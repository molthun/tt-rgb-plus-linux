#!/usr/bin/env bash
set -euo pipefail

sudo apt update
sudo apt install -y python3 python3-pip python3-venv libhidapi-hidraw0 libhidapi-libusb0
python3 -m pip install --user --upgrade hidapi psutil

sudo cp 99-thermaltake-tt-rgb-plus.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger

sudo mkdir -p /opt/tt-rgb-plus
sudo cp tt_rgb_plus.py /opt/tt-rgb-plus/
sudo cp tt-rgb-plus-auto.service /etc/systemd/system/
sudo systemctl daemon-reload

echo "Installed. Unplug/replug the controller, then run:"
echo "  python3 tt_rgb_plus.py list"
echo ""
echo "Optional background auto mode:"
echo "  sudo systemctl enable --now tt-rgb-plus-auto.service"
