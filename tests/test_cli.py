"""The command line client, driven against the simulator."""

from __future__ import annotations

import pytest

from pysdcp_extended.__main__ import main
from pysdcp_extended.simulator import ProjectorSimulator, SimulatorState


def _args(simulator: ProjectorSimulator, *rest: str) -> list[str]:
    return ["--ip", simulator.host, "--port", str(simulator.port), "--timeout", "0.5", *rest]


def test_power_and_status(simulator: ProjectorSimulator, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_args(simulator, "power", "on")) == 0
    assert main(_args(simulator, "status")) == 0
    out = capsys.readouterr().out
    assert "power: START_UP" in out
    assert "input: HDMI 1" in out
    assert "lamp hours: 123" in out


def test_get_set_and_ir(simulator: ProjectorSimulator, state: SimulatorState, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_args(simulator, "set", "HDR", "AUTO")) == 0
    assert state.get("HDR") == 2
    assert main(_args(simulator, "get", "HDR")) == 0
    assert main(_args(simulator, "ir", "CURSOR_UP")) == 0
    assert main(_args(simulator, "input", "2")) == 0
    assert main(_args(simulator, "mute", "on")) == 0
    assert main(_args(simulator, "lamp")) == 0
    out = capsys.readouterr().out
    assert "HDR: AUTO" in out
    assert "sent CURSOR_UP" in out
    assert "input: HDMI 2" in out
    assert "muting: True" in out


def test_errors_return_nonzero(simulator: ProjectorSimulator, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_args(simulator, "set", "HDR", "BOGUS")) == 1
    assert "error:" in capsys.readouterr().err


def test_connection_error_returns_nonzero(free_tcp_port: int, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--ip", "127.0.0.1", "--port", str(free_tcp_port), "--timeout", "0.5", "power"]) == 1
    assert "error:" in capsys.readouterr().err


def test_discover_with_nothing_on_the_wire(free_udp_port: int, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--udp-port", str(free_udp_port), "discover", "--timeout", "0.1"]) == 0
    assert "No projector found" in capsys.readouterr().out
