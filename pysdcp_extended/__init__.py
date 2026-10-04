"""Extended SDCP / PJ Talk library to control Sony projectors."""

from __future__ import annotations

import socket
import time
from collections import namedtuple
from collections.abc import Iterator
from dataclasses import dataclass
from struct import pack_into, unpack

from pysdcp_extended.exceptions import (
    SDCPCommandError,
    SDCPConnectionError,
    SDCPDiscoveryError,
    SDCPError,
    SDCPProtocolError,
    SDCPTimeoutError,
)
from pysdcp_extended.protocol import (
    ACTIONS,
    ADVANCED_IRIS,
    ASPECT_RATIOS,
    CALIBRATION_PRESETS,
    COMMANDS,
    COMMANDS_IR,
    DYNAMIC_RANGES,
    ERROR_STATUS,
    HDR,
    INPUT_LAG_REDUCTION,
    INPUTS,
    IR_COMMAND_PREFIXES,
    LAMP_CONTROL,
    MENU_POSITIONS,
    MOTIONFLOW,
    PICTURE_MUTING,
    PICTURE_POSITIONS,
    POWER_STATUS,
    RESPONSE_ERRORS,
    SDCP_CATEGORY,
    SDCP_VERSION,
    SETTINGS,
    THREE_D_FORMATS,
    TWO_D_THREE_D_SELECT,
    is_ir_command,
    value_name,
)

__all__ = [
    "ACTIONS",
    "ADVANCED_IRIS",
    "ASPECT_RATIOS",
    "CALIBRATION_PRESETS",
    "COMMANDS",
    "COMMANDS_IR",
    "DEFAULT_TCP_PORT",
    "DEFAULT_TCP_TIMEOUT",
    "DEFAULT_UDP_PORT",
    "DEFAULT_UDP_TIMEOUT",
    "DYNAMIC_RANGES",
    "ERROR_STATUS",
    "HDR",
    "INPUTS",
    "INPUT_LAG_REDUCTION",
    "IR_COMMAND_PREFIXES",
    "LAMP_CONTROL",
    "MENU_POSITIONS",
    "MOTIONFLOW",
    "PICTURE_MUTING",
    "PICTURE_POSITIONS",
    "POWER_STATUS",
    "RESPONSE_ERRORS",
    "SDCP_CATEGORY",
    "SDCP_VERSION",
    "SETTINGS",
    "THREE_D_FORMATS",
    "TWO_D_THREE_D_SELECT",
    "DiscoveredProjector",
    "Header",
    "ProjInfo",
    "Projector",
    "SDCPCommandError",
    "SDCPConnectionError",
    "SDCPDiscoveryError",
    "SDCPError",
    "SDCPProtocolError",
    "SDCPTimeoutError",
    "create_command_buffer",
    "decode_text_field",
    "discover_projectors",
    "process_SDAP",
    "process_command_response",
]

DEFAULT_TCP_PORT = 53484
DEFAULT_UDP_PORT = 53862
DEFAULT_TCP_TIMEOUT = 2.0
# SDAP advertisements are sent every 30 seconds, so one full interval plus margin.
DEFAULT_UDP_TIMEOUT = 31.0

SDCP_HEADER_LENGTH = 10
SDAP_MIN_LENGTH = 26

Header = namedtuple("Header", ["version", "category", "community"])
ProjInfo = namedtuple("ProjInfo", ["id", "product_name", "serial_number", "power_state", "location"])


@dataclass(frozen=True)
class DiscoveredProjector:
    """A projector seen on the network via SDAP advertisement."""

    ip: str
    header: Header
    info: ProjInfo

    @property
    def product_name(self) -> str:
        return str(self.info.product_name)

    @property
    def serial_number(self) -> int:
        return int(self.info.serial_number)

    @property
    def power_state(self) -> int:
        return int(self.info.power_state)


def create_command_buffer(header: Header, action: int, command: int, data: int | None = None) -> bytearray:
    """Build the bytes of one SDCP request."""
    my_buf = bytearray(SDCP_HEADER_LENGTH + 2 if data is not None else SDCP_HEADER_LENGTH)
    my_buf[0] = SDCP_VERSION  # only works with version 2, don't know why
    my_buf[1] = header.category
    my_buf[2:6] = header.community.encode("ascii")[:4]
    my_buf[6] = action
    pack_into(">H", my_buf, 7, command)
    if data is not None:
        my_buf[9] = 2  # Data is always 2 bytes
        pack_into(">H", my_buf, 10, data)
    else:
        my_buf[9] = 0
    return my_buf


def process_command_response(msgBuf: bytes) -> tuple[Header, bool, int, int | None]:
    """Parse one SDCP response into (header, is_success, command, data).

    :raises SDCPProtocolError: if the buffer is too short to be a response
    """
    if len(msgBuf) < SDCP_HEADER_LENGTH:
        raise SDCPProtocolError(f"Response too short ({len(msgBuf)} bytes): {msgBuf!r}")
    my_header = Header(
        version=int(msgBuf[0]),
        category=int(msgBuf[1]),
        community=decode_text_field(msgBuf[2:6]),
    )
    is_success = bool(msgBuf[6])
    command = unpack(">H", msgBuf[7:9])[0]
    data_len = int(msgBuf[9])
    if data_len == 0:
        data = None
    elif len(msgBuf) < SDCP_HEADER_LENGTH + data_len:
        raise SDCPProtocolError(f"Response announces {data_len} data bytes but only {len(msgBuf) - SDCP_HEADER_LENGTH} present")
    else:
        data = int.from_bytes(msgBuf[SDCP_HEADER_LENGTH : SDCP_HEADER_LENGTH + data_len], "big")
    return my_header, is_success, command, data


def process_SDAP(SDAP_buffer: bytes) -> tuple[Header, ProjInfo]:
    """Parse one SDAP advertisement packet.

    :raises SDCPProtocolError: if the packet is too short
    """
    if len(SDAP_buffer) < SDAP_MIN_LENGTH:
        raise SDCPProtocolError(f"SDAP packet too short ({len(SDAP_buffer)} bytes): {SDAP_buffer!r}")
    my_header = Header(
        version=int(SDAP_buffer[2]),
        category=int(SDAP_buffer[3]),
        community=decode_text_field(SDAP_buffer[4:8]),
    )
    my_info = ProjInfo(
        id=decode_text_field(SDAP_buffer[0:2]),
        product_name=decode_text_field(SDAP_buffer[8:20]),
        serial_number=unpack(">I", SDAP_buffer[20:24])[0],
        power_state=unpack(">H", SDAP_buffer[24:26])[0],
        location=decode_text_field(SDAP_buffer[26:]),
    )
    return my_header, my_info


def decode_text_field(buf: bytes) -> str:
    """Convert a NUL padded char[] field to a Python string."""
    return buf.decode(errors="replace").strip("\x00")


def _open_sdap_socket(udp_ip: str, udp_port: int, timeout: float) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Lets several listeners (another client, a second discovery run) share the port.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(timeout)
        sock.bind((udp_ip, udp_port))
    except OSError as err:
        sock.close()
        raise SDCPConnectionError(f"Cannot listen for SDAP advertisements on {udp_ip or '*'}:{udp_port}: {err}") from err
    return sock


def _iter_sdap(timeout: float, udp_ip: str, udp_port: int) -> Iterator[DiscoveredProjector]:
    """Yield every valid SDAP advertisement heard until ``timeout`` seconds have passed."""
    deadline = time.monotonic() + timeout
    with _open_sdap_socket(udp_ip, udp_port, timeout) as sock:
        while (remaining := deadline - time.monotonic()) > 0:
            sock.settimeout(remaining)
            try:
                sdap_buffer, addr = sock.recvfrom(1028)
            except TimeoutError:
                return
            try:
                header, info = process_SDAP(sdap_buffer)
            except SDCPProtocolError:
                continue
            yield DiscoveredProjector(ip=addr[0], header=header, info=info)


def discover_projectors(
    timeout: float = DEFAULT_UDP_TIMEOUT,
    udp_ip: str = "",
    udp_port: int = DEFAULT_UDP_PORT,
    limit: int | None = None,
) -> list[DiscoveredProjector]:
    """Collect the projectors that advertise themselves via SDAP within ``timeout`` seconds.

    Projectors advertise every 30 seconds, so a timeout shorter than that may miss
    some of them. Returns an empty list if nothing was heard. Projectors are
    de-duplicated on serial number. With ``limit`` the search stops as soon as that
    many distinct projectors were heard.

    :raises SDCPConnectionError: if the UDP port cannot be bound
    """
    found: dict[int, DiscoveredProjector] = {}
    for item in _iter_sdap(timeout, udp_ip, udp_port):
        found[item.serial_number] = item
        if limit is not None and len(found) >= limit:
            break
    return list(found.values())


class Projector:
    """Control one Sony projector over SDCP (PJ Talk).

    :param ip: IP address of the projector, e.g. "10.0.0.5". If omitted, the first
        command runs SDAP discovery (which can take up to 30 seconds) and uses the
        first projector found.
    :param community: PJ Talk community configured on the projector, "SONY" by default
    :param udp_port: SDAP advertisement UDP port, 53862 by default
    :param tcp_port: PJ Talk / SDCP TCP port, 53484 by default
    :param tcp_timeout: seconds to wait for a connection or a reply, 2 by default
    :param udp_timeout: seconds to wait for an SDAP advertisement, 31 by default
    """

    def __init__(
        self,
        ip: str | None = None,
        community: str = "SONY",
        udp_port: int = DEFAULT_UDP_PORT,
        tcp_port: int = DEFAULT_TCP_PORT,
        tcp_timeout: float = DEFAULT_TCP_TIMEOUT,
        udp_timeout: float = DEFAULT_UDP_TIMEOUT,
    ) -> None:
        self.info = ProjInfo(product_name=None, serial_number=None, power_state=None, location=None, id=None)
        self.ip = ip
        if ip is None:
            self.header = Header(version=None, category=None, community=None)
            self.is_init = False
        else:
            self.header = Header(version=SDCP_VERSION, category=SDCP_CATEGORY, community=community)
            self.is_init = True

        self.UDP_IP = ""
        self.UDP_PORT = udp_port
        self.TCP_PORT = tcp_port
        self.TCP_TIMEOUT = tcp_timeout
        self.UDP_TIMEOUT = udp_timeout

        # Valid settings, kept for backwards compatibility; see protocol.SETTINGS for all of them.
        self.SCREEN_SETTINGS = {
            "ASPECT_RATIO": ASPECT_RATIOS,
            "PICTURE_POSITION": PICTURE_POSITIONS,
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Projector):
            return NotImplemented
        return bool(self.info.serial_number == other.info.serial_number)

    def __repr__(self) -> str:
        return f"Projector(ip={self.ip!r}, community={self.header.community!r}, tcp_port={self.TCP_PORT})"

    def send_command(
        self,
        action: int,
        command: int,
        data: int | None = None,
        timeout: float | None = None,
    ) -> int | bool | None:
        """Send one raw SDCP command and return the response data.

        :param action: ``ACTIONS["GET"]`` or ``ACTIONS["SET"]``
        :param command: a value from ``COMMANDS`` or ``COMMANDS_IR``
        :param data: 16 bit payload for SET commands
        :param timeout: overrides the TCP timeout for this call
        :return: the 16 bit response data for a GET, ``None`` for a SET that carries
            no data, ``True`` for a simulated IR command (which gets no reply)
        :raises SDCPDiscoveryError: no IP known and discovery found nothing
        :raises SDCPTimeoutError: the projector did not answer in time
        :raises SDCPConnectionError: the projector refused or dropped the connection
        :raises SDCPProtocolError: the reply could not be parsed
        :raises SDCPCommandError: the projector rejected the command
        """
        if timeout is None:
            timeout = self.TCP_TIMEOUT
        if not self.is_init:
            self.find_projector()
        if not self.is_init:
            raise SDCPDiscoveryError("No projector found and / or specified")
        assert self.ip is not None

        my_buf = create_command_buffer(self.header, action, command, data)
        fire_and_forget = data is None and is_ir_command(command)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            try:
                sock.connect((self.ip, self.TCP_PORT))
                sock.sendall(my_buf)
                if fire_and_forget:
                    return True
                response_buf = sock.recv(1024)
            except TimeoutError as err:
                raise SDCPTimeoutError(f"Timeout after {timeout}s while sending command 0x{command:04x} to {self.ip}") from err
            except OSError as err:
                raise SDCPConnectionError(f"Cannot send command 0x{command:04x} to {self.ip}:{self.TCP_PORT}: {err}") from err

        if not response_buf:
            raise SDCPProtocolError(f"Projector {self.ip} closed the connection without answering command 0x{command:04x}")

        _, is_success, _, response_data = process_command_response(response_buf)
        if not is_success:
            raise SDCPCommandError(command, response_data)
        return response_data

    # Kept for backwards compatibility with code written against older releases.
    _send_command = send_command

    def find_projector(self, udp_ip: str | None = None, udp_port: int | None = None, timeout: float | None = None) -> bool:
        """Wait for the next SDAP advertisement and use that projector.

        Returns ``True`` and fills ``ip``, ``header`` and ``info`` if a projector was
        heard, ``False`` if the timeout expired.

        :raises SDCPConnectionError: if the UDP port cannot be bound
        """
        if udp_port is not None:
            self.UDP_PORT = udp_port
        if udp_ip is not None:
            self.UDP_IP = udp_ip
        if timeout is None:
            timeout = self.UDP_TIMEOUT

        for first in _iter_sdap(timeout, self.UDP_IP, self.UDP_PORT):
            self.header, self.info, self.ip = first.header, first.info, first.ip
            self.is_init = True
            return True
        return False

    def get_pjinfo(
        self, udp_ip: str | None = None, udp_port: int | None = None, timeout: float | None = None
    ) -> dict[str, str | int]:
        """Return ``{"model", "serial", "ip"}`` from the next SDAP advertisement.

        Can take up to 30 seconds. If this ``Projector`` has an IP, only an
        advertisement from that IP is accepted.

        :raises SDCPDiscoveryError: nothing was heard before the timeout
        :raises SDCPConnectionError: the UDP port cannot be bound
        """
        if udp_port is not None:
            self.UDP_PORT = udp_port
        if udp_ip is not None:
            self.UDP_IP = udp_ip
        if timeout is None:
            timeout = self.UDP_TIMEOUT

        for first in _iter_sdap(timeout, self.UDP_IP, self.UDP_PORT):
            if self.ip is not None and first.ip != self.ip:
                continue
            self.info = first.info
            return {"model": first.product_name, "serial": first.serial_number, "ip": first.ip}
        raise SDCPDiscoveryError(f"No SDAP advertisement received on port {self.UDP_PORT} within {timeout}s")

    # Named settings

    def get_setting(self, name: str) -> str | int:
        """Read a setting from ``protocol.SETTINGS`` and return its value name.

        If the projector reports a value the library does not know, the raw number
        is returned instead.

        :raises ValueError: ``name`` is not a key of ``SETTINGS``
        """
        table = _setting_table(name)
        data = self.send_command(action=ACTIONS["GET"], command=COMMANDS[name])
        return value_name(table, _as_int(data))

    def set_setting(self, name: str, value: str) -> bool:
        """Write a named value to a setting from ``protocol.SETTINGS``.

        :raises ValueError: unknown ``name`` or ``value`` not valid for it
        """
        table = _setting_table(name)
        if value not in table:
            raise ValueError(f"Invalid value for {name}: {value}. Expected one of: {list(table)}")
        self.send_command(action=ACTIONS["SET"], command=COMMANDS[name], data=table[value])
        return True

    def send_ir_command(self, name: str) -> bool:
        """Send a simulated remote control key from ``COMMANDS_IR``.

        :raises ValueError: unknown ``name``
        """
        if name not in COMMANDS_IR:
            raise ValueError(f"Invalid IR command: {name}. Expected one of: {list(COMMANDS_IR)}")
        self.send_command(action=ACTIONS["SET"], command=COMMANDS_IR[name])
        return True

    # Power

    def set_power(self, on: bool = True) -> bool:
        self.send_command(
            action=ACTIONS["SET"],
            command=COMMANDS["SET_POWER"],
            data=POWER_STATUS["START_UP"] if on else POWER_STATUS["STANDBY"],
        )
        return True

    def get_power(self) -> bool:
        """Return True if the projector is on or starting up, False if in standby or cooling."""
        data = self.send_command(action=ACTIONS["GET"], command=COMMANDS["GET_STATUS_POWER"])
        return data not in (POWER_STATUS["STANDBY"], POWER_STATUS["COOLING"], POWER_STATUS["COOLING2"])

    def get_power_status(self) -> str | int:
        """Return the power status name from ``POWER_STATUS`` (e.g. "COOLING")."""
        data = self.send_command(action=ACTIONS["GET"], command=COMMANDS["GET_STATUS_POWER"])
        return value_name(POWER_STATUS, _as_int(data))

    # Input

    def set_HDMI_input(self, hdmi_num: int) -> bool:
        """Switch to HDMI 1 or HDMI 2.

        :raises ValueError: ``hdmi_num`` is not 1 or 2
        """
        self.send_command(action=ACTIONS["SET"], command=COMMANDS["INPUT"], data=INPUTS[_hdmi_key(hdmi_num)])
        return True

    def get_input(self) -> str | None:
        """Return "HDMI 1" or "HDMI 2", or None for any other input."""
        data = self.send_command(action=ACTIONS["GET"], command=COMMANDS["INPUT"])
        if data == INPUTS["HDMI1"]:
            return "HDMI 1"
        if data == INPUTS["HDMI2"]:
            return "HDMI 2"
        return None

    # Screen

    def set_screen(self, command: str, value: str) -> bool:
        """Set an aspect ratio or picture position; see ``SCREEN_SETTINGS``.

        :raises ValueError: unknown ``command`` or ``value``
        """
        if command not in self.SCREEN_SETTINGS:
            raise ValueError(f"Invalid screen setting {command}. Expected one of: {list(self.SCREEN_SETTINGS)}")
        return self.set_setting(command, value)

    def get_screen(self, command: str) -> str | int:
        """Read an aspect ratio or picture position; see ``SCREEN_SETTINGS``."""
        if command not in self.SCREEN_SETTINGS:
            raise ValueError(f"Invalid screen setting {command}. Expected one of: {list(self.SCREEN_SETTINGS)}")
        return self.get_setting(command)

    def set_aspect_ratio(self, aspect_ratio: str) -> bool:
        return self.set_setting("ASPECT_RATIO", aspect_ratio)

    def get_aspect_ratio(self) -> str | int:
        return self.get_setting("ASPECT_RATIO")

    def set_picture_position(self, position: str) -> bool:
        return self.set_setting("PICTURE_POSITION", position)

    def get_picture_position(self) -> str | int:
        return self.get_setting("PICTURE_POSITION")

    # Picture muting

    def set_muting(self, on: bool = True) -> bool:
        self.send_command(
            action=ACTIONS["SET"],
            command=COMMANDS["PICTURE_MUTING"],
            data=PICTURE_MUTING["ON"] if on else PICTURE_MUTING["OFF"],
        )
        return True

    def get_muting(self) -> bool:
        data = self.send_command(action=ACTIONS["GET"], command=COMMANDS["PICTURE_MUTING"])
        return data != PICTURE_MUTING["OFF"]

    # HDMI dynamic range

    def get_HDMI_dynamic_range(self, hdmi_num: int) -> str | int:
        """:raises ValueError: ``hdmi_num`` is not 1 or 2"""
        return self.get_setting(f"{_hdmi_key(hdmi_num)}_DYNAMIC_RANGE")

    def get_HDMI1_dynamic_range(self) -> str | int:
        return self.get_HDMI_dynamic_range(1)

    def get_HDMI2_dynamic_range(self) -> str | int:
        return self.get_HDMI_dynamic_range(2)

    def set_HDMI_dynamic_range(self, hdmi_num: int, dynamic_range: str) -> bool:
        """:raises ValueError: ``hdmi_num`` is not 1 or 2, or ``dynamic_range`` is unknown"""
        return self.set_setting(f"{_hdmi_key(hdmi_num)}_DYNAMIC_RANGE", dynamic_range)

    def set_HDMI1_dynamic_range(self, dynamic_range: str) -> bool:
        return self.set_HDMI_dynamic_range(1, dynamic_range)

    def set_HDMI2_dynamic_range(self, dynamic_range: str) -> bool:
        return self.set_HDMI_dynamic_range(2, dynamic_range)

    # Calibration preset

    def set_calibration_preset(self, preset_name: str) -> bool:
        """:raises ValueError: ``preset_name`` is unknown"""
        return self.set_setting("CALIBRATION_PRESET", preset_name)

    def get_calibration_preset(self) -> str | int:
        return self.get_setting("CALIBRATION_PRESET")

    # Lamp

    def get_lamp_timer(self) -> int:
        """Return the lamp hours as a number."""
        return _as_int(self.send_command(action=ACTIONS["GET"], command=COMMANDS["GET_STATUS_LAMP_TIMER"]))

    def get_lamp_hours(self) -> str:
        """Return the lamp hours as a string (see ``get_lamp_timer`` for a number)."""
        return f"{self.get_lamp_timer():d}"


def _setting_table(name: str) -> dict[str, int]:
    try:
        return SETTINGS[name]
    except KeyError:
        raise ValueError(f"Invalid setting {name}. Expected one of: {list(SETTINGS)}") from None


def _hdmi_key(hdmi_num: int) -> str:
    if hdmi_num not in (1, 2):
        raise ValueError(f"Invalid HDMI input: {hdmi_num}. Expected 1 or 2")
    return f"HDMI{hdmi_num}"


def _as_int(data: int | bool | None) -> int:
    if data is None or isinstance(data, bool):
        raise SDCPProtocolError(f"Expected data in the response, got {data!r}")
    return data
