"""Shared fixtures: a simulator per test and a client pointed at it."""

from __future__ import annotations

import socket
import time
from collections.abc import Callable, Iterator

import pytest

from pysdcp_extended import Projector
from pysdcp_extended.simulator import ProjectorSimulator, SimulatorState

FAST_TIMEOUT = 0.5


@pytest.fixture
def state() -> SimulatorState:
    return SimulatorState()


@pytest.fixture
def simulator(state: SimulatorState) -> Iterator[ProjectorSimulator]:
    with ProjectorSimulator("127.0.0.1", 0, state) as sim:
        yield sim


@pytest.fixture
def projector(simulator: ProjectorSimulator) -> Projector:
    return Projector(ip=simulator.host, tcp_port=simulator.port, tcp_timeout=FAST_TIMEOUT)


@pytest.fixture
def free_udp_port() -> int:
    """A UDP port on localhost that nothing is bound to right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def free_tcp_port() -> int:
    """A TCP port on localhost that nothing listens on (connections get refused)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for(condition: Callable[[], bool], timeout: float = 2.0) -> None:
    """Poll ``condition`` until it is true; fail if ``timeout`` seconds pass first."""
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(0.01)
