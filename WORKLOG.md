# TT RGB Plus / SWAFAN EX14 Ubuntu Worklog

Date: 2026-05-13

## Goal

Control Thermaltake SWAFAN EX14 RGB case fans on Ubuntu, with fan speed increasing
automatically from CPU or GPU load.

## Hardware observed on Ubuntu

User has 4 kits of:

- Thermaltake SWAFAN EX14 RGB, 14 cm, White

Ubuntu `lsusb` output showed the relevant controller:

```text
Bus 007 Device 009: ID 264a:232b Thermaltake LEDFanBox
```

`liquidctl list --verbose` did not detect this Thermaltake controller. It only
detected:

```text
Device #0: Gigabyte RGB Fusion 2.0 5702 Controller
Vendor ID: 0x048d
Product ID: 0x5702
Driver: RgbFusion2
```

`usbhid-dump` for the Thermaltake controller showed:

```text
007:009:000:DESCRIPTOR
06 00 FF 09 01 A1 01 15 00 26 FF 00 75 08 95 40
09 01 81 02 95 C0 09 01 91 02 C0
```

Interpretation:

- Vendor-defined HID device.
- Input report count `0x40` = 64 bytes.
- Output report count `0xC0` = 192 bytes.
- With `hidapi`, writes should include report id, so profile uses write length
  `193`.

## Windows installer findings

Original file:

```text
D:\Downloads\TTRGBPLUS_Setup_307_x64\TT RGB PLUS_Setup_3.0.7_x64.exe
```

It is a Windows NSIS installer with Windows binaries and drivers. It cannot be
converted directly into Ubuntu software.

Useful extracted/observed strings from Windows binaries included:

- `SWAFAN RGB`
- `SWAFAN EX RGB`
- `SWAFAN EX RGB SINGLE`
- `VID_264A&PID_232B`
- PID ranges including `2199`-`21A8`, `2260`-`226F`, `232B`-`233A`

## Files created

Folder:

```text
D:\Downloads\TTRGBPLUS_Setup_307_x64\ubuntu-tt-rgb-plus
```

Files:

- `tt_rgb_plus.py` - Python CLI for Linux HID control.
- `install_ubuntu.sh` - installs dependencies, udev rule, and systemd service.
- `99-thermaltake-tt-rgb-plus.rules` - udev rule for Thermaltake VID `264a`.
- `tt-rgb-plus-auto.service` - systemd service for automatic fan control.
- `build_deb.sh` - builds a local Debian package.
- `packaging/tt-rgb-plus.default` - packaged service configuration.
- `packaging/tt-rgb-plus-auto.service` - packaged systemd service.
- `README.md` - usage instructions.
- `WORKLOG.md` - this context file.

## Current script capabilities

`tt_rgb_plus.py` supports:

- `list`
- `sensors`
- `monitor`
- `config`
- `topology`
- `status`
- `set-speed`
- `set-rgb`
- `rgb-off`
- `set-rgb-raw`
- `scan-rgb-modes`
- `set-rgb-effect`
- `auto`
- `auto-temp`
- `auto-control`

Current known controller profiles:

- Riing Controller: `264a:1f41`-`264a:1f51`
- Riing Plus Controller: `264a:1fa5`-`264a:1fb5`
- Riing Trio Controller: `264a:2135`-`264a:2145`
- SWAFAN EX / Hiyatek: `264a:2199`-`264a:21a8`
- Riing Quad Controller: `264a:2260`-`264a:226f`
- SWAFAN EX LEDFanBox: `264a:232b`-`264a:233a`, write length `193`

RGB control:

- Static RGB command is implemented as `[0x32, 0x52, PORT, FULL_MODE, COLOR]`.
- Riing uses full mode `0x01` and RGB byte order.
- SWAFAN EX LEDFanBox uses raw mode `0x24` for static color and needs a
  per-LED payload; `set-rgb --port-fans` calculates this for SWAFAN EX chains.
- Commands: `set-rgb COLOR` and `rgb-off`.
- Built-in RGB effects: `set-rgb-effect flow|spectrum|ripple|blink|pulse|wave|per-led slow|normal|fast|extreme`.
- `set-rgb-effect --port-fans 1:3,2:3,3:3,4:1` calculates LED payload length
  per port for SWAFAN EX chains, using 20 LEDs per fan.
- `auto-temp --rgb-sync --rgb-style color|flow|spectrum` syncs lighting with
  calculated fan speed. `color` changes static color from blue/cyan to red;
  `flow` and `spectrum` increase circular effect speed with fan speed.

Automatic mode:

- Reads CPU load through `psutil`.
- Reads NVIDIA GPU load through `nvidia-smi` if available.
- `--source max` uses whichever is higher, CPU or GPU.
- Applies load-to-speed curve such as `0:30,30:40,50:60,70:80,85:100`.
- `--all-controllers` applies to all supported Thermaltake controllers.

Temperature mode:

- `sensors` lists available temperature sensors.
- `auto-temp` reads temperatures through `psutil.sensors_temperatures()`.
- NVIDIA GPU temperature is added through `nvidia-smi` if available.
- `--source max` uses the hottest available sensor.
- `--sensor TEXT` can pin to a chip/label, such as `Tctl`, `Package`, `k10temp`,
  `coretemp`, or `nvidia`.
- `--sensors A B C` selects the hottest sensor matching any listed text, for
  example `--sensors Tctl nvidia nvme`.
- Applies temperature-to-speed curve such as `30:25,40:35,55:55,70:80,80:100`.
- `auto-temp` writes current state to `/run/tt-rgb-plus/state.json`.
- `monitor` reads this state and prints controller info, selected sensor,
  calculated fan speed, RGB mode, and all temperatures without opening HID.

Unified control:

- `auto-control --mode temp` delegates to temperature control.
- `auto-control --mode load` delegates to CPU/GPU load control.
- Packaged service config in `/etc/default/tt-rgb-plus` now uses
  `auto-control`, so users can switch modes by editing one option line.
- `config` can generate `/etc/default/tt-rgb-plus` and optionally restart the
  packaged service, for example `sudo tt-rgb-plus config --mode load --restart`.
- `topology` stores controller/port/fan counts in `/etc/tt-rgb-plus/topology.json`.
  RGB commands and `config --use-topology` can then target only occupied ports
  and calculate LED payload sizes automatically.
- `topology wizard` turns all checked ports off once, lights ports red one at a
  time, asks how many fans lit up, and leaves detected ports in a normal RGB
  effect while continuing.

## Commands to run on Ubuntu

Install dependencies:

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv libhidapi-hidraw0 libhidapi-libusb0 usbutils
python3 -m pip install --user --upgrade hidapi psutil
```

If Ubuntu blocks user pip installs due to PEP 668, use one of these:

```bash
python3 -m pip install --user --break-system-packages --upgrade hidapi psutil
```

or create a venv:

```bash
python3 -m venv ~/.venvs/tt-rgb-plus
~/.venvs/tt-rgb-plus/bin/pip install --upgrade hidapi psutil
~/.venvs/tt-rgb-plus/bin/python tt_rgb_plus.py list --all
```

Basic detection:

```bash
lsusb | grep -i 264a
sudo python3 tt_rgb_plus.py list --all
```

Status:

```bash
sudo python3 tt_rgb_plus.py status --all-controllers --ports 1 2 3 4 5
```

Manual speed test:

```bash
sudo python3 tt_rgb_plus.py set-speed 40 --all-controllers --ports 1 2 3 4 5
sudo python3 tt_rgb_plus.py set-speed 70 --all-controllers --ports 1 2 3 4 5
```

Automatic CPU/GPU load curve:

```bash
sudo python3 tt_rgb_plus.py auto --source max --all-controllers --ports 1 2 3 4 5 --curve 0:30,30:40,50:60,70:80,85:100
```

Temperature sensors and automatic temperature curve:

```bash
sudo python3 tt_rgb_plus.py sensors
sudo python3 tt_rgb_plus.py auto-temp --source max --all-controllers --ports 1 2 3 4 5 --curve 30:25,40:35,55:55,70:80,80:100
```

Systemd service:

```bash
sudo mkdir -p /opt/tt-rgb-plus
sudo cp tt_rgb_plus.py /opt/tt-rgb-plus/
sudo cp tt-rgb-plus-auto.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tt-rgb-plus-auto.service
systemctl status tt-rgb-plus-auto.service
```

## Next debugging steps after machine access

1. Copy or sync the latest `ubuntu-tt-rgb-plus` folder to Ubuntu.
2. Run `sudo python3 tt_rgb_plus.py list --all`.
3. Run `sudo python3 tt_rgb_plus.py status --all-controllers --ports 1 2 3 4 5`.
4. If `status` returns no reply, test whether LEDFanBox needs feature reports or
   a different init command.
5. Try `set-speed 40` and `set-speed 70` on individual ports first.
6. If no change, capture HID traffic from Windows TT RGB Plus while changing fan
   speed, then mirror the exact command format in `tt_rgb_plus.py`.

## Important caveat

The profile for `264a:232b` is inferred from the Windows installer strings,
public TT RGB Plus API notes, and the user's HID descriptor. It may need one
round of live testing to confirm whether speed command payload
`[0x32, 0x51, PORT, 0x01, SPEED]` works for LEDFanBox.
