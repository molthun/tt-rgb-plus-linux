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

For SWAFAN EX chains, static color can also use `--port-fans` so the LED
payload matches the number of fans per port:

```bash
tt-rgb-plus set-rgb red --port-fans 1:3,2:3,3:3,4:1 --all-controllers --ports 1 2 3 4
tt-rgb-plus rgb-off --port-fans 1:3,2:3,3:3,4:1 --all-controllers --ports 1 2 3 4
```

Set a circular RGB effect:

```bash
tt-rgb-plus set-rgb-effect spectrum slow --all-controllers --ports 1 2 3 4 5
tt-rgb-plus set-rgb-effect flow normal --all-controllers --ports 1 2 3 4 5
```

Other RGB effects:

```bash
tt-rgb-plus set-rgb-effect ripple fast --color '#00aaff' --all-controllers --ports 1 2 3 4 5
tt-rgb-plus set-rgb-effect pulse normal --color red --led-count 20 --all-controllers --ports 1 2 3 4 5
tt-rgb-plus set-rgb-effect wave slow --color '#ffaa00' --led-count 20 --all-controllers --ports 1 2 3 4 5
tt-rgb-plus set-rgb-effect blink normal --colors '#ff0000,#00ff00,#0000ff' --led-count 20 --all-controllers --ports 1
```

For SWAFAN EX chains, use `--port-fans` instead of manually calculating LED
counts. Each SWAFAN EX fan is treated as 20 LEDs. Example for one controller
with three 3-fan chains and one single fan:

```bash
tt-rgb-plus set-rgb-effect wave slow --color '#ffaa00' --port-fans 1:3,2:3,3:3,4:1 --all-controllers --ports 1 2 3 4
```

Monitor state without taking over the HID controller:

```bash
tt-rgb-plus monitor
tt-rgb-plus monitor --watch --clear
```

Save your physical layout once, then reuse it:

```bash
tt-rgb-plus topology detect
sudo tt-rgb-plus topology wizard
sudo tt-rgb-plus topology set '1:3,2:3' '1:3,2:1'
tt-rgb-plus topology show
```

`topology wizard` turns all checked ports off once, lights one controller/port
red at a time, asks how many fans lit up, then leaves found ports running in a
normal RGB effect while continuing. Empty ports stay off. At the end it saves
`/etc/tt-rgb-plus/topology.json`.

The example means:

- controller `0`: port 1 has 3 fans, port 2 has 3 fans
- controller `1`: port 1 has 3 fans, port 2 has 1 fan

After that, RGB commands can use topology instead of repeating port/fan counts:

```bash
tt-rgb-plus set-rgb red --use-topology --all-controllers
tt-rgb-plus set-rgb-effect wave fast --color '#00aaff' --use-topology --all-controllers
```

## Automatic Control

`auto-control` is the recommended command for services. It supports two modes:

- `--mode temp` for temperature-based control
- `--mode load` for CPU/GPU load-based control

Temperature mode with multiple sensors:

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

Default color-by-speed mapping:

- low speed: green
- medium speed: yellow
- high speed: orange/red

For SWAFAN EX chains, color sync sends a 60-LED payload by default, enough for
up to 3 fans on one port. Color sync is refreshed regularly with
`--rgb-refresh` to prevent controllers from falling back to a previous effect.

Legacy commands are still available:

- `auto` for CPU/GPU load
- `auto-temp` for temperature

## Systemd Service

Show current service options:

```bash
tt-rgb-plus config --show
```

Change service options with one command. Example temperature mode with multiple
sensors:

```bash
sudo tt-rgb-plus config \
  --mode temp \
  --sensors Tctl nvidia nvme it87952 \
  --use-topology \
  --temp-curve 30:18,40:24,50:38,60:58,70:80,80:100 \
  --rgb-style color \
  --restart
```

Switch to CPU/GPU load mode:

```bash
sudo tt-rgb-plus config \
  --mode load \
  --load-source max \
  --use-topology \
  --load-curve 0:20,30:30,50:50,70:75,90:100 \
  --rgb-style spectrum \
  --restart
```

Manual editing is also possible:

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

## RGB Protocol Discovery

Some controllers expose more lighting modes than the currently named commands.
For careful testing on one port:

```bash
sudo systemctl stop tt-rgb-plus-auto.service
tt-rgb-plus set-rgb-raw --mode 0x19 --color red --repeat 20 --ports 1 -c 0
tt-rgb-plus scan-rgb-modes --start 0x00 --end 0x2f --color red --repeat 20 --delay 3 --ports 1 -c 0
sudo systemctl start tt-rgb-plus-auto.service
```

Note which raw modes produce useful effects and open an issue with the mode
number, controller PID, fan model, and visible behavior.

Known SWAFAN EX LEDFanBox raw findings:

- `0x24`: static color with per-LED payload, confirmed on `264a:232b/232c`

## Protocol Notes

The HID commands are based on public TT RGB Plus protocol notes by MoshiMoshi0:

- https://moshimoshi0.github.io/ttrgbplusapi/
- https://github.com/MoshiMoshi0/ttrgbplusapi

Related Linux projects:

- https://github.com/chestm007/linux_thermaltake_riing
- https://github.com/munablamu/linux_thermaltake_rgb_plus

This project is unofficial and is not affiliated with Thermaltake.
