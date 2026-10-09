"""Fujitsu AR-RFF2J (AS-C226H) IR protocol for the Nature Remo local API.

Port of the ESPHome external component ``fujitsu_arrff2j`` (AEHA address 0x28C6)
and of ESPHome's ``remote_base/aeha_protocol.cpp`` timings. Pure Python: this
module must not import Home Assistant so it can be unit-tested standalone.

Frame layout (16 bytes after the 16-bit AEHA address):
  0..5  fixed header 00 08 08 7F D0 82
  6     temperature byte (bit 0x80 = power-on flag, only when turning on)
  7     mode (cool 0x80, heat 0x20, dry 0xA0, auto 0x00)
  8     fan | swing
  9..12 zero
  13    fixed 0x48
  14    footer (0xE0 normal / 0xC0 when fan or swing non-default; dry: E0 mild, C0 full)
  15    checksum
Short "util" frames (5 bytes): OFF = 00 08 08 40 BF, high power toggle = 00 08 08 9C 63.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PROTOCOL = "fujitsu_arrff2j"

ADDRESS = 0x28C6
HEADER_BYTES = (0x00, 0x08, 0x08, 0x7F, 0xD0, 0x82)
FIXED13 = 0x48
FOOTER_NORMAL = 0xE0
FOOTER_ALT = 0xC0
POWER_ON_FLAG = 0x80
DRY_TEMP_BYTE = 0x1E

TEMP_MIN = 16.0
TEMP_MAX = 30.0
TEMP_STEP = 0.5
COOL_MIN = 18.0

MODE_AUTO = "auto"
MODE_COOL = "cool"
MODE_HEAT = "heat"
MODE_DRY = "dry"
MODE_OFF = "off"

MODE_BYTES = {MODE_AUTO: 0x00, MODE_HEAT: 0x20, MODE_COOL: 0x80, MODE_DRY: 0xA0}
FAN_BYTES = {"auto": 0x00, "high": 0x10, "medium": 0x60, "med_low": 0xC0, "low": 0x80}
SWING_BYTES = {"off": 0x00, "horizontal": 0x04, "vertical": 0x08, "both": 0x0C}

OFF_FRAME = (0x00, 0x08, 0x08, 0x40, 0xBF)
HYPER_FRAME = (0x00, 0x08, 0x08, 0x9C, 0x63)

# ESPHome AEHA timings (microseconds)
T = 425
HEADER_MARK = T * 8
HEADER_SPACE = T * 4
BIT_MARK = T
ONE_SPACE = T * 3
ZERO_SPACE = T
TRAILER = T
CARRIER_KHZ = 38


@dataclass
class FujitsuState:
    """Decoded/desired AC state."""

    mode: str  # off/cool/heat/dry/auto
    temperature: float | None = None
    fan: str = "auto"
    swing: str = "off"
    power_on: bool = False
    mild_dry: bool = False
    special: str | None = None  # e.g. "hyper" for util frames
    raw: list[int] = field(default_factory=list)


def bitrev8(x: int) -> int:
    x &= 0xFF
    x = ((x & 0xF0) >> 4) | ((x & 0x0F) << 4)
    x = ((x & 0xCC) >> 2) | ((x & 0x33) << 2)
    x = ((x & 0xAA) >> 1) | ((x & 0x55) << 1)
    return x & 0xFF


def _lround(x: float) -> int:
    # C lroundf: halves away from zero (Python round() is banker's rounding)
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


def encode_temperature(temp: float, mode: str, power_on: bool) -> int:
    t = min(max(float(temp), TEMP_MIN), TEMP_MAX)
    if mode == MODE_COOL and t < COOL_MIN:
        t = COOL_MIN
    half = max(0, min(28, _lround((t - TEMP_MIN) * 2.0)))
    whole, is_half = half // 2, half % 2 == 1
    group, offset = (0x02, whole) if whole < 8 else (0x01, whole - 8)
    br = ((offset & 1) << 2) | (offset & 2) | ((offset & 4) >> 2)
    b = group | (br << 2)
    if is_half:
        b |= 0x20
    if power_on:
        b |= POWER_ON_FLAG
    return b


def decode_temperature(b: int) -> float | None:
    group = b & 0x03
    if group not in (0x01, 0x02):
        return None
    br = (b >> 2) & 0x07
    offset = ((br & 1) << 2) | (br & 2) | ((br & 4) >> 2)
    whole = offset if group == 0x02 else offset + 8
    return TEMP_MIN + whole + (0.5 if b & 0x20 else 0.0)


def checksum(msg15: list[int] | tuple[int, ...]) -> int:
    full = [bitrev8(0x28), bitrev8(0xC6)] + [bitrev8(b) for b in msg15[:15]]
    s = sum(full[7:17]) & 0xFF
    return bitrev8((256 - s) & 0xFF)


def encode_state(state: FujitsuState) -> list[int]:
    """Return the AEHA payload bytes for a state (OFF -> 5-byte off frame)."""
    if state.mode == MODE_OFF:
        return list(OFF_FRAME)
    if state.mode not in MODE_BYTES:
        raise ValueError(f"unsupported mode {state.mode}")
    msg = list(HEADER_BYTES)
    if state.mode == MODE_DRY:
        msg.append(DRY_TEMP_BYTE | (POWER_ON_FLAG if state.power_on else 0))
        fan_swing = 0x00  # dry: fan auto, no swing (as the ESPHome component)
        footer = FOOTER_NORMAL if state.mild_dry else FOOTER_ALT
    else:
        temp = state.temperature if state.temperature is not None else 22.5
        msg.append(encode_temperature(temp, state.mode, state.power_on))
        fan = FAN_BYTES.get(state.fan, 0x00)
        swing = SWING_BYTES.get(state.swing, 0x00)
        fan_swing = fan | swing
        footer = FOOTER_ALT if (state.fan != "auto" or state.swing != "off") else FOOTER_NORMAL
    msg.append(MODE_BYTES[state.mode])
    msg.append(fan_swing)
    msg += [0, 0, 0, 0, FIXED13, footer]
    msg.append(checksum(msg))
    return msg


def to_remo_signal(payload: list[int]) -> dict:
    """AEHA payload -> Nature Remo local API IRSignal (MSB-first, as ESPHome)."""
    data = [HEADER_MARK, HEADER_SPACE]
    bits = [(ADDRESS >> (15 - i)) & 1 for i in range(16)]
    for byte in payload:
        bits += [(byte >> (7 - i)) & 1 for i in range(8)]
    for bit in bits:
        data += [BIT_MARK, ONE_SPACE if bit else ZERO_SPACE]
    data.append(TRAILER)
    return {"format": "us", "freq": CARRIER_KHZ, "data": data}


def build_signal(state: FujitsuState) -> dict:
    return to_remo_signal(encode_state(state))


# ---------------------------------------------------------------- decoding
def _frames_from_timings(data: list[int]) -> list[list[int]]:
    """Split a mark/space list into AEHA frames (jitter tolerant). Returns bit lists
    as byte lists including the 2 address bytes."""
    frames: list[list[int]] = []
    i, n = 0, len(data)
    while i + 1 < n:
        mark, space = data[i], data[i + 1]
        # header: ~3400/1700, accept wide tolerance
        if 2400 <= mark <= 4800 and 1100 <= space <= 2500:
            bits: list[int] = []
            j = i + 2
            while j + 1 < n:
                m, s = data[j], data[j + 1]
                if not (150 <= m <= 900):
                    break
                if 150 <= s <= 850:
                    bits.append(0)
                elif 850 < s <= 2000:
                    bits.append(1)
                else:
                    break  # long gap / end of frame
                j += 2
            if len(bits) >= 16 + 8:
                nbytes = len(bits) // 8
                frames.append(
                    [int("".join(map(str, bits[k * 8:(k + 1) * 8])), 2) for k in range(nbytes)]
                )
            i = j
        else:
            i += 1
    return frames


def decode_payload(payload: list[int]) -> FujitsuState | None:
    """Decode AEHA payload bytes (without address)."""
    if len(payload) == 5 and tuple(payload) == OFF_FRAME:
        return FujitsuState(mode=MODE_OFF, raw=list(payload))
    if len(payload) == 5 and tuple(payload) == HYPER_FRAME:
        return FujitsuState(mode="unchanged", special="hyper", raw=list(payload))
    if len(payload) != 16 or tuple(payload[:6]) != HEADER_BYTES or payload[13] != FIXED13:
        return None
    if checksum(payload) != payload[15]:
        return None
    mode_by_byte = {v: k for k, v in MODE_BYTES.items()}
    mode = mode_by_byte.get(payload[7])
    if mode is None:
        return None
    power_on = bool(payload[6] & POWER_ON_FLAG)
    if mode == MODE_DRY:
        return FujitsuState(mode=mode, temperature=None, power_on=power_on,
                            mild_dry=payload[14] == FOOTER_NORMAL, raw=list(payload))
    fan = {v: k for k, v in FAN_BYTES.items()}.get(payload[8] & 0xF0, "auto")
    swing = {v: k for k, v in SWING_BYTES.items()}.get(payload[8] & 0x0C, "off")
    return FujitsuState(mode=mode, temperature=decode_temperature(payload[6] & 0x7F),
                        fan=fan, swing=swing, power_on=power_on, raw=list(payload))


def decode_remo_signal(signal: dict) -> FujitsuState | None:
    """Decode a Remo IRSignal ({"format","freq","data"}) into a FujitsuState.

    Returns None if no valid AR-RFF2J frame is found. Real captures have timing
    jitter and may contain repeated frames; the first valid frame wins.
    """
    if not isinstance(signal, dict) or signal.get("format", "us") != "us":
        return None
    data = signal.get("data") or []
    if not isinstance(data, list) or len(data) < 2 + 2 * 24:
        return None
    for frame in _frames_from_timings([int(x) for x in data]):
        address = (frame[0] << 8) | frame[1]
        if address != ADDRESS:
            continue
        state = decode_payload(frame[2:])
        if state is not None:
            return state
    return None
