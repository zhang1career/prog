"""Front door for the three hw-lab programmers.

Board scripts keep chip policy (fuses, partition erase, openocd.cfg).
This tool checks that the named probe is on USB, then execs openocd or avrdude.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

PROBES = ("nanodap", "stlink", "asp")

STLINK_VID = 0x0483
# F429-DISC1 onboard probe is 0483:374b. The rest are other ST-LINK variants.
STLINK_PIDS = frozenset({
    0x3744,
    0x3748,
    0x374A,
    0x374B,
    0x374D,
    0x374E,
    0x374F,
    0x3752,
    0x3753,
    0x3754,
})

ASP_VID = 0x16C0
ASP_PID = 0x05DC

DAPLINK_VID = 0x0D28
DAPLINK_PID = 0x0204

PROBE_INTERFACE = {
    "nanodap": "cmsis-dap",
    "stlink": "stlink",
}

INTERFACE_RE = re.compile(
    r"source\s+\[find\s+interface/(cmsis-dap|stlink)\.cfg\]"
)

USAGE = """\
usage:
  prog list
  prog openocd <nanodap|stlink> -- <openocd args>
  prog avrdude -- <avrdude args>

Probes:
  nanodap   CMSIS-DAP (nanoDAP). OpenOCD interface/cmsis-dap.cfg
  stlink    STM32F429-DISC1 onboard ST-LINK. OpenOCD interface/stlink.cfg
  asp       USBasp. avrdude -c usbasp
"""


class ProgError(Exception):
    pass


@dataclass(frozen=True)
class UsbDevice:
    name: str
    vid: int | None
    pid: int | None


def parse_id(value: object) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    token = value.split()[0]
    if not token.startswith("0x"):
        return None
    return int(token, 16)


def iter_devices(node: object) -> list[UsbDevice]:
    found: list[UsbDevice] = []

    def walk(item: object) -> None:
        if isinstance(item, dict):
            if "vendor_id" in item or "product_id" in item:
                found.append(
                    UsbDevice(
                        name=str(item.get("_name") or ""),
                        vid=parse_id(item.get("vendor_id")),
                        pid=parse_id(item.get("product_id")),
                    )
                )
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(node)
    return found


def is_stlink(device: UsbDevice) -> bool:
    return device.vid == STLINK_VID and device.pid in STLINK_PIDS


def is_asp(device: UsbDevice) -> bool:
    if device.vid == ASP_VID and device.pid == ASP_PID:
        return True
    return "usbasp" in device.name.lower()


def is_nanodap(device: UsbDevice) -> bool:
    if is_stlink(device):
        return False
    name = device.name.lower()
    if any(token in name for token in ("cmsis-dap", "daplink", "dap-link", "nanodap")):
        return True
    return device.vid == DAPLINK_VID and device.pid == DAPLINK_PID


def probe_of(device: UsbDevice) -> str | None:
    if is_stlink(device):
        return "stlink"
    if is_asp(device):
        return "asp"
    if is_nanodap(device):
        return "nanodap"
    return None


def group_probes(devices: list[UsbDevice]) -> dict[str, list[UsbDevice]]:
    grouped = {name: [] for name in PROBES}
    for device in devices:
        name = probe_of(device)
        if name is not None:
            grouped[name].append(device)
    return grouped


def format_list(grouped: dict[str, list[UsbDevice]]) -> str:
    lines = []
    for name in PROBES:
        devs = grouped[name]
        if not devs:
            lines.append(f"{name}  absent")
            continue
        device = devs[0]
        if device.vid is None or device.pid is None:
            ident = "no-id"
        else:
            ident = f"{device.vid:04x}:{device.pid:04x}"
        extra = f"  +{len(devs) - 1}" if len(devs) > 1 else ""
        lines.append(f"{name}  present  {device.name}  {ident}{extra}")
    return "\n".join(lines) + "\n"


def load_devices() -> list[UsbDevice]:
    try:
        raw = subprocess.check_output(
            ["system_profiler", "SPUSBDataType", "-json"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as exc:
        raise ProgError("system_profiler failed") from exc
    except FileNotFoundError as exc:
        raise ProgError("system_profiler not found") from exc
    start = raw.find("{")
    if start < 0:
        raise ProgError("system_profiler returned no JSON")
    try:
        payload, _ = json.JSONDecoder().raw_decode(raw[start:])
    except json.JSONDecodeError as exc:
        raise ProgError("system_profiler returned invalid JSON") from exc
    return iter_devices(payload)


def require_probe(probe: str, grouped: dict[str, list[UsbDevice]]) -> None:
    if probe not in grouped:
        raise ProgError(f"unknown probe: {probe}")
    if not grouped[probe]:
        raise ProgError(f"{probe} is not on the USB bus")


def config_paths(argv: list[str]) -> list[str]:
    paths = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in ("-f", "--file"):
            if index + 1 >= len(argv):
                raise ProgError(f"{arg} needs a file")
            paths.append(argv[index + 1])
            index += 2
            continue
        index += 1
    return paths


def interfaces_in(text: str) -> list[str]:
    found = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        match = INTERFACE_RE.search(stripped)
        if match is not None:
            found.append(match.group(1))
    return found


def check_openocd_configs(probe: str, argv: list[str], read_text) -> None:
    expected = PROBE_INTERFACE[probe]
    declared = []
    for path in config_paths(argv):
        try:
            text = read_text(path)
        except OSError as exc:
            raise ProgError(f"openocd config not found: {path}") from exc
        declared.extend(interfaces_in(text))
    if not declared:
        raise ProgError(
            "no openocd config declares an interface; "
            f"pass -f a board openocd.cfg that sources interface/{expected}.cfg"
        )
    for got in declared:
        if got != expected:
            raise ProgError(
                f"config sources interface/{got}.cfg; "
                f"probe {probe} requires interface/{expected}.cfg"
            )


def reject_avrdude_programmer(argv: list[str]) -> None:
    for arg in argv:
        if arg in ("-c", "--programmer"):
            raise ProgError("avrdude programmer is fixed to usbasp; do not pass -c")
        if arg.startswith("-c") and not arg.startswith("-C"):
            raise ProgError("avrdude programmer is fixed to usbasp; do not pass -c")


def build_openocd_argv(probe: str, user: list[str], read_text) -> list[str]:
    if probe not in PROBE_INTERFACE:
        raise ProgError(f"openocd probe must be nanodap or stlink, not {probe}")
    if not user:
        raise ProgError("openocd args required after --")
    check_openocd_configs(probe, user, read_text)
    return ["openocd", *user]


def build_avrdude_argv(user: list[str]) -> list[str]:
    if not user:
        raise ProgError("avrdude args required after --")
    reject_avrdude_programmer(user)
    return ["avrdude", "-c", "usbasp", *user]


def split_command(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" not in argv:
        raise ProgError("missing -- before the tool arguments")
    index = argv.index("--")
    return argv[:index], argv[index + 1 :]


def _read_config(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise ProgError(f"{name} not found")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        sys.stdout.write(USAGE)
        return 0 if args and args[0] in ("-h", "--help") else 1
    try:
        if args[0] == "list":
            if len(args) != 1:
                raise ProgError("prog list takes no arguments")
            sys.stdout.write(format_list(group_probes(load_devices())))
            return 0
        grouped = group_probes(load_devices())
        if args[0] == "openocd":
            head, user = split_command(args[1:])
            if len(head) != 1:
                raise ProgError(
                    "usage: prog openocd <nanodap|stlink> -- <openocd args>"
                )
            require_probe(head[0], grouped)
            _require_tool("openocd")
            cmd = build_openocd_argv(head[0], user, _read_config)
        elif args[0] == "avrdude":
            head, user = split_command(args[1:])
            if head:
                raise ProgError("usage: prog avrdude -- <avrdude args>")
            require_probe("asp", grouped)
            _require_tool("avrdude")
            cmd = build_avrdude_argv(user)
        else:
            raise ProgError(f"unknown command: {args[0]}")
    except ProgError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    try:
        os.execvp(cmd[0], cmd)
    except OSError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 1
