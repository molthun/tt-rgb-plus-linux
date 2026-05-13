#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-0.1.0}"
ARCH="${ARCH:-all}"
PKG="tt-rgb-plus"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${ROOT}/build/${PKG}_${VERSION}_${ARCH}"
OUT_DIR="${ROOT}/dist"

rm -rf "${BUILD_DIR}"
mkdir -p \
  "${BUILD_DIR}/DEBIAN" \
  "${BUILD_DIR}/usr/bin" \
  "${BUILD_DIR}/etc/default" \
  "${BUILD_DIR}/etc/udev/rules.d" \
  "${BUILD_DIR}/lib/systemd/system" \
  "${BUILD_DIR}/usr/share/doc/${PKG}"

install -m 0755 "${ROOT}/tt_rgb_plus.py" "${BUILD_DIR}/usr/bin/tt-rgb-plus"
install -m 0644 "${ROOT}/99-thermaltake-tt-rgb-plus.rules" "${BUILD_DIR}/etc/udev/rules.d/99-thermaltake-tt-rgb-plus.rules"
install -m 0644 "${ROOT}/packaging/tt-rgb-plus-auto.service" "${BUILD_DIR}/lib/systemd/system/tt-rgb-plus-auto.service"
install -m 0644 "${ROOT}/packaging/tt-rgb-plus.default" "${BUILD_DIR}/etc/default/tt-rgb-plus"
install -m 0644 "${ROOT}/README.md" "${BUILD_DIR}/usr/share/doc/${PKG}/README.md"
install -m 0644 "${ROOT}/WORKLOG.md" "${BUILD_DIR}/usr/share/doc/${PKG}/WORKLOG.md"

cat > "${BUILD_DIR}/DEBIAN/control" <<EOF
Package: ${PKG}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Maintainer: bogdanets <bogdanets@localhost>
Depends: python3, python3-psutil, python3-hid, libhidapi-hidraw0, libhidapi-libusb0, usbutils
Recommends: lm-sensors
Description: Thermaltake TT RGB Plus fan and RGB control for Linux
 Control Thermaltake TT RGB Plus / SWAFAN EX LEDFanBox USB HID controllers
 from Linux. Includes manual fan control, RGB control, temperature-based
 automatic fan curves, monitoring, udev rules, and a systemd service.
EOF

cat > "${BUILD_DIR}/DEBIAN/postinst" <<'EOF'
#!/usr/bin/env bash
set -e

udevadm control --reload-rules >/dev/null 2>&1 || true
udevadm trigger >/dev/null 2>&1 || true
systemctl daemon-reload >/dev/null 2>&1 || true

cat <<MSG
tt-rgb-plus installed.

Useful commands:
  tt-rgb-plus list --all
  tt-rgb-plus sensors
  tt-rgb-plus monitor

Edit service options:
  sudo nano /etc/default/tt-rgb-plus

Enable auto control:
  sudo systemctl enable --now tt-rgb-plus-auto.service
MSG
EOF

cat > "${BUILD_DIR}/DEBIAN/prerm" <<'EOF'
#!/usr/bin/env bash
set -e

if [ "${1:-}" = "remove" ] || [ "${1:-}" = "deconfigure" ]; then
  systemctl stop tt-rgb-plus-auto.service >/dev/null 2>&1 || true
  systemctl disable tt-rgb-plus-auto.service >/dev/null 2>&1 || true
fi
EOF

cat > "${BUILD_DIR}/DEBIAN/postrm" <<'EOF'
#!/usr/bin/env bash
set -e

systemctl daemon-reload >/dev/null 2>&1 || true
udevadm control --reload-rules >/dev/null 2>&1 || true
EOF

chmod 0755 "${BUILD_DIR}/DEBIAN/postinst" "${BUILD_DIR}/DEBIAN/prerm" "${BUILD_DIR}/DEBIAN/postrm"

mkdir -p "${OUT_DIR}"
dpkg-deb --build --root-owner-group "${BUILD_DIR}" "${OUT_DIR}/${PKG}_${VERSION}_${ARCH}.deb"
echo "Built: ${OUT_DIR}/${PKG}_${VERSION}_${ARCH}.deb"
