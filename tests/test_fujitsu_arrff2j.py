"""Unit tests for the AR-RFF2J encoder/decoder (no Home Assistant needed)."""
import importlib.util
import json
import pathlib
import random
import sys

import pytest

MOD_PATH = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "nature_remo" / "ir" / "fujitsu_arrff2j.py"
spec = importlib.util.spec_from_file_location("fujitsu_arrff2j", MOD_PATH)
f = importlib.util.module_from_spec(spec)
sys.modules["fujitsu_arrff2j"] = f
spec.loader.exec_module(f)

# Debug frames captured from the physical AR-RFF2J remote (west room ESPHome YAML)
COOL_225_POWER_ON = [0x00, 0x08, 0x08, 0x7F, 0xD0, 0x82, 0xAE, 0x80, 0, 0, 0, 0, 0, 0x48, 0xE0, 0x0C]
HEAT_225 = [0x00, 0x08, 0x08, 0x7F, 0xD0, 0x82, 0x2E, 0x20, 0, 0, 0, 0, 0, 0x48, 0xE0, 0x74]


def test_known_cool_frame():
    st = f.FujitsuState(mode="cool", temperature=22.5, power_on=True)
    assert f.encode_state(st) == COOL_225_POWER_ON


def test_known_heat_frame():
    st = f.FujitsuState(mode="heat", temperature=22.5, power_on=False)
    assert f.encode_state(st) == HEAT_225


def test_off_frame():
    assert f.encode_state(f.FujitsuState(mode="off")) == [0x00, 0x08, 0x08, 0x40, 0xBF]
    sig = f.build_signal(f.FujitsuState(mode="off"))
    assert f.decode_remo_signal(sig).mode == "off"


def test_checksum_on_known_frames():
    assert f.checksum(COOL_225_POWER_ON) == 0x0C
    assert f.checksum(HEAT_225) == 0x74


def test_frame_sent_on_2026_10_09():
    """Exact frame POSTed to the living room Remo (cool 25, fan auto, power-on)."""
    st = f.FujitsuState(mode="cool", temperature=25.0, power_on=True)
    assert f.encode_state(st) == [0x00, 0x08, 0x08, 0x7F, 0xD0, 0x82, 0x91, 0x80, 0, 0, 0, 0, 0, 0x48, 0xE0, 0x38]


def test_signal_timings():
    sig = f.build_signal(f.FujitsuState(mode="cool", temperature=25.0, power_on=True))
    assert sig["format"] == "us" and sig["freq"] == 38
    d = sig["data"]
    assert d[:2] == [3400, 1700]
    assert len(d) == 2 + 2 * (16 + 16 * 8) + 1
    assert d[-1] == 425
    assert set(d[2:-1:2]) == {425} and set(d[3:-1:2]) <= {425, 1275}


@pytest.mark.parametrize("mode", ["cool", "heat", "auto"])
@pytest.mark.parametrize("fan", ["auto", "low", "med_low", "medium", "high"])
@pytest.mark.parametrize("swing", ["off", "vertical", "horizontal", "both"])
def test_round_trip(mode, fan, swing):
    for half in range(0, 29):
        temp = 16.0 + half / 2
        if mode == "cool" and temp < 18.0:
            continue
        for power in (False, True):
            st = f.FujitsuState(mode=mode, temperature=temp, fan=fan, swing=swing, power_on=power)
            back = f.decode_remo_signal(f.build_signal(st))
            assert back is not None
            assert (back.mode, back.temperature, back.fan, back.swing, back.power_on) == (mode, temp, fan, swing, power)
            footer = back.raw[14]
            assert footer == (0xE0 if (fan == "auto" and swing == "off") else 0xC0)


def test_cool_clamps_to_18():
    st = f.FujitsuState(mode="cool", temperature=16.0)
    assert f.decode_payload(f.encode_state(st)).temperature == 18.0


def test_dry_frames():
    full = f.encode_state(f.FujitsuState(mode="dry", power_on=True))
    assert full[6] == 0x9E and full[7] == 0xA0 and full[14] == 0xC0
    mild = f.decode_payload(f.encode_state(f.FujitsuState(mode="dry", mild_dry=True)))
    assert mild.mode == "dry" and mild.mild_dry and not mild.power_on


def test_decoder_tolerates_jitter_and_repeats():
    rnd = random.Random(1)
    sig = f.build_signal(f.FujitsuState(mode="heat", temperature=21.5, fan="high", swing="vertical"))
    noisy = [max(1, int(x * rnd.uniform(0.8, 1.2))) for x in sig["data"]]
    # leading noise + frame + gap + repeated frame
    data = [2241, 65535, 0, 62586] + noisy + [30000] + noisy
    back = f.decode_remo_signal({"format": "us", "freq": 37, "data": data})
    assert back and (back.mode, back.temperature, back.fan, back.swing) == ("heat", 21.5, "high", "vertical")


def test_decoder_rejects_noise_and_bad_checksum():
    noise = {"format": "us", "freq": 29, "data": [2241, 65535, 0, 62586, 2185, 65535, 0, 62629, 2287]}
    assert f.decode_remo_signal(noise) is None
    bad = list(COOL_225_POWER_ON)
    bad[15] ^= 0x01
    assert f.decode_remo_signal(f.to_remo_signal(bad)) is None


def test_hyper_frame_decodes_as_special():
    st = f.decode_remo_signal(f.to_remo_signal(list(f.HYPER_FRAME)))
    assert st.special == "hyper"


def test_matches_box_script_output():
    p = pathlib.Path("/workspace/remo_local/frame_cool25_auto.json")
    if not p.exists():
        pytest.skip("reference frame not present")
    ref = json.loads(p.read_text())
    assert f.build_signal(f.FujitsuState(mode="cool", temperature=25.0, power_on=True)) == ref
