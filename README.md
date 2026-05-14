# TT RGB Plus Fan Control for Ubuntu

This folder is a Linux replacement utility, not a converted Windows `.exe`.
The original `TT RGB PLUS_Setup_3.0.7_x64.exe` is a Windows NSIS installer with
Windows binaries and drivers. Ubuntu cannot run those drivers directly, so this
tool talks to supported Thermaltake USB HID fan controllers directly.

Tested hardware:

- Thermaltake SWAFAN EX14 RGB White kits with `264a:232b Thermaltake LEDFanBox`

This project is unofficial and is not affiliated with Thermaltake.

## Supported controllers

Known protocol support:

- Riing Controller, USB VID `264a`, PID range `1f41`-`1f51`
- Riing Plus Controller, USB VID `264a`, PID range `1fa5`-`1fb5`
- Riing Trio Controller, USB VID `264a`, PID range `2135`-`2145`
- SWAFAN EX / Hiyatek Controller, USB VID `264a`, PID range `2199`-`21a8`
- Riing Quad Controller, USB VID `264a`, PID range `2260`-`2270`
- SWAFAN EX LEDFanBox Controller, USB VID `264a`, PID range `232b`-`233a`

Supported operations:

- list connected controllers
- read firmware, fan speed and RPM
- set fan speed percentage
- set static RGB color or turn RGB off
- automatically adjust fan speed from CPU/GPU load
- automatically adjust fan speed from CPU/GPU/system temperature
- save profile on controller families where the command is known to be safe

## Install on Ubuntu

```bash
cd ubuntu-tt-rgb-plus
chmod +x install_ubuntu.sh tt_rgb_plus.py
./install_ubuntu.sh
```

Unplug and reconnect the controller after installing udev rules.

## Usage

List controllers:

```bash
python3 tt_rgb_plus.py list
python3 tt_rgb_plus.py list --all
```

Read fan data:

```bash
python3 tt_rgb_plus.py status
python3 tt_rgb_plus.py status --ports 1 2 3
```

Set speed to 60 percent:

```bash
python3 tt_rgb_plus.py set-speed 60 --ports 1 2 3
```

Set speed and save it to controller memory, where supported:

```bash
python3 tt_rgb_plus.py set-speed 60 --ports 1 2 3 --save
```

Set static RGB color:

```bash
python3 tt_rgb_plus.py set-rgb '#ffffff' --all-controllers --ports 1 2 3 4 5
python3 tt_rgb_plus.py set-rgb red --all-controllers --ports 1 2 3 4 5
python3 tt_rgb_plus.py rgb-off --all-controllers --ports 1 2 3 4 5
python3 tt_rgb_plus.py set-rgb-effect spectrum slow --all-controllers --ports 1 2 3 4 5
```

Automatic speed from CPU/GPU load:

```bash
python3 tt_rgb_plus.py auto --source max --all-controllers --ports 1 2 3 4 5
```

Custom fan curve:

```bash
python3 tt_rgb_plus.py auto --source max --all-controllers --ports 1 2 3 4 5 --curve 0:25,35:35,55:55,75:80,90:100
```

`--source max` uses the higher value between CPU load and GPU load. GPU load is
read through `nvidia-smi` when an NVIDIA driver is installed. If GPU load is not
available, the script falls back to CPU load.

For multiple SWAFAN EX kits/controllers, use `--all-controllers`. If you use one
controller with several fans chained on each port, setting the port controls the
whole chain on that port.

List temperature sensors:

```bash
python3 tt_rgb_plus.py sensors
```

Automatic speed from temperature:

```bash
python3 tt_rgb_plus.py auto-temp --source max --all-controllers --ports 1 2 3 4 5 --curve 30:25,40:35,55:55,70:80,80:100
```

Use a specific sensor by chip or label text:

```bash
python3 tt_rgb_plus.py auto-temp --sensor Tctl --all-controllers --ports 1 2 3 4 5
python3 tt_rgb_plus.py auto-temp --sensor nvidia --all-controllers --ports 1 2 3 4 5
```

Use the hottest of several important sensors, useful for AI servers:

```bash
python3 tt_rgb_plus.py auto-temp --sensors Tctl nvidia nvme --all-controllers --ports 1 2 3 4 5 --curve 30:18,40:24,50:38,60:58,70:80,80:100
```

Use the unified service-friendly command and choose control mode:

```bash
tt-rgb-plus auto-control --mode temp --sensors Tctl nvidia nvme it87952 --all-controllers --ports 1 2 3 4 5 --temp-curve 30:18,40:24,50:38,60:58,70:80,80:100 --rgb-sync --rgb-style spectrum
tt-rgb-plus auto-control --mode load --load-source max --all-controllers --ports 1 2 3 4 5 --load-curve 0:20,30:30,50:50,70:75,90:100 --rgb-sync --rgb-style spectrum
```

For packaged installs, switch between temperature and load control by editing:

```bash
sudo nano /etc/default/tt-rgb-plus
sudo systemctl restart tt-rgb-plus-auto.service
```

Sync circular RGB with fan speed:

```bash
python3 tt_rgb_plus.py auto-temp --sensors Tctl nvidia nvme --all-controllers --ports 1 2 3 4 5 --interval 2 --step 2 --curve 30:18,40:24,50:38,60:58,70:80,80:100 --rgb-sync --rgb-style spectrum
```

`--rgb-style color` uses blue/cyan at low speed, green/yellow in the middle,
and orange/red at high speed. `flow` and `spectrum` use built-in circular
effects and increase effect speed as fan speed rises.

Monitor service state and temperatures without taking over the controller:

```bash
python3 tt_rgb_plus.py monitor
python3 tt_rgb_plus.py monitor --watch --clear
```

## Build a Debian package

```bash
chmod +x build_deb.sh
./build_deb.sh 0.1.0
sudo apt install ./dist/tt-rgb-plus_0.1.0_all.deb
```

After installing the package:

```bash
tt-rgb-plus list --all
tt-rgb-plus sensors
tt-rgb-plus monitor
sudo nano /etc/default/tt-rgb-plus
sudo systemctl enable --now tt-rgb-plus-auto.service
```

Run it in the background with systemd:

```bash
sudo cp tt-rgb-plus-auto.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tt-rgb-plus-auto.service
systemctl status tt-rgb-plus-auto.service
```

## Troubleshooting

Check whether Ubuntu sees the controller:

```bash
lsusb | grep -i 264a
```

If the script only works with `sudo`, the udev rule has not been applied yet.
Reload rules, reconnect the controller, then log out and back in:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

If your controller has a different PID, send the output of:

```bash
lsusb
python3 tt_rgb_plus.py list
```

Then the PID range and command profile can be added.

## Protocol note

The HID commands are based on the public TT RGB Plus API notes by MoshiMoshi0:

- https://moshimoshi0.github.io/ttrgbplusapi/
- https://github.com/MoshiMoshi0/ttrgbplusapi
