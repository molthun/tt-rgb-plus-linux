# TT RGB Plus Linux

Unofficial Linux control utility for Thermaltake TT RGB Plus USB HID fan/RGB
controllers.

The original Thermaltake `TT RGB PLUS` application is a Windows installer with
Windows drivers. This project does not convert that application; it talks to the
USB HID controller directly from Linux.

Tested hardware:

- Thermaltake SWAFAN EX14 RGB White kits
- `264a:232b Thermaltake LEDFanBox`
- Ubuntu 24.04 LTS

## Features

- List supported Thermaltake USB HID controllers.
- Set fan speed by percent.
- Control static RGB color and built-in circular RGB effects.
- Automatic fan control by temperature.
- Automatic fan control by CPU/GPU load.
- Sync RGB with calculated fan speed.
- Monitor current control state and sensor readings.
- Installable Debian package with udev rules and systemd service.

## Supported Controllers

Known profiles:

- Riing Controller: `264a:1f41`-`264a:1f51`
- Riing Plus Controller: `264a:1fa5`-`264a:1fb5`
- Riing Trio Controller: `264a:2135`-`264a:2145`
- SWAFAN EX / Hiyatek Controller: `264a:2199`-`264a:21a8`
- Riing Quad Controller: `264a:2260`-`264a:226f`
- SWAFAN EX LEDFanBox Controller: `264a:232b`-`264a:233a`

The `264a:232b` LEDFanBox profile has been tested for fan speed control,
temperature/load automation, monitoring, static RGB, and circular RGB effect
selection.

## Install

Download the latest `.deb` from GitHub Releases:

```bash
cd /tmp
wget -O tt-rgb-plus_0.2.0_all.deb https://github.com/molthun/tt-rgb-plus-linux/releases/download/v0.2.0/tt-rgb-plus_0.2.0_all.deb
sudo apt install ./tt-rgb-plus_0.2.0_all.deb
```

The package installs:

- `/usr/bin/tt-rgb-plus`
- `/etc/default/tt-rgb-plus`
- `/etc/udev/rules.d/99-thermaltake-tt-rgb-plus.rules`
- `/lib/systemd/system/tt-rgb-plus-auto.service`

Unplug and reconnect the controller after installing udev rules, or reboot.

## Quick Start

List controllers:

```bash
tt-rgb-plus list --all
```

List temperature sensors:

```bash
tt-rgb-plus sensors
```

Set fan speed:

```bash
tt-rgb-plus set-speed 50 --all-controllers --ports 1 2 3 4 5
```

Set RGB:

```bash
tt-rgb-plus set-rgb '#00aaff' --all-controllers --ports 1 2 3 4 5
tt-rgb-plus rgb-off --all-controllers --ports 1 2 3 4 5
```

Set a circular RGB effect:

```bash
tt-rgb-plus set-rgb-effect spectrum slow --all-controllers --ports 1 2 3 4 5
tt-rgb-plus set-rgb-effect flow normal --all-controllers --ports 1 2 3 4 5
```

Monitor state without taking over the HID controller:

```bash
tt-rgb-plus monitor
tt-rgb-plus monitor --watch --clear
```

## Automatic Control

`auto-control` is the recommended command for services. It supports two modes:

- `--mode temp` for temperature-based control
- `--mode load` for CPU/GPU load-based control

Temperature mode for an AI server:

```bash
tt-rgb-plus auto-control \
  --mode temp \
  --sensors Tctl nvidia nvme it87952 \
  --all-controllers \
  --ports 1 2 3 4 5 \
  --interval 2 \
  --step 2 \
  --temp-curve 30:18,40:24,50:38,60:58,70:80,80:100 \
  --rgb-sync \
  --rgb-style spectrum
```

Load mode:

```bash
tt-rgb-plus auto-control \
  --mode load \
  --load-source max \
  --all-controllers \
  --ports 1 2 3 4 5 \
  --interval 2 \
  --step 2 \
  --load-curve 0:20,30:30,50:50,70:75,90:100 \
  --rgb-sync \
  --rgb-style spectrum
```

`--rgb-style color` changes static color from blue/cyan at low speed to red at
high speed. `flow` and `spectrum` use built-in circular effects and increase
effect speed as fan speed rises.

Legacy commands are still available:

- `auto` for CPU/GPU load
- `auto-temp` for temperature

## Systemd Service

Edit service options:

```bash
sudo nano /etc/default/tt-rgb-plus
```

Default temperature mode:

```bash
TT_RGB_PLUS_ARGS="auto-control --mode temp --sensors Tctl nvidia nvme it87952 --all-controllers --ports 1 2 3 4 5 --interval 2 --step 2 --temp-curve 30:18,40:24,50:38,60:58,70:80,80:100 --rgb-sync --rgb-style spectrum"
```

Alternative load mode:

```bash
TT_RGB_PLUS_ARGS="auto-control --mode load --load-source max --all-controllers --ports 1 2 3 4 5 --interval 2 --step 2 --load-curve 0:20,30:30,50:50,70:75,90:100 --rgb-sync --rgb-style spectrum"
```

Enable and start:

```bash
sudo systemctl enable --now tt-rgb-plus-auto.service
```

Restart after config changes:

```bash
sudo systemctl restart tt-rgb-plus-auto.service
```

Logs:

```bash
journalctl -u tt-rgb-plus-auto.service -f
```

## Build From Source

```bash
git clone https://github.com/molthun/tt-rgb-plus-linux.git
cd tt-rgb-plus-linux
chmod +x build_deb.sh
./build_deb.sh 0.2.0
sudo apt install ./dist/tt-rgb-plus_0.2.0_all.deb
```

For direct source usage:

```bash
sudo apt install python3 python3-psutil python3-hid libhidapi-hidraw0 libhidapi-libusb0 usbutils lm-sensors
python3 tt_rgb_plus.py list --all
```

## Troubleshooting

Check whether Linux sees the controller:

```bash
lsusb | grep -i 264a
tt-rgb-plus list --all
```

If the command only works with `sudo`, reload udev rules and reconnect the
controller:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Check service status:

```bash
systemctl status tt-rgb-plus-auto.service
journalctl -u tt-rgb-plus-auto.service -n 100 --no-pager
```

If your controller has a different PID, open an issue with:

```bash
lsusb
tt-rgb-plus list --all
tt-rgb-plus sensors
sudo usbhid-dump
```

## Protocol Notes

The HID commands are based on public TT RGB Plus protocol notes by MoshiMoshi0:

- https://moshimoshi0.github.io/ttrgbplusapi/
- https://github.com/MoshiMoshi0/ttrgbplusapi

This project is unofficial and is not affiliated with Thermaltake.
