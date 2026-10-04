"""SDAP discovery against the simulator's broadcaster, over localhost UDP."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest

from pysdcp_extended import Projector, SDCPConnectionError, SDCPDiscoveryError, discover_projectors
from pysdcp_extended.simulator import SDAPBroadcaster, SimulatorState, build_sdap_packet

LOCALHOST = "127.0.0.1"
LISTEN = 1.0


@pytest.fixture
def broadcaster(state: SimulatorState, free_udp_port: int) -> Iterator[SDAPBroadcaster]:
    with SDAPBroadcaster(state, (LOCALHOST, free_udp_port), interval=0.05) as thread:
        yield thread


@pytest.mark.usefixtures("broadcaster")
def test_discover_projectors_finds_the_simulator(state: SimulatorState, free_udp_port: int) -> None:
    state.product_name = "VPL-VW285"
    state.serial_number = 42
    found = discover_projectors(timeout=LISTEN, udp_ip=LOCALHOST, udp_port=free_udp_port)
    assert len(found) == 1
    assert found[0].ip == LOCALHOST
    assert found[0].product_name == "VPL-VW285"
    assert found[0].serial_number == 42
    assert found[0].power_state == state.power
    assert found[0].header.community == "SONY"


def test_discover_projectors_times_out_to_empty_list(free_udp_port: int) -> None:
    assert discover_projectors(timeout=0.1, udp_ip=LOCALHOST, udp_port=free_udp_port) == []


def test_discover_projectors_reports_bind_failure() -> None:
    with pytest.raises(SDCPConnectionError):
        discover_projectors(timeout=0.1, udp_ip="203.0.113.1", udp_port=53862)


@pytest.mark.usefixtures("broadcaster")
def test_find_projector_fills_in_the_projector(free_udp_port: int, state: SimulatorState) -> None:
    projector = Projector()
    assert projector.is_init is False
    assert projector.find_projector(udp_ip=LOCALHOST, udp_port=free_udp_port, timeout=LISTEN) is True
    assert projector.is_init is True
    assert projector.ip == LOCALHOST
    assert projector.info.serial_number == state.serial_number
    assert projector.header.community == "SONY"


def test_find_projector_returns_false_on_timeout(free_udp_port: int) -> None:
    projector = Projector()
    assert projector.find_projector(udp_ip=LOCALHOST, udp_port=free_udp_port, timeout=0.1) is False
    assert projector.is_init is False


@pytest.mark.usefixtures("broadcaster")
def test_get_pjinfo(free_udp_port: int, state: SimulatorState) -> None:
    projector = Projector(ip=LOCALHOST)
    info = projector.get_pjinfo(udp_ip=LOCALHOST, udp_port=free_udp_port, timeout=LISTEN)
    assert info == {"model": state.product_name, "serial": state.serial_number, "ip": LOCALHOST}
    assert projector.info.product_name == state.product_name


@pytest.mark.usefixtures("broadcaster")
def test_get_pjinfo_ignores_other_projectors(free_udp_port: int) -> None:
    projector = Projector(ip="10.0.0.99")
    with pytest.raises(SDCPDiscoveryError):
        projector.get_pjinfo(udp_ip=LOCALHOST, udp_port=free_udp_port, timeout=0.3)


def test_get_pjinfo_timeout_is_typed(free_udp_port: int) -> None:
    projector = Projector(ip=LOCALHOST, udp_timeout=0.1)
    projector.UDP_IP = LOCALHOST
    with pytest.raises(SDCPDiscoveryError):
        projector.get_pjinfo(udp_port=free_udp_port)


def _send_later(payloads: list[bytes], target: tuple[str, int], delay: float = 0.1) -> threading.Timer:
    def send() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            for payload in payloads:
                sender.sendto(payload, target)

    timer = threading.Timer(delay, send)
    timer.start()
    return timer


def test_discover_projectors_skips_garbage_packets(state: SimulatorState, free_udp_port: int) -> None:
    timer = _send_later([b"not an SDAP packet", build_sdap_packet(state)], (LOCALHOST, free_udp_port))
    found = discover_projectors(timeout=1.0, udp_ip=LOCALHOST, udp_port=free_udp_port, limit=1)
    timer.join()
    assert [item.serial_number for item in found] == [state.serial_number]


def test_discover_projectors_dedupes_and_stops_at_limit(state: SimulatorState, free_udp_port: int) -> None:
    other = SimulatorState(product_name="VPL-VW260", serial_number=99)
    packets = [build_sdap_packet(state), build_sdap_packet(state), build_sdap_packet(other)]
    timer = _send_later(packets, (LOCALHOST, free_udp_port))
    started = time.monotonic()
    found = discover_projectors(timeout=5.0, udp_ip=LOCALHOST, udp_port=free_udp_port, limit=2)
    timer.join()
    assert time.monotonic() - started < 4.0
    assert sorted(item.serial_number for item in found) == [99, state.serial_number]


@pytest.mark.usefixtures("broadcaster")
def test_find_projector_returns_on_first_advertisement(free_udp_port: int) -> None:
    projector = Projector()
    started = time.monotonic()
    assert projector.find_projector(udp_ip=LOCALHOST, udp_port=free_udp_port, timeout=5.0) is True
    assert time.monotonic() - started < 4.0
