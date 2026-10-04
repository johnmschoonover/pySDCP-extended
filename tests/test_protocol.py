"""Pure unit tests for frame building and parsing, no sockets involved."""

from __future__ import annotations

import pytest

from pysdcp_extended import (
    Header,
    SDCPProtocolError,
    create_command_buffer,
    decode_text_field,
    process_command_response,
    process_SDAP,
)
from pysdcp_extended.protocol import (
    ACTIONS,
    COMMANDS,
    COMMANDS_IR,
    INPUTS,
    SETTINGS,
    is_ir_command,
    value_name,
)
from pysdcp_extended.simulator import SimulatorState, build_response, build_sdap_packet

HEADER = Header(version=2, category=0x0A, community="SONY")


def test_create_command_buffer_get() -> None:
    buf = create_command_buffer(HEADER, ACTIONS["GET"], COMMANDS["GET_STATUS_POWER"])
    assert bytes(buf) == b"\x02\x0aSONY\x01\x01\x02\x00"


def test_create_command_buffer_set_with_data() -> None:
    buf = create_command_buffer(HEADER, ACTIONS["SET"], COMMANDS["INPUT"], INPUTS["HDMI2"])
    assert bytes(buf) == b"\x02\x0aSONY\x00\x00\x01\x02\x00\x03"


def test_create_command_buffer_uses_community_from_header() -> None:
    buf = create_command_buffer(Header(2, 0x0A, "ROOM"), ACTIONS["GET"], COMMANDS["INPUT"])
    assert bytes(buf[2:6]) == b"ROOM"


def test_process_command_response_success_with_data() -> None:
    header, ok, command, data = process_command_response(build_response("SONY", True, COMMANDS["INPUT"], INPUTS["HDMI1"]))
    assert header == HEADER
    assert ok is True
    assert command == COMMANDS["INPUT"]
    assert data == INPUTS["HDMI1"]


def test_process_command_response_success_without_data() -> None:
    _, ok, command, data = process_command_response(build_response("SONY", True, COMMANDS["SET_POWER"], None))
    assert ok is True
    assert command == COMMANDS["SET_POWER"]
    assert data is None


def test_process_command_response_error_carries_code() -> None:
    _, ok, _, data = process_command_response(build_response("SONY", False, COMMANDS["INPUT"], 0x104))
    assert ok is False
    assert data == 0x104


@pytest.mark.parametrize(
    "buf",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"\x02\x0aSONY\x01", id="short-header"),
        pytest.param(b"\x02\x0aSONY\x01\x01\x02\x02\x00", id="missing-data-byte"),
    ],
)
def test_process_command_response_rejects_short_buffers(buf: bytes) -> None:
    with pytest.raises(SDCPProtocolError):
        process_command_response(buf)


def test_process_sdap_round_trip() -> None:
    state = SimulatorState(product_name="VPL-VW665", serial_number=0xDEADBEEF, power=3, location="Den")
    header, info = process_SDAP(build_sdap_packet(state))
    assert header == HEADER
    assert info.id == "DA"
    assert info.product_name == "VPL-VW665"
    assert info.serial_number == 0xDEADBEEF
    assert info.power_state == 3
    assert info.location == "Den"


def test_process_sdap_rejects_short_packet() -> None:
    with pytest.raises(SDCPProtocolError):
        process_SDAP(b"DA\x02\x0aSONY")


def test_decode_text_field_strips_padding() -> None:
    assert decode_text_field(b"VPL-VW520\x00\x00\x00") == "VPL-VW520"


def test_is_ir_command_matches_all_ir_code_sets() -> None:
    assert all(is_ir_command(code) for code in COMMANDS_IR.values())
    assert is_ir_command(0x1B02)
    assert not any(is_ir_command(code) for code in COMMANDS.values())


def test_value_name_reverse_lookup_and_fallback() -> None:
    assert value_name(INPUTS, INPUTS["HDMI2"]) == "HDMI2"
    assert value_name(INPUTS, 0x99) == 0x99


def test_every_setting_has_a_command_code() -> None:
    assert set(SETTINGS) <= set(COMMANDS)
    assert all(table for table in SETTINGS.values())
