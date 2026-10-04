"""Command line client, mostly for checking a projector (or the simulator) by hand.

Examples::

    python -m pysdcp_extended discover --timeout 35
    python -m pysdcp_extended --ip 10.0.0.5 power
    python -m pysdcp_extended --ip 10.0.0.5 power on
    python -m pysdcp_extended --ip 10.0.0.5 get ASPECT_RATIO
    python -m pysdcp_extended --ip 10.0.0.5 set ASPECT_RATIO ZOOM_2_35
    python -m pysdcp_extended --ip 10.0.0.5 ir MENU
"""

from __future__ import annotations

import argparse
import sys

from pysdcp_extended import (
    DEFAULT_TCP_PORT,
    DEFAULT_TCP_TIMEOUT,
    DEFAULT_UDP_PORT,
    DEFAULT_UDP_TIMEOUT,
    Projector,
    SDCPError,
    discover_projectors,
)
from pysdcp_extended.protocol import COMMANDS_IR, SETTINGS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m pysdcp_extended", description="Query and control a Sony projector.")
    parser.add_argument("--ip", help="projector IP address (omit to discover one via SDAP)")
    parser.add_argument("--port", type=int, default=DEFAULT_TCP_PORT, help=f"SDCP TCP port (default: {DEFAULT_TCP_PORT})")
    parser.add_argument("--community", default="SONY", help="PJ Talk community (default: SONY)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TCP_TIMEOUT, help="TCP timeout in seconds (default: 2)")
    parser.add_argument("--udp-port", type=int, default=DEFAULT_UDP_PORT, help=f"SDAP UDP port (default: {DEFAULT_UDP_PORT})")
    sub = parser.add_subparsers(dest="action", required=True)

    discover = sub.add_parser("discover", help="list projectors advertising via SDAP")
    discover.add_argument("--timeout", dest="udp_timeout", type=float, default=DEFAULT_UDP_TIMEOUT, help="seconds to listen")

    sub.add_parser("info", help="model and serial via SDAP")
    sub.add_parser("status", help="power status, input, muting and lamp hours")
    power = sub.add_parser("power", help="show or change power")
    power.add_argument("state", nargs="?", choices=["on", "off"])
    hdmi = sub.add_parser("input", help="show or change the HDMI input")
    hdmi.add_argument("number", nargs="?", type=int, choices=[1, 2])
    mute = sub.add_parser("mute", help="show or change picture muting")
    mute.add_argument("state", nargs="?", choices=["on", "off"])
    sub.add_parser("lamp", help="lamp hours")
    get = sub.add_parser("get", help="read a named setting")
    get.add_argument("name", choices=sorted(SETTINGS))
    set_ = sub.add_parser("set", help="write a named setting")
    set_.add_argument("name", choices=sorted(SETTINGS))
    set_.add_argument("value")
    ir = sub.add_parser("ir", help="send a remote control key")
    ir.add_argument("name", choices=sorted(COMMANDS_IR))
    return parser


def run(args: argparse.Namespace) -> list[str]:
    if args.action == "discover":
        found = discover_projectors(timeout=args.udp_timeout, udp_port=args.udp_port)
        if not found:
            return ["No projector found"]
        return [f"{item.ip}\t{item.product_name}\tserial {item.serial_number}\tpower {item.power_state}" for item in found]

    projector = Projector(
        ip=args.ip, community=args.community, udp_port=args.udp_port, tcp_port=args.port, tcp_timeout=args.timeout
    )

    if args.action == "info":
        return [f"{key}: {value}" for key, value in projector.get_pjinfo().items()]
    if args.action == "status":
        return [
            f"power: {projector.get_power_status()}",
            f"input: {projector.get_input()}",
            f"muting: {projector.get_muting()}",
            f"lamp hours: {projector.get_lamp_timer()}",
        ]
    if args.action == "power":
        if args.state is not None:
            projector.set_power(args.state == "on")
        return [f"power: {projector.get_power_status()}"]
    if args.action == "input":
        if args.number is not None:
            projector.set_HDMI_input(args.number)
        return [f"input: {projector.get_input()}"]
    if args.action == "mute":
        if args.state is not None:
            projector.set_muting(args.state == "on")
        return [f"muting: {projector.get_muting()}"]
    if args.action == "lamp":
        return [f"lamp hours: {projector.get_lamp_timer()}"]
    if args.action == "get":
        return [f"{args.name}: {projector.get_setting(args.name)}"]
    if args.action == "set":
        projector.set_setting(args.name, args.value)
        return [f"{args.name}: {projector.get_setting(args.name)}"]
    if args.action == "ir":
        projector.send_ir_command(args.name)
        return [f"sent {args.name}"]
    raise AssertionError(args.action)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        lines = run(args)
    except (ValueError, SDCPError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
