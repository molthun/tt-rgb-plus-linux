#!/usr/bin/env python3
"""
Small Ubuntu/Linux CLI for Thermaltake TT RGB Plus USB HID fan controllers.

It is intentionally conservative: it supports listing controllers, reading fan
speed/RPM, setting fan speed by percent, and saving profiles where the protocol
is known to support it.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

try:
    import hid
except ImportError:
    print(
        "Missing Python package: hidapi\n"
        "Install with: python3 -m pip install --user hidapi",
        file=sys.stderr,
    )
    raise SystemExit(2)

try:
    import psutil
except ImportError:
    psutil = None


THERMALTAKE_VID = 0x264A
REPORT_LEN = 64
DEFAULT_STATE_FILE = "/run/tt-rgb-plus/state.json"
DEFAULT_CONFIG_FILE = "/etc/default/tt-rgb-plus"
SERVICE_NAME = "tt-rgb-plus-auto.service"
RGB_SPEEDS = {
    "extreme": 0x00,
    "fast": 0x01,
    "normal": 0x02,
    "slow": 0x03,
}
RGB_EFFECTS = {
    "flow": {"base": 0x00, "uses_speed": True, "colors": "none"},
    "spectrum": {"base": 0x04, "uses_speed": True, "colors": "none"},
    "ripple": {"base": 0x08, "uses_speed": True, "colors": "single"},
    "blink": {"base": 0x0C, "uses_speed": True, "colors": "leds"},
    "pulse": {"base": 0x10, "uses_speed": True, "colors": "leds"},
    "wave": {"base": 0x14, "uses_speed": True, "colors": "leds"},
    "per-led": {"base": 0x18, "uses_speed": False, "colors": "leds"},
}
LEDS_PER_SWAFAN_EX_FAN = 20


@dataclass(frozen=True)
class ControllerFamily:
    name: str
    pid_start: int
    pid_end: int
    speed_mode: int
    can_save: bool = True
    write_len: int = REPORT_LEN
    rgb_full_mode: int = 0x19
    color_order: str = "grb"

    def matches(self, pid: int) -> bool:
        return self.pid_start <= pid <= self.pid_end


FAMILIES = (
    ControllerFamily("Riing", 0x1F41, 0x1F51, speed_mode=0x03, rgb_full_mode=0x01, color_order="rgb"),
    ControllerFamily("Riing Plus", 0x1FA5, 0x1FB5, speed_mode=0x01),
    ControllerFamily("Riing Trio", 0x2135, 0x2145, speed_mode=0x01),
    ControllerFamily("SWAFAN EX / Hiyatek", 0x2199, 0x21A8, speed_mode=0x01, can_save=False),
    ControllerFamily("Riing Quad", 0x2260, 0x2270, speed_mode=0x01, can_save=False),
    ControllerFamily("SWAFAN EX LEDFanBox", 0x232B, 0x233A, speed_mode=0x01, can_save=False, write_len=193),
)


@dataclass
class ControllerInfo:
    path: bytes
    vendor_id: int
    product_id: int
    product_string: str | None
    serial_number: str | None
    family: ControllerFamily


class TTController:
    def __init__(self, info: ControllerInfo):
        self.info = info
        self.dev = hid.device()
        self.dev.open_path(info.path)
        self.dev.set_nonblocking(False)

    def close(self) -> None:
        self.dev.close()

    def __enter__(self) -> "TTController":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def write_cmd(self, payload: Iterable[int]) -> None:
        data = [0x00, *payload]
        write_len = self.info.family.write_len
        if len(data) > write_len:
            raise ValueError("HID command is too long")
        data.extend([0x00] * (write_len - len(data)))
        written = self.dev.write(data)
        if written <= 0:
            raise RuntimeError("HID write failed")

    def read_reply(self) -> list[int]:
        data = self.dev.read(REPORT_LEN, timeout_ms=1500)
        if not data:
            raise RuntimeError("No reply from controller")
        return list(data)

    def command(self, payload: Iterable[int]) -> list[int]:
        self.write_cmd(payload)
        return self.read_reply()

    def init(self) -> list[int]:
        return self.command([0xFE, 0x33])

    def firmware(self) -> tuple[int, int, int]:
        data = self.command([0x33, 0x50])
        return tuple((data + [0, 0, 0])[:3])  # type: ignore[return-value]

    def fan_data(self, port: int) -> tuple[int, int, int]:
        data = self.command([0x33, 0x51, port])
        padded = data + [0] * 5
        speed = padded[2]
        rpm = (padded[4] << 8) + padded[3]
        detected_port = padded[0]
        return detected_port, speed, rpm

    def set_speed(self, port: int, speed: int) -> list[int]:
        mode = self.info.family.speed_mode
        return self.command([0x32, 0x51, port, mode, speed])

    def set_rgb(self, port: int, red: int, green: int, blue: int) -> list[int]:
        colors = {"r": red, "g": green, "b": blue}
        payload_color = [colors[channel] for channel in self.info.family.color_order]
        return self.command([0x32, 0x52, port, self.info.family.rgb_full_mode, *payload_color])

    def color_payload(self, red: int, green: int, blue: int) -> list[int]:
        colors = {"r": red, "g": green, "b": blue}
        return [colors[channel] for channel in self.info.family.color_order]

    def set_rgb_effect(
        self,
        port: int,
        effect: str,
        speed: str,
        colors: list[tuple[int, int, int]] | None = None,
    ) -> list[int]:
        effect_info = RGB_EFFECTS[effect]
        mode = int(effect_info["base"])
        if effect_info["uses_speed"]:
            mode += RGB_SPEEDS[speed]

        payload = [0x32, 0x52, port, mode]
        for red, green, blue in colors or []:
            payload.extend(self.color_payload(red, green, blue))
        return self.command(payload)

    def save(self) -> list[int]:
        if not self.info.family.can_save:
            raise RuntimeError("Save command is not considered safe for this controller family")
        return self.command([0x32, 0x53])


def known_family(pid: int) -> ControllerFamily | None:
    for family in FAMILIES:
        if family.matches(pid):
            return family
    return None


def find_controllers(include_unknown: bool = False) -> list[ControllerInfo]:
    devices = []
    for dev in hid.enumerate(THERMALTAKE_VID):
        family = known_family(dev["product_id"])
        if family is None:
            if not include_unknown:
                continue
            family = ControllerFamily("Unknown Thermaltake HID", dev["product_id"], dev["product_id"], speed_mode=0x01)
        devices.append(
            ControllerInfo(
                path=dev["path"],
                vendor_id=dev["vendor_id"],
                product_id=dev["product_id"],
                product_string=dev.get("product_string"),
                serial_number=dev.get("serial_number"),
                family=family,
            )
        )
    return devices


def select_controller(index: int) -> ControllerInfo:
    controllers = find_controllers()
    if not controllers:
        raise SystemExit(
            "No supported Thermaltake TT RGB Plus HID controller found.\n"
            "Check USB connection, then run: lsusb | grep -i 264a"
        )
    if index < 0 or index >= len(controllers):
        raise SystemExit(f"Controller index {index} is out of range; found {len(controllers)}")
    return controllers[index]


def select_controllers(index: int, all_controllers: bool) -> list[ControllerInfo]:
    controllers = find_controllers()
    if not controllers:
        raise SystemExit(
            "No supported Thermaltake TT RGB Plus HID controller found.\n"
            "Check USB connection, then run: lsusb | grep -i 264a"
        )
    if all_controllers:
        return controllers
    return [select_controller(index)]


def print_reply(reply: list[int]) -> None:
    compact = " ".join(f"{byte:02x}" for byte in reply[:8])
    print(f"reply: {compact}")


def write_state(path: str, state: dict[str, object]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, path)
    except OSError as exc:
        print(f"warning: failed to write state file {path}: {exc}", file=sys.stderr)


def read_state(path: str) -> dict[str, object] | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        print(f"warning: failed to read state file {path}: {exc}", file=sys.stderr)
        return None
    return data if isinstance(data, dict) else None


def cmd_list(_args: argparse.Namespace) -> None:
    controllers = find_controllers(include_unknown=_args.all)
    if not controllers:
        print("No supported Thermaltake TT RGB Plus HID controller found.")
        return
    for idx, info in enumerate(controllers):
        print(
            f"[{idx}] {info.family.name} "
            f"VID:PID={info.vendor_id:04x}:{info.product_id:04x} "
            f"write_len={info.family.write_len} "
            f"name={info.product_string or '-'} serial={info.serial_number or '-'}"
        )


def cmd_status(args: argparse.Namespace) -> None:
    for controller_index, info in enumerate(select_controllers(args.controller, args.all_controllers)):
        with TTController(info) as ctrl:
            ctrl.init()
            firmware = ctrl.firmware()
            print(f"controller {controller_index}: {info.family.name} {info.vendor_id:04x}:{info.product_id:04x}")
            print(f"firmware: {firmware[0]}.{firmware[1]}.{firmware[2]}")
            for port in args.ports:
                detected_port, speed, rpm = ctrl.fan_data(port)
                print(f"port {port}: detected={detected_port} speed={speed}% rpm={rpm}")


def cmd_set(args: argparse.Namespace) -> None:
    if not 0 <= args.speed <= 100:
        raise SystemExit("Speed must be between 0 and 100")
    if 1 <= args.speed <= 19:
        print("Warning: this controller protocol usually ignores speeds from 1 to 19%.")
    for controller_index, info in enumerate(select_controllers(args.controller, args.all_controllers)):
        with TTController(info) as ctrl:
            ctrl.init()
            for port in args.ports:
                print(f"setting controller {controller_index} port {port} to {args.speed}%")
                print_reply(ctrl.set_speed(port, args.speed))
            if args.save:
                print(f"saving profile on controller {controller_index}")
                print_reply(ctrl.save())


def parse_color(value: str) -> tuple[int, int, int]:
    text = value.strip()
    named = {
        "off": "000000",
        "black": "000000",
        "white": "ffffff",
        "red": "ff0000",
        "green": "00ff00",
        "blue": "0000ff",
        "cyan": "00ffff",
        "magenta": "ff00ff",
        "yellow": "ffff00",
    }
    text = named.get(text.lower(), text)
    if text.startswith("#"):
        text = text[1:]
    if len(text) != 6:
        raise ValueError("Color must be #RRGGBB, RRGGBB, or a known name")
    try:
        red = int(text[0:2], 16)
        green = int(text[2:4], 16)
        blue = int(text[4:6], 16)
    except ValueError as exc:
        raise ValueError("Color must contain hexadecimal digits") from exc
    return red, green, blue


def parse_color_list(value: str) -> list[tuple[int, int, int]]:
    return [parse_color(item.strip()) for item in value.split(",") if item.strip()]


def parse_port_fans(value: str) -> dict[int, int]:
    mapping = {}
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        port_raw, fans_raw = item.split(":", 1)
        port = int(port_raw)
        fans = int(fans_raw)
        if port < 1:
            raise ValueError("Port number must be 1 or greater")
        if fans < 1:
            raise ValueError("Fan count must be 1 or greater")
        mapping[port] = fans
    return mapping


def cmd_set_rgb(args: argparse.Namespace) -> None:
    try:
        red, green, blue = parse_color(args.color)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    for controller_index, info in enumerate(select_controllers(args.controller, args.all_controllers)):
        with TTController(info) as ctrl:
            ctrl.init()
            for port in args.ports:
                print(
                    f"setting controller {controller_index} port {port} "
                    f"rgb=#{red:02x}{green:02x}{blue:02x}"
                )
                print_reply(ctrl.set_rgb(port, red, green, blue))
            if args.save:
                print(f"saving profile on controller {controller_index}")
                print_reply(ctrl.save())


def led_count_for_port(args: argparse.Namespace, port: int) -> int:
    if args.port_fans:
        try:
            mapping = parse_port_fans(args.port_fans)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        return mapping.get(port, args.led_count) * LEDS_PER_SWAFAN_EX_FAN
    return args.led_count


def effect_colors(args: argparse.Namespace, port: int) -> list[tuple[int, int, int]]:
    color_mode = RGB_EFFECTS[args.effect]["colors"]
    if color_mode == "none":
        return []
    led_count = led_count_for_port(args, port)
    if args.colors:
        colors = parse_color_list(args.colors)
        if color_mode == "single":
            return colors[:1]
        if len(colors) == 1:
            return colors * led_count
        if len(colors) != led_count:
            raise SystemExit(f"--colors must contain either 1 color or exactly {led_count} colors for port {port}")
        return colors
    color = parse_color(args.color)
    if color_mode == "single":
        return [color]
    return [color] * led_count


def cmd_set_rgb_effect(args: argparse.Namespace) -> None:
    for controller_index, info in enumerate(select_controllers(args.controller, args.all_controllers)):
        with TTController(info) as ctrl:
            ctrl.init()
            for port in args.ports:
                colors = effect_colors(args, port)
                led_count = len(colors) if RGB_EFFECTS[args.effect]["colors"] == "leds" else "-"
                print(
                    f"setting controller {controller_index} port {port} "
                    f"rgb_effect={args.effect} speed={args.speed} led_count={led_count}"
                )
                print_reply(ctrl.set_rgb_effect(port, args.effect, args.speed, colors))
            if args.save:
                print(f"saving profile on controller {controller_index}")
                print_reply(ctrl.save())


def interpolate_color(left: tuple[int, int, int], right: tuple[int, int, int], pos: float) -> tuple[int, int, int]:
    return tuple(round(left[idx] + (right[idx] - left[idx]) * pos) for idx in range(3))  # type: ignore[return-value]


def color_from_speed(speed: int) -> tuple[int, int, int]:
    points = [
        (0, (0, 90, 255)),
        (25, (0, 220, 255)),
        (45, (0, 255, 120)),
        (65, (255, 220, 0)),
        (80, (255, 90, 0)),
        (100, (255, 0, 0)),
    ]
    if speed <= points[0][0]:
        return points[0][1]
    for idx in range(1, len(points)):
        left_speed, left_color = points[idx - 1]
        right_speed, right_color = points[idx]
        if speed <= right_speed:
            pos = (speed - left_speed) / (right_speed - left_speed)
            return interpolate_color(left_color, right_color, pos)
    return points[-1][1]


def rgb_effect_speed_from_fan_speed(speed: int) -> str:
    if speed < 30:
        return "slow"
    if speed < 55:
        return "normal"
    if speed < 75:
        return "fast"
    return "extreme"


def apply_synced_rgb(ctrl: TTController, ports: list[int], fan_speed: int, style: str) -> None:
    if style == "color":
        red, green, blue = color_from_speed(fan_speed)
        for port in ports:
            ctrl.set_rgb(port, red, green, blue)
        return

    effect_speed = rgb_effect_speed_from_fan_speed(fan_speed)
    for port in ports:
        ctrl.set_rgb_effect(port, style, effect_speed)


def parse_curve(points: str) -> list[tuple[int, int]]:
    curve = []
    for raw_point in points.split(","):
        load_raw, speed_raw = raw_point.split(":", 1)
        load = int(load_raw)
        speed = int(speed_raw)
        if not 0 <= load <= 100 or not 0 <= speed <= 100:
            raise ValueError("Curve load and speed values must be between 0 and 100")
        curve.append((load, speed))
    curve.sort()
    if not curve:
        raise ValueError("Curve cannot be empty")
    return curve


def speed_from_curve(load: float, curve: list[tuple[int, int]]) -> int:
    if load <= curve[0][0]:
        return curve[0][1]
    for idx in range(1, len(curve)):
        left_load, left_speed = curve[idx - 1]
        right_load, right_speed = curve[idx]
        if load <= right_load:
            span = right_load - left_load
            if span <= 0:
                return right_speed
            pos = (load - left_load) / span
            return round(left_speed + pos * (right_speed - left_speed))
    return curve[-1][1]


def cpu_load_percent() -> float:
    if psutil is None:
        raise RuntimeError("Missing Python package: psutil. Install with: python3 -m pip install --user psutil")
    return float(psutil.cpu_percent(interval=None))


def nvidia_gpu_load_percent() -> float | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (subprocess.SubprocessError, OSError):
        return None

    values = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            values.append(float(line))
        except ValueError:
            continue
    return max(values) if values else None


def nvidia_gpu_temp_celsius() -> float | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (subprocess.SubprocessError, OSError):
        return None

    values = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            values.append(float(line))
        except ValueError:
            continue
    return max(values) if values else None


def system_temperatures() -> list[tuple[str, str, float]]:
    if psutil is None:
        raise RuntimeError("Missing Python package: psutil. Install with: python3 -m pip install --user psutil")
    readings = []
    for chip, entries in psutil.sensors_temperatures(fahrenheit=False).items():
        for entry in entries:
            if entry.current is None:
                continue
            temp = float(entry.current)
            if -20 <= temp <= 125:
                readings.append((chip, entry.label or "-", temp))
    gpu_temp = nvidia_gpu_temp_celsius()
    if gpu_temp is not None:
        readings.append(("nvidia", "gpu", gpu_temp))
    return readings


def select_temperature(
    source: str,
    sensor: str | None = None,
    sensors: list[str] | None = None,
) -> tuple[float, str]:
    readings = system_temperatures()
    if not readings:
        raise RuntimeError("No temperature sensors found")

    if sensors:
        needles = [item.lower() for item in sensors]
        matches = [
            reading for reading in readings
            if any(needle in f"{reading[0]} {reading[1]}".lower() for needle in needles)
        ]
        if not matches:
            available = ", ".join(f"{chip}/{label}" for chip, label, _temp in readings)
            raise RuntimeError(f"Sensors '{', '.join(sensors)}' not found. Available: {available}")
        chip, label, temp = max(matches, key=lambda reading: reading[2])
        return temp, f"{chip}/{label}"

    if sensor:
        needle = sensor.lower()
        matches = [
            reading for reading in readings
            if needle in f"{reading[0]} {reading[1]}".lower()
        ]
        if not matches:
            available = ", ".join(f"{chip}/{label}" for chip, label, _temp in readings)
            raise RuntimeError(f"Sensor '{sensor}' not found. Available: {available}")
        chip, label, temp = max(matches, key=lambda reading: reading[2])
        return temp, f"{chip}/{label}"

    if source == "gpu":
        matches = [reading for reading in readings if "gpu" in f"{reading[0]} {reading[1]}".lower() or reading[0] == "nvidia"]
        if not matches:
            raise RuntimeError("No GPU temperature sensor found")
    elif source == "cpu":
        matches = [
            reading for reading in readings
            if any(term in f"{reading[0]} {reading[1]}".lower() for term in ("cpu", "core", "k10temp", "zenpower", "coretemp", "tctl", "tdie", "package"))
        ]
        if not matches:
            raise RuntimeError("No CPU temperature sensor found")
    else:
        matches = readings

    chip, label, temp = max(matches, key=lambda reading: reading[2])
    return temp, f"{chip}/{label}"


def cmd_sensors(_args: argparse.Namespace) -> None:
    readings = system_temperatures()
    if not readings:
        print("No temperature sensors found.")
        return
    for chip, label, temp in sorted(readings):
        print(f"{chip}/{label}: {temp:.1f} C")


def cmd_monitor(args: argparse.Namespace) -> None:
    while True:
        if args.clear:
            print("\033[2J\033[H", end="")

        print(f"TT RGB Plus monitor - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()

        controllers = find_controllers(include_unknown=True)
        if controllers:
            print("Controllers:")
            for idx, info in enumerate(controllers):
                print(
                    f"  [{idx}] {info.family.name} "
                    f"{info.vendor_id:04x}:{info.product_id:04x} "
                    f"name={info.product_string or '-'}"
                )
        else:
            print("Controllers: none found")

        print()
        state = read_state(args.state_file)
        if state:
            print("Last auto state:")
            print(f"  mode: {state.get('mode', '-')}")
            print(f"  time: {state.get('time', '-')}")
            print(f"  sensor: {state.get('sensor', '-')}")
            print(f"  temperature: {state.get('temperature_c', '-')} C")
            print(f"  target fan speed: {state.get('target_speed_percent', '-')}%")
            print(f"  ports: {state.get('ports', '-')}")
            print(f"  rgb: {state.get('rgb', '-')}")
        else:
            print(f"Last auto state: no state file at {args.state_file}")

        print()
        print("Temperatures:")
        try:
            readings = system_temperatures()
        except RuntimeError as exc:
            print(f"  error: {exc}")
            readings = []
        for chip, label, temp in sorted(readings):
            print(f"  {chip}/{label}: {temp:.1f} C")

        if not args.watch:
            return
        time.sleep(args.interval)


def build_auto_control_args(args: argparse.Namespace) -> list[str]:
    command = [
        "auto-control",
        "--mode",
        args.mode,
        "--all-controllers",
        "--ports",
        *[str(port) for port in args.ports],
        "--interval",
        str(args.interval),
        "--step",
        str(args.step),
    ]
    if args.refresh is not None:
        command.extend(["--refresh", str(args.refresh)])
    if args.min_speed is not None:
        command.extend(["--min-speed", str(args.min_speed)])
    if args.max_speed is not None:
        command.extend(["--max-speed", str(args.max_speed)])

    if args.mode == "temp":
        if args.sensors:
            command.extend(["--sensors", *args.sensors])
        elif args.sensor:
            command.extend(["--sensor", args.sensor])
        else:
            command.extend(["--temp-source", args.temp_source])
        command.extend(["--temp-curve", args.temp_curve])
    else:
        command.extend(["--load-source", args.load_source])
        command.extend(["--load-curve", args.load_curve])

    if args.rgb_sync:
        command.extend(["--rgb-sync", "--rgb-style", args.rgb_style])
        command.extend(["--rgb-step", str(args.rgb_step)])
    return command


def default_config_text(command: list[str]) -> str:
    return (
        "# Options used by tt-rgb-plus-auto.service.\n"
        "# Generated by: tt-rgb-plus config\n\n"
        f'TT_RGB_PLUS_ARGS="{shlex.join(command)}"\n'
    )


def cmd_config(args: argparse.Namespace) -> None:
    if args.show:
        try:
            with open(args.path, "r", encoding="utf-8") as handle:
                print(handle.read(), end="")
        except FileNotFoundError:
            raise SystemExit(f"Config file not found: {args.path}")
        return

    command = build_auto_control_args(args)
    text = default_config_text(command)
    print(text, end="")

    if args.dry_run:
        return

    try:
        with open(args.path, "w", encoding="utf-8") as handle:
            handle.write(text)
    except PermissionError as exc:
        raise SystemExit(f"Permission denied writing {args.path}. Run with sudo.") from exc

    print(f"written: {args.path}")
    if args.restart:
        subprocess.run(["systemctl", "daemon-reload"], check=False)
        subprocess.run(["systemctl", "restart", SERVICE_NAME], check=True)
        print(f"restarted: {SERVICE_NAME}")


def cmd_auto(args: argparse.Namespace) -> None:
    curve = parse_curve(args.curve)
    infos = select_controllers(args.controller, args.all_controllers)
    last_speed: int | None = None
    last_rgb_speed: int | None = None
    last_write = 0.0

    print(f"auto mode: controllers={len(infos)} ports={','.join(map(str, args.ports))}")
    print(f"source: {args.source}")
    print(f"curve: {', '.join(f'{load}%->{speed}%' for load, speed in curve)}")
    if args.rgb_sync:
        print(f"rgb sync: {args.rgb_style}")
    print("press Ctrl+C to stop")

    with_counters = [TTController(info) for info in infos]
    try:
        for ctrl in with_counters:
            ctrl.init()
        if psutil is not None:
            psutil.cpu_percent(interval=None)

        while True:
            cpu = cpu_load_percent()
            gpu = nvidia_gpu_load_percent()
            loads = [cpu]
            if gpu is not None and args.source in ("gpu", "max"):
                loads.append(gpu)
            if args.source == "cpu":
                active_load = cpu
            elif args.source == "gpu":
                active_load = gpu if gpu is not None else cpu
            else:
                active_load = max(loads)

            target_speed = speed_from_curve(active_load, curve)
            if args.min_speed is not None:
                target_speed = max(target_speed, args.min_speed)
            if args.max_speed is not None:
                target_speed = min(target_speed, args.max_speed)
            target_speed = max(0, min(100, target_speed))

            now = time.monotonic()
            should_write = (
                last_speed is None
                or abs(target_speed - last_speed) >= args.step
                or now - last_write >= args.refresh
            )

            if should_write:
                for ctrl in with_counters:
                    for port in args.ports:
                        ctrl.set_speed(port, target_speed)
                last_speed = target_speed
                last_write = now
                gpu_text = "n/a" if gpu is None else f"{gpu:.0f}%"
                print(f"cpu={cpu:.0f}% gpu={gpu_text} load={active_load:.0f}% speed={target_speed}%")

            should_write_rgb = (
                args.rgb_sync
                and (
                    last_rgb_speed is None
                    or abs(target_speed - last_rgb_speed) >= args.rgb_step
                    or should_write
                )
            )
            if should_write_rgb:
                for ctrl in with_counters:
                    apply_synced_rgb(ctrl, args.ports, target_speed, args.rgb_style)
                last_rgb_speed = target_speed

            write_state(
                args.state_file,
                {
                    "mode": "auto-load",
                    "time": datetime.now().isoformat(timespec="seconds"),
                    "source": args.source,
                    "cpu_load_percent": round(cpu, 1),
                    "gpu_load_percent": None if gpu is None else round(gpu, 1),
                    "active_load_percent": round(active_load, 1),
                    "target_speed_percent": target_speed,
                    "ports": args.ports,
                    "controllers": len(infos),
                    "rgb": args.rgb_style if args.rgb_sync else "off",
                    "curve": args.curve,
                },
            )

            time.sleep(args.interval)
    finally:
        for ctrl in with_counters:
            ctrl.close()


def cmd_auto_temp(args: argparse.Namespace) -> None:
    curve = parse_curve(args.curve)
    infos = select_controllers(args.controller, args.all_controllers)
    last_speed: int | None = None
    last_rgb_speed: int | None = None
    last_write = 0.0

    print(f"auto-temp mode: controllers={len(infos)} ports={','.join(map(str, args.ports))}")
    if args.sensors:
        print(f"sensors contain any of: {', '.join(args.sensors)}")
    else:
        print(f"source: {args.source}" + (f" sensor contains: {args.sensor}" if args.sensor else ""))
    print(f"curve: {', '.join(f'{temp}C->{speed}%' for temp, speed in curve)}")
    if args.rgb_sync:
        print(f"rgb sync: {args.rgb_style}")
    print("press Ctrl+C to stop")

    controllers = [TTController(info) for info in infos]
    try:
        for ctrl in controllers:
            ctrl.init()

        while True:
            temp, sensor_name = select_temperature(args.source, args.sensor, args.sensors)
            target_speed = speed_from_curve(temp, curve)
            if args.min_speed is not None:
                target_speed = max(target_speed, args.min_speed)
            if args.max_speed is not None:
                target_speed = min(target_speed, args.max_speed)
            target_speed = max(0, min(100, target_speed))

            now = time.monotonic()
            should_write = (
                last_speed is None
                or abs(target_speed - last_speed) >= args.step
                or now - last_write >= args.refresh
            )

            if should_write:
                for ctrl in controllers:
                    for port in args.ports:
                        ctrl.set_speed(port, target_speed)
                last_speed = target_speed
                last_write = now
                print(f"sensor={sensor_name} temp={temp:.1f}C speed={target_speed}%")

            should_write_rgb = (
                args.rgb_sync
                and (
                    last_rgb_speed is None
                    or abs(target_speed - last_rgb_speed) >= args.rgb_step
                    or should_write
                )
            )
            if should_write_rgb:
                for ctrl in controllers:
                    apply_synced_rgb(ctrl, args.ports, target_speed, args.rgb_style)
                last_rgb_speed = target_speed

            write_state(
                args.state_file,
                {
                    "mode": "auto-temp",
                    "time": datetime.now().isoformat(timespec="seconds"),
                    "sensor": sensor_name,
                    "temperature_c": round(temp, 1),
                    "target_speed_percent": target_speed,
                    "ports": args.ports,
                    "controllers": len(infos),
                    "rgb": args.rgb_style if args.rgb_sync else "off",
                    "curve": args.curve,
                },
            )

            time.sleep(args.interval)
    finally:
        for ctrl in controllers:
            ctrl.close()


def cmd_auto_control(args: argparse.Namespace) -> None:
    common = {
        "controller": args.controller,
        "all_controllers": args.all_controllers,
        "ports": args.ports,
        "interval": args.interval,
        "refresh": args.refresh,
        "step": args.step,
        "min_speed": args.min_speed,
        "max_speed": args.max_speed,
        "rgb_sync": args.rgb_sync,
        "rgb_style": args.rgb_style,
        "rgb_step": args.rgb_step,
        "state_file": args.state_file,
    }
    if args.mode == "temp":
        cmd_auto_temp(
            argparse.Namespace(
                **common,
                source=args.temp_source,
                sensor=args.sensor,
                sensors=args.sensors,
                curve=args.temp_curve,
            )
        )
    else:
        cmd_auto(
            argparse.Namespace(
                **common,
                source=args.load_source,
                curve=args.load_curve,
            )
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Thermaltake TT RGB Plus fan control for Ubuntu/Linux")
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="List supported USB HID controllers")
    list_parser.add_argument("--all", action="store_true", help="Also show unknown Thermaltake HID devices")
    list_parser.set_defaults(func=cmd_list)

    sensors_parser = sub.add_parser("sensors", help="List available temperature sensors")
    sensors_parser.set_defaults(func=cmd_sensors)

    monitor_parser = sub.add_parser("monitor", help="Show controller, temperature, and auto-control state")
    monitor_parser.add_argument("--state-file", default=DEFAULT_STATE_FILE, help="State file written by auto-temp")
    monitor_parser.add_argument("--watch", action="store_true", help="Keep refreshing")
    monitor_parser.add_argument("--interval", type=float, default=2.0, help="Refresh interval for --watch")
    monitor_parser.add_argument("--clear", action="store_true", help="Clear screen between refreshes")
    monitor_parser.set_defaults(func=cmd_monitor)

    config_parser = sub.add_parser("config", help="Write /etc/default service config")
    config_parser.add_argument("--show", action="store_true", help="Print current config and exit")
    config_parser.add_argument("--path", default=DEFAULT_CONFIG_FILE, help="Config file path")
    config_parser.add_argument("--dry-run", action="store_true", help="Print generated config without writing it")
    config_parser.add_argument("--restart", action="store_true", help="Restart tt-rgb-plus-auto.service after writing")
    config_parser.add_argument(
        "--mode",
        choices=["temp", "load"],
        default="temp",
        help="Control by temperature or by CPU/GPU load",
    )
    config_parser.add_argument("-p", "--ports", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    config_parser.add_argument(
        "--temp-source",
        choices=["cpu", "gpu", "max"],
        default="max",
        help="Temperature mode: use CPU, GPU, or hottest available sensor",
    )
    config_parser.add_argument("--sensor", default=None, help="Temperature mode: use one matching sensor")
    config_parser.add_argument(
        "--sensors",
        nargs="+",
        default=None,
        help="Temperature mode: use hottest sensor matching any listed text",
    )
    config_parser.add_argument(
        "--temp-curve",
        default="30:18,40:24,50:38,60:58,70:80,80:100",
        help="Temperature-to-speed curve",
    )
    config_parser.add_argument(
        "--load-source",
        choices=["cpu", "gpu", "max"],
        default="max",
        help="Load mode: use CPU load, GPU load, or the higher value",
    )
    config_parser.add_argument(
        "--load-curve",
        default="0:20,30:30,50:50,70:75,90:100",
        help="Load-to-speed curve",
    )
    config_parser.add_argument("--interval", type=float, default=2.0, help="Seconds between checks")
    config_parser.add_argument("--refresh", type=float, default=15.0, help="Force write every N seconds")
    config_parser.add_argument("--step", type=int, default=2, help="Only write when speed changes by at least N percent")
    config_parser.add_argument("--min-speed", type=int, default=None, help="Clamp minimum speed")
    config_parser.add_argument("--max-speed", type=int, default=None, help="Clamp maximum speed")
    config_parser.add_argument("--rgb-sync", dest="rgb_sync", action="store_true", default=True, help="Sync RGB with fan speed")
    config_parser.add_argument("--no-rgb-sync", dest="rgb_sync", action="store_false", help="Disable RGB sync")
    config_parser.add_argument(
        "--rgb-style",
        choices=["color", "flow", "spectrum"],
        default="spectrum",
        help="RGB sync style",
    )
    config_parser.add_argument("--rgb-step", type=int, default=5, help="Only update RGB when speed changes by N percent")
    config_parser.set_defaults(func=cmd_config)

    status_parser = sub.add_parser("status", help="Read speed/RPM from ports")
    status_parser.add_argument("-c", "--controller", type=int, default=0, help="Controller index from list")
    status_parser.add_argument("--all-controllers", action="store_true", help="Apply to every supported controller")
    status_parser.add_argument("-p", "--ports", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    status_parser.set_defaults(func=cmd_status)

    set_parser = sub.add_parser("set-speed", help="Set fan speed in percent")
    set_parser.add_argument("speed", type=int, help="Speed percent, 0-100")
    set_parser.add_argument("-c", "--controller", type=int, default=0, help="Controller index from list")
    set_parser.add_argument("--all-controllers", action="store_true", help="Apply to every supported controller")
    set_parser.add_argument("-p", "--ports", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    set_parser.add_argument("--save", action="store_true", help="Save to controller profile when supported")
    set_parser.set_defaults(func=cmd_set)

    rgb_parser = sub.add_parser("set-rgb", help="Set static RGB color")
    rgb_parser.add_argument("color", help="Color as #RRGGBB, RRGGBB, or name: red, green, blue, white, off")
    rgb_parser.add_argument("-c", "--controller", type=int, default=0, help="Controller index from list")
    rgb_parser.add_argument("--all-controllers", action="store_true", help="Apply to every supported controller")
    rgb_parser.add_argument("-p", "--ports", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    rgb_parser.add_argument("--save", action="store_true", help="Save to controller profile when supported")
    rgb_parser.set_defaults(func=cmd_set_rgb)

    off_parser = sub.add_parser("rgb-off", help="Turn RGB off")
    off_parser.add_argument("-c", "--controller", type=int, default=0, help="Controller index from list")
    off_parser.add_argument("--all-controllers", action="store_true", help="Apply to every supported controller")
    off_parser.add_argument("-p", "--ports", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    off_parser.add_argument("--save", action="store_true", help="Save to controller profile when supported")
    off_parser.set_defaults(func=lambda args: cmd_set_rgb(argparse.Namespace(**vars(args), color="off")))

    effect_parser = sub.add_parser("set-rgb-effect", help="Set built-in RGB effect")
    effect_parser.add_argument("effect", choices=sorted(RGB_EFFECTS), help="RGB effect")
    effect_parser.add_argument("speed", choices=sorted(RGB_SPEEDS), help="Effect speed")
    effect_parser.add_argument("--color", default="white", help="Color for effects that need colors")
    effect_parser.add_argument(
        "--colors",
        default=None,
        help="Comma-separated colors for per-LED effects, for example '#ff0000,#00ff00,#0000ff'",
    )
    effect_parser.add_argument("--led-count", type=int, default=20, help="LED count for per-LED effects")
    effect_parser.add_argument(
        "--port-fans",
        default=None,
        help="Fan count by port for SWAFAN EX chains, for example: 1:3,2:3,3:3,4:1",
    )
    effect_parser.add_argument("-c", "--controller", type=int, default=0, help="Controller index from list")
    effect_parser.add_argument("--all-controllers", action="store_true", help="Apply to every supported controller")
    effect_parser.add_argument("-p", "--ports", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    effect_parser.add_argument("--save", action="store_true", help="Save to controller profile when supported")
    effect_parser.set_defaults(func=cmd_set_rgb_effect)

    auto_parser = sub.add_parser("auto", help="Automatically adjust speed from CPU/GPU load")
    auto_parser.add_argument("-c", "--controller", type=int, default=0, help="Controller index from list")
    auto_parser.add_argument("--all-controllers", action="store_true", help="Apply to every supported controller")
    auto_parser.add_argument("-p", "--ports", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    auto_parser.add_argument(
        "--source",
        choices=["cpu", "gpu", "max"],
        default="max",
        help="Use CPU load, GPU load, or the higher value",
    )
    auto_parser.add_argument(
        "--curve",
        default="0:25,30:35,50:55,70:75,90:100",
        help="Load-to-speed curve, for example: 0:25,40:45,70:75,90:100",
    )
    auto_parser.add_argument("--interval", type=float, default=2.0, help="Seconds between load checks")
    auto_parser.add_argument("--refresh", type=float, default=15.0, help="Force write every N seconds")
    auto_parser.add_argument("--step", type=int, default=3, help="Only write when speed changes by at least N percent")
    auto_parser.add_argument("--min-speed", type=int, default=None, help="Clamp minimum speed")
    auto_parser.add_argument("--max-speed", type=int, default=None, help="Clamp maximum speed")
    auto_parser.add_argument("--rgb-sync", action="store_true", help="Also sync RGB with current fan speed")
    auto_parser.add_argument(
        "--rgb-style",
        choices=["color", "flow", "spectrum"],
        default="color",
        help="RGB sync style: color changes color, flow/spectrum use circular built-in effects",
    )
    auto_parser.add_argument("--rgb-step", type=int, default=5, help="Only update RGB when speed changes by N percent")
    auto_parser.add_argument("--state-file", default=DEFAULT_STATE_FILE, help="Write current auto-control state here")
    auto_parser.set_defaults(func=cmd_auto)

    auto_temp_parser = sub.add_parser("auto-temp", help="Automatically adjust speed from CPU/GPU temperature")
    auto_temp_parser.add_argument("-c", "--controller", type=int, default=0, help="Controller index from list")
    auto_temp_parser.add_argument("--all-controllers", action="store_true", help="Apply to every supported controller")
    auto_temp_parser.add_argument("-p", "--ports", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    auto_temp_parser.add_argument(
        "--source",
        choices=["cpu", "gpu", "max"],
        default="max",
        help="Use CPU temperature, GPU temperature, or the hottest available sensor",
    )
    auto_temp_parser.add_argument(
        "--sensor",
        default=None,
        help="Use sensors whose chip/label contains this text, for example: k10temp, Tctl, Package, nvidia",
    )
    auto_temp_parser.add_argument(
        "--sensors",
        nargs="+",
        default=None,
        help="Use the hottest sensor matching any listed text, for example: Tctl nvidia nvme",
    )
    auto_temp_parser.add_argument(
        "--curve",
        default="30:25,40:35,55:55,70:80,80:100",
        help="Temperature-to-speed curve, for example: 30:25,45:40,60:65,75:100",
    )
    auto_temp_parser.add_argument("--interval", type=float, default=2.0, help="Seconds between temperature checks")
    auto_temp_parser.add_argument("--refresh", type=float, default=15.0, help="Force write every N seconds")
    auto_temp_parser.add_argument("--step", type=int, default=3, help="Only write when speed changes by at least N percent")
    auto_temp_parser.add_argument("--min-speed", type=int, default=None, help="Clamp minimum speed")
    auto_temp_parser.add_argument("--max-speed", type=int, default=None, help="Clamp maximum speed")
    auto_temp_parser.add_argument(
        "--rgb-sync",
        action="store_true",
        help="Also sync RGB with current fan speed",
    )
    auto_temp_parser.add_argument(
        "--rgb-style",
        choices=["color", "flow", "spectrum"],
        default="color",
        help="RGB sync style: color changes color, flow/spectrum use circular built-in effects",
    )
    auto_temp_parser.add_argument("--rgb-step", type=int, default=5, help="Only update RGB when speed changes by N percent")
    auto_temp_parser.add_argument("--state-file", default=DEFAULT_STATE_FILE, help="Write current auto-control state here")
    auto_temp_parser.set_defaults(func=cmd_auto_temp)

    auto_control_parser = sub.add_parser(
        "auto-control",
        help="Automatically adjust speed by selected mode: temperature or CPU/GPU load",
    )
    auto_control_parser.add_argument(
        "--mode",
        choices=["temp", "load"],
        default="temp",
        help="Control by temperature or by CPU/GPU load",
    )
    auto_control_parser.add_argument("-c", "--controller", type=int, default=0, help="Controller index from list")
    auto_control_parser.add_argument("--all-controllers", action="store_true", help="Apply to every supported controller")
    auto_control_parser.add_argument("-p", "--ports", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    auto_control_parser.add_argument(
        "--temp-source",
        choices=["cpu", "gpu", "max"],
        default="max",
        help="Temperature mode: use CPU, GPU, or hottest available sensor",
    )
    auto_control_parser.add_argument(
        "--sensor",
        default=None,
        help="Temperature mode: use sensors whose chip/label contains this text",
    )
    auto_control_parser.add_argument(
        "--sensors",
        nargs="+",
        default=None,
        help="Temperature mode: use hottest sensor matching any listed text, for example: Tctl nvidia nvme",
    )
    auto_control_parser.add_argument(
        "--temp-curve",
        default="30:18,40:24,50:38,60:58,70:80,80:100",
        help="Temperature-to-speed curve",
    )
    auto_control_parser.add_argument(
        "--load-source",
        choices=["cpu", "gpu", "max"],
        default="max",
        help="Load mode: use CPU load, GPU load, or the higher value",
    )
    auto_control_parser.add_argument(
        "--load-curve",
        default="0:20,30:30,50:50,70:75,90:100",
        help="Load-to-speed curve",
    )
    auto_control_parser.add_argument("--interval", type=float, default=2.0, help="Seconds between checks")
    auto_control_parser.add_argument("--refresh", type=float, default=15.0, help="Force write every N seconds")
    auto_control_parser.add_argument("--step", type=int, default=3, help="Only write when speed changes by at least N percent")
    auto_control_parser.add_argument("--min-speed", type=int, default=None, help="Clamp minimum speed")
    auto_control_parser.add_argument("--max-speed", type=int, default=None, help="Clamp maximum speed")
    auto_control_parser.add_argument("--rgb-sync", action="store_true", help="Also sync RGB with current fan speed")
    auto_control_parser.add_argument(
        "--rgb-style",
        choices=["color", "flow", "spectrum"],
        default="color",
        help="RGB sync style: color changes color, flow/spectrum use circular built-in effects",
    )
    auto_control_parser.add_argument("--rgb-step", type=int, default=5, help="Only update RGB when speed changes by N percent")
    auto_control_parser.add_argument("--state-file", default=DEFAULT_STATE_FILE, help="Write current auto-control state here")
    auto_control_parser.set_defaults(func=cmd_auto_control)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
