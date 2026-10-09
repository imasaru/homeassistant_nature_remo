# Nature Remo - Home Assistant Custom Integration

⭐ If this integration helps you, please consider giving it a star on GitHub!

📄 日本語版のREADMEはこちら 👉 [README_ja.md](README_ja.md)

This is a custom integration for linking Nature Remo devices with Home Assistant.  
It enables you to control appliances like air conditioners and lights, and monitor temperature, humidity, and more directly in your smart home setup.

---

## ⚠️ Disclaimer
This is an **unofficial** integration and is not affiliated with Nature Inc. or Home Assistant.  
Please use this integration **at your own risk**.

---

## Features

- Control appliances (air conditioners, lights) registered to Nature Remo
- Retrieve temperature, humidity, illuminance, and motion sensor data
- Access smart meter data (consumption, generation, instant power) via Nature Remo E / E Lite
- Control lighting modes using custom service calls
- Send IR commands using remote entities created from defined signals
- Optional local (LAN) IR control of supported air conditioners via the Nature Remo local API

---

## Installation (via HACS)

Click the button below to easily add this repository to HACS.

[![Open your Home Assistant instance and open the repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=NaNaLinks&repository=homeassistant_nature_remo&category=integration)

1. Open HACS in Home Assistant
2. Click the menu (⋮) in the top right corner
3. Select "Custom repositories"
4. Add this repository URL:
   https://github.com/NaNaLinks/homeassistant_nature_remo  
   Category: Integration
5. Install "Nature Remo"
6. Restart Home Assistant

---

## Installation (Manual)

1. Download or clone this repository and place it in the following path:

```
<config directory>/custom_components/nature_remo/
```

2. Restart Home Assistant.

---

## Setup Instructions

1. Go to *Settings → Devices & Services → Add Integration* and search for `Nature Remo`
2. Enter your access token (API key) and integration name
   - You can issue an API token at [Nature Official Site](https://home.nature.global)
3. Your registered appliances will be automatically imported as entities

---

## Options

- You can set the update interval (in seconds)
  - Default: `60 seconds`

⚠️ Nature Remo Cloud API has rate limits.  
Setting a very short update interval may cause the integration to reach the API request limit.

---

## Supported Entities

| Type    | Description                                                        |
|---------|--------------------------------------------------------------------|
| climate | Control air conditioners (cooling, heating, dry)                   |
| light   | Control lights (on/off, mode selection)                            |
| sensor  | Temperature, humidity, illuminance, motion, power (buy/sell)      |
| remote  | Send infrared signals defined as "signals" for IR/AC/LIGHT types  |

*Additional entities may be supported in future updates.*

---

## Sample: Using Remote Entities

This integration supports `remote` entities generated from Nature Remo's defined `signals`. These entities allow you to send IR commands directly from Home Assistant.

### Example: Service Call

You can call a signal like this using `remote.send_command`:

```yaml
service: remote.send_command
target:
  entity_id: remote.living_room_remote  # Your remote entity ID
data:
  command: "Power On"  # The name of the signal as defined in Remo
```

---

## External Temperature and Humidity Sensors

You can now configure external temperature and humidity sensors for each device.

By selecting entities from Home Assistant settings, the climate device will use the specified sensors instead of the default values provided by Nature Remo.

### How it works

- Open the integration settings from Home Assistant
- Select a device
- Choose temperature and humidity entities from available sensors
- Save the configuration

Once configured, the selected external sensors will be used for:

- Displaying temperature and humidity in the climate entity
- Providing more accurate environmental data for air conditioner control

### Notes

- If no external sensors are configured, the integration will continue to use the default values from Nature Remo
- Any sensor entity with appropriate temperature or humidity values can be used

---

## Local IR control (optional, experimental)

Air conditioners can be controlled **directly over the LAN** through the Nature Remo
local API (`POST http://<remo-ip>/messages`) instead of the cloud. The integration
encodes the complete AC state itself and sends it as a raw IR signal, so commands
are fast, work without internet access, and are not affected by cloud rate limits
or by cloud-side validation of values such as the temperature step.

Currently supported local IR protocols:

| Protocol          | Air conditioners                                                      |
|-------------------|-----------------------------------------------------------------------|
| `fujitsu_arrff2j` | Fujitsu General (nocria) using the AR-RFF2J remote (AEHA, 16-byte frame) |

### Setup

1. Give the Nature Remo a fixed IP address (DHCP reservation) on your router.
2. *Settings → Devices & Services → Nature Remo → Configure*:
   - `<Remo name> : IP Address` – the Remo's IP, e.g. `192.168.10.150`
     (a bare host or `http://host` both work).
   - `Nature Remo <AC name> : Local IR protocol (none = cloud)` – choose `fujitsu_arrff2j`.
   - Optional: `<Remo name> : Detect remote presses via local API (poll /messages)` (default off, see below).
3. Reload the integration (⋮ → Reload) or restart Home Assistant.

Nature Remo nano does not offer the local API.

### Behaviour

- Each change (mode, temperature, fan, swing, on/off) sends **one full-state frame**
  with a ~3 s timeout. The *power-on* bit is set only when turning on from off.
- If the local send fails (timeout, connection error, non-2xx), the command is sent through
  the **cloud API** instead and a warning is logged.
- Temperature step is 0.5 °C (16–30 °C; cooling 18–30 °C). Modes: off, cool, heat, dry, auto
  (fan-only cannot be expressed by this protocol).
- The state is **optimistic** (IR has no feedback) and is restored after a restart.
  Because local sends never reach the Nature cloud, cloud AC settings are ignored unless
  they change (e.g. you used the Nature app), and are also ignored for 60 s after a local send.
- Extra attributes on the climate entity: `local_protocol`, `local_host`,
  `last_command_path` (`local`, `cloud` or `remote_ir`), `last_local_error`, `last_remote_ir`.

### Detecting physical remote presses (optional)

When enabled, the integration polls `GET /messages` every 2 s. The Remo keeps only the
**last** IR signal it received, without timestamp, so a press is detected when that signal
changes and decodes to a valid frame. Limitations:

- The Remo must be able to *see* the remote's IR; place it accordingly.
- Several presses within one poll interval: only the last one is seen (the protocol always
  carries the full state, so the final state is still correct). Repeating the exact same
  press is not detectable (harmless, the state is unchanged).
- If more than one AC on the same Remo uses the same protocol the press cannot be attributed
  and is ignored. ACs of the same type elsewhere in the house can still be "overheard".
- The first poll after startup is only used as a baseline.

---

## Author

- Author: [@nanosns](https://github.com/nanosns) (NaNaRin)
- Project: [@NaNaLinks](https://github.com/NaNaLinks)
- Socials: [note](https://note.com/nanomana)

---

## License

MIT License