"""Client behaviour against the simulator, including every failure path."""

from __future__ import annotations

import pytest

from pysdcp_extended import (
    Projector,
    SDCPCommandError,
    SDCPConnectionError,
    SDCPDiscoveryError,
    SDCPError,
    SDCPProtocolError,
    SDCPTimeoutError,
)
from pysdcp_extended.protocol import ACTIONS, COMMANDS, COMMANDS_IR, INPUTS, POWER_STATUS, SETTINGS
from pysdcp_extended.simulator import ERROR_INVALID_DATA, ERROR_NOT_APPLICABLE_ITEM, ProjectorSimulator, SimulatorState
from tests.conftest import FAST_TIMEOUT, wait_for


def test_power_round_trip(projector: Projector, state: SimulatorState) -> None:
    assert projector.get_power() is False
    assert projector.get_power_status() == "STANDBY"

    assert projector.set_power(True) is True
    assert state.power == POWER_STATUS["START_UP"]
    assert projector.get_power() is True
    assert projector.get_power_status() == "START_UP"

    assert projector.set_power(False) is True
    assert state.power == POWER_STATUS["STANDBY"]
    assert projector.get_power() is False


@pytest.mark.parametrize(
    ("power", "expected"),
    [
        pytest.param(POWER_STATUS["STANDBY"], False, id="standby"),
        pytest.param(POWER_STATUS["START_UP"], True, id="start-up"),
        pytest.param(POWER_STATUS["START_UP_LAMP"], True, id="start-up-lamp"),
        pytest.param(POWER_STATUS["POWER_ON"], True, id="on"),
        pytest.param(POWER_STATUS["COOLING"], False, id="cooling"),
        pytest.param(POWER_STATUS["COOLING2"], False, id="cooling2"),
    ],
)
def test_get_power_for_every_status(projector: Projector, state: SimulatorState, power: int, expected: bool) -> None:
    state.power = power
    assert projector.get_power() is expected


def test_hdmi_input(projector: Projector, state: SimulatorState) -> None:
    assert projector.set_HDMI_input(2) is True
    assert state.get("INPUT") == INPUTS["HDMI2"]
    assert projector.get_input() == "HDMI 2"
    projector.set_HDMI_input(1)
    assert projector.get_input() == "HDMI 1"


def test_get_input_unknown_value_returns_none(projector: Projector, state: SimulatorState) -> None:
    state.settings[COMMANDS["INPUT"]] = 0x0004
    assert projector.get_input() is None


def test_set_hdmi_input_rejects_other_numbers(projector: Projector, state: SimulatorState) -> None:
    with pytest.raises(ValueError):
        projector.set_HDMI_input(3)
    assert state.received == []


def test_muting(projector: Projector, state: SimulatorState) -> None:
    assert projector.get_muting() is False
    projector.set_muting(True)
    assert state.get("PICTURE_MUTING") == 1
    assert projector.get_muting() is True
    projector.set_muting(False)
    assert projector.get_muting() is False


def test_lamp_hours(projector: Projector, state: SimulatorState) -> None:
    state.lamp_hours = 1987
    assert projector.get_lamp_timer() == 1987
    assert projector.get_lamp_hours() == "1987"


@pytest.mark.parametrize("name", sorted(SETTINGS))
def test_every_named_setting_round_trips(projector: Projector, state: SimulatorState, name: str) -> None:
    for value in SETTINGS[name]:
        assert projector.set_setting(name, value) is True
        assert state.get(name) == SETTINGS[name][value]
        assert projector.get_setting(name) == value


def test_get_setting_returns_raw_value_when_unknown(projector: Projector, state: SimulatorState) -> None:
    state.settings[COMMANDS["ASPECT_RATIO"]] = 0x42
    assert projector.get_setting("ASPECT_RATIO") == 0x42


@pytest.mark.parametrize(
    ("name", "value"),
    [
        pytest.param("NOT_A_SETTING", "NORMAL", id="unknown-setting"),
        pytest.param("ASPECT_RATIO", "NOT_A_VALUE", id="unknown-value"),
        pytest.param("GET_STATUS_POWER", "ON", id="command-but-not-a-setting"),
    ],
)
def test_set_setting_validates_arguments(projector: Projector, state: SimulatorState, name: str, value: str) -> None:
    with pytest.raises(ValueError):
        projector.set_setting(name, value)
    assert state.received == []


@pytest.mark.parametrize("name", ["NOT_A_SETTING", "GET_STATUS_POWER"])
def test_get_setting_validates_name(projector: Projector, state: SimulatorState, name: str) -> None:
    with pytest.raises(ValueError):
        projector.get_setting(name)
    assert state.received == []


def test_screen_helpers(projector: Projector, state: SimulatorState) -> None:
    projector.set_screen("ASPECT_RATIO", "ZOOM_2_35")
    assert projector.get_screen("ASPECT_RATIO") == "ZOOM_2_35"
    assert projector.get_aspect_ratio() == "ZOOM_2_35"
    projector.set_aspect_ratio("NORMAL")
    assert state.get("ASPECT_RATIO") == SETTINGS["ASPECT_RATIO"]["NORMAL"]
    projector.set_picture_position("CUSTOM_3")
    assert projector.get_picture_position() == "CUSTOM_3"
    with pytest.raises(ValueError):
        projector.set_screen("HDR", "ON")
    with pytest.raises(ValueError):
        projector.get_screen("HDR")


def test_dynamic_range_and_calibration_helpers(projector: Projector) -> None:
    projector.set_HDMI1_dynamic_range("FULL")
    projector.set_HDMI2_dynamic_range("LIMITED")
    assert projector.get_HDMI1_dynamic_range() == "FULL"
    assert projector.get_HDMI2_dynamic_range() == "LIMITED"
    assert projector.get_HDMI_dynamic_range(2) == "LIMITED"
    with pytest.raises(ValueError):
        projector.get_HDMI_dynamic_range(3)
    with pytest.raises(ValueError):
        projector.set_HDMI_dynamic_range(0, "AUTO")

    projector.set_calibration_preset("GAME")
    assert projector.get_calibration_preset() == "GAME"
    with pytest.raises(ValueError):
        projector.set_calibration_preset("NOPE")


def test_ir_command_is_fire_and_forget(projector: Projector, state: SimulatorState) -> None:
    assert projector.send_ir_command("MENU") is True
    # The client does not wait for a reply, so give the simulator thread a moment to log the request.
    wait_for(lambda: state.last is not None)
    assert state.last is not None
    assert state.last.command == COMMANDS_IR["MENU"]
    assert state.last.action == ACTIONS["SET"]
    with pytest.raises(ValueError):
        projector.send_ir_command("VOLUME_UP")


def test_send_command_is_public_and_private_alias_still_works(projector: Projector) -> None:
    assert projector.send_command(ACTIONS["GET"], COMMANDS["GET_STATUS_POWER"]) == POWER_STATUS["STANDBY"]
    assert projector._send_command(ACTIONS["GET"], COMMANDS["GET_STATUS_POWER"]) == POWER_STATUS["STANDBY"]


def test_command_error_carries_code_and_message(projector: Projector, state: SimulatorState) -> None:
    state.fail_with[COMMANDS["ASPECT_RATIO"]] = ERROR_NOT_APPLICABLE_ITEM
    with pytest.raises(SDCPCommandError) as excinfo:
        projector.get_aspect_ratio()
    err = excinfo.value
    assert err.command == COMMANDS["ASPECT_RATIO"]
    assert err.error_code == ERROR_NOT_APPLICABLE_ITEM
    assert err.error_message == "Item Error: Not Applicable Item"
    assert "0x0020" in str(err)
    assert isinstance(err, SDCPError)


def test_command_error_unknown_code(projector: Projector, state: SimulatorState) -> None:
    state.fail_with[COMMANDS["INPUT"]] = 0x7777
    with pytest.raises(SDCPCommandError, match="Unknown error code: 0x7777"):
        projector.get_input()


def test_simulator_rejects_invalid_data_like_a_projector(projector: Projector) -> None:
    with pytest.raises(SDCPCommandError) as excinfo:
        projector.send_command(ACTIONS["SET"], COMMANDS["INPUT"], 0x99)
    assert excinfo.value.error_code == ERROR_INVALID_DATA


def test_wrong_community_is_a_command_error(simulator: ProjectorSimulator) -> None:
    projector = Projector(ip=simulator.host, tcp_port=simulator.port, community="ROOM", tcp_timeout=FAST_TIMEOUT)
    with pytest.raises(SDCPCommandError, match="Different Community"):
        projector.get_power()


def test_timeout_is_typed_and_a_timeout_error(projector: Projector, state: SimulatorState) -> None:
    state.reply = False
    with pytest.raises(SDCPTimeoutError) as excinfo:
        projector.get_power()
    assert isinstance(excinfo.value, TimeoutError)
    assert isinstance(excinfo.value, ConnectionError)
    assert isinstance(excinfo.value, SDCPError)


def test_timeout_override_per_call(projector: Projector, state: SimulatorState) -> None:
    state.hold_seconds = 0.3
    with pytest.raises(SDCPTimeoutError):
        projector.send_command(ACTIONS["GET"], COMMANDS["GET_STATUS_POWER"], timeout=0.05)
    assert projector.send_command(ACTIONS["GET"], COMMANDS["GET_STATUS_POWER"], timeout=2) == POWER_STATUS["STANDBY"]


def test_connection_refused_is_typed(free_tcp_port: int) -> None:
    projector = Projector(ip="127.0.0.1", tcp_port=free_tcp_port, tcp_timeout=FAST_TIMEOUT)
    with pytest.raises(SDCPConnectionError) as excinfo:
        projector.get_power()
    assert isinstance(excinfo.value, ConnectionError)
    assert not isinstance(excinfo.value, SDCPTimeoutError)


def test_garbage_reply_is_a_protocol_error(projector: Projector, state: SimulatorState) -> None:
    state.reply_bytes = b"\x02\x0a"
    with pytest.raises(SDCPProtocolError):
        projector.get_power()


def test_closed_without_reply_is_a_protocol_error(projector: Projector, state: SimulatorState) -> None:
    state.reply_bytes = b""
    with pytest.raises(SDCPProtocolError, match="without answering"):
        projector.get_power()


def test_no_ip_and_no_advertisement_is_a_discovery_error(free_udp_port: int) -> None:
    projector = Projector(udp_port=free_udp_port, udp_timeout=0.1)
    projector.UDP_IP = "127.0.0.1"
    with pytest.raises(SDCPDiscoveryError):
        projector.get_power()


def test_equality_and_repr() -> None:
    a = Projector(ip="10.0.0.1")
    b = Projector(ip="10.0.0.2")
    assert a == b  # neither has a serial yet
    a.info = a.info._replace(serial_number=1)
    assert a != b
    assert a != object()
    assert "10.0.0.1" in repr(a)


def test_constructor_defaults_and_backwards_compatible_attributes() -> None:
    projector = Projector(ip="10.0.0.1")
    assert projector.is_init is True
    assert projector.header.community == "SONY"
    assert projector.TCP_PORT == 53484
    assert projector.UDP_PORT == 53862
    assert projector.TCP_TIMEOUT == 2
    assert projector.UDP_TIMEOUT == 31
    assert set(projector.SCREEN_SETTINGS) == {"ASPECT_RATIO", "PICTURE_POSITION"}
    assert Projector().is_init is False
