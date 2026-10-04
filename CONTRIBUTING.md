# Contributing

Thanks for helping out. This page covers setting up a development environment, running the
checks, and testing against the simulator or a real projector.

## Development setup

The project uses [Poetry](https://python-poetry.org/) for dependencies and packaging.
Python 3.11 or newer is required.

```shell
pipx install poetry            # or: pip install --user poetry
git clone https://github.com/kennymc-c/pySDCP-extended.git
cd pySDCP-extended
poetry install --with dev
```

`poetry install` creates a virtual environment and installs the library in editable mode
together with the development tools (pytest, pytest-cov, ruff, mypy). Prefix commands with
`poetry run`, or start a shell inside the environment with `poetry env activate`.

If you prefer the virtual environment inside the project folder (handy for editors), run
`poetry config virtualenvs.in-project true` once before `poetry install`.

## Checks

These are the same four steps the GitHub Actions workflow runs on every push and pull request
(`.github/workflows/test.yaml`), on Python 3.11, 3.12, 3.13 and 3.14.

```shell
poetry run ruff check .                     # lint
poetry run ruff format --check .            # formatting (use `ruff format .` to fix)
poetry run mypy                             # type check (strict) of the package and the tests
poetry run pytest                           # tests
```

Useful variations:

```shell
poetry run pytest -v                        # one line per test
poetry run pytest --cov                     # with a coverage report
poetry run pytest tests/test_projector.py   # one file
poetry run pytest -k timeout                # tests whose name matches
poetry run pytest --durations=10            # find slow tests
```

The whole suite runs in well under ten seconds. Every test that touches the network uses
`127.0.0.1` and an ephemeral port, so the suite needs no hardware and no network access, and
several copies can run at once.

Please run `ruff format .` before committing; the CI fails on unformatted code.

## How the tests work

The library speaks plain TCP and UDP, so the tests talk to a fake projector instead of mocking
sockets. `pysdcp_extended/simulator.py` contains:

- `ProjectorSimulator`: a threaded TCP server that answers SDCP requests the way a VPL-VW
  series projector does. GET returns the stored value, SET validates the value against the
  tables in `protocol.py` and stores it, IR commands are accepted without a reply, and bad
  requests get the matching SDCP error code (invalid item, invalid data, different community,
  and so on).
- `SimulatorState`: the simulator's memory (power, lamp hours, every setting) and the knobs
  that make it misbehave: `fail_with` (answer a command with a given error code), `reply=False`
  (never answer, to trigger timeouts), `reply_bytes` (answer with arbitrary bytes),
  `hold_seconds` (delay the answer). It also records every request in `received`.
- `SDAPBroadcaster`: a thread that sends SDAP advertisements for a state to a given address,
  used to test discovery over localhost.
- `handle_request()` / `build_response()` / `build_sdap_packet()`: the pure functions behind
  the server, usable directly in tests that do not need a socket.

`tests/conftest.py` provides fixtures that start a simulator per test (`simulator`, `state`)
and a `Projector` pointed at it (`projector`), plus `free_udp_port` / `free_tcp_port` for tests
that need a port nobody listens on.

A typical test:

```python
def test_hdmi_input(projector: Projector, state: SimulatorState) -> None:
    projector.set_HDMI_input(2)
    assert state.get("INPUT") == INPUTS["HDMI2"]
    assert projector.get_input() == "HDMI 2"


def test_timeout(projector: Projector, state: SimulatorState) -> None:
    state.reply = False
    with pytest.raises(SDCPTimeoutError):
        projector.get_power()
```

Test files:

| File | Covers |
|---|---|
| `tests/test_protocol.py` | building request frames and parsing responses and SDAP packets, no sockets |
| `tests/test_projector.py` | every public `Projector` method against the simulator, and every error path |
| `tests/test_discovery.py` | `discover_projectors()`, `find_projector()` and `get_pjinfo()` over localhost UDP |
| `tests/test_simulator.py` | the simulator's own request handling |
| `tests/test_cli.py` | the command line client |

When you add a command or a setting:

1. Add the constants to `protocol.py`. If it is a GET/SET setting with a value table, add it to
   `SETTINGS` as well; `get_setting()` / `set_setting()`, the simulator and the CLI pick it up
   from there, and `test_every_named_setting_round_trips` covers it automatically.
2. Add a helper method to `Projector` if the setting deserves one.
3. Add a test for anything that is not just a table entry.

## Trying it by hand

### Against the simulator

Start a fake projector in one terminal. By default it listens on all interfaces on TCP 53484
(the real SDCP port) and broadcasts SDAP advertisements to UDP 53862 every 30 seconds, so it
looks like a projector to anything on your machine or your network.

```shell
poetry run python -m pysdcp_extended.simulator
poetry run python -m pysdcp_extended.simulator --port 5348 --no-sdap          # another port, no SDAP
poetry run python -m pysdcp_extended.simulator --model VPL-VW665 --serial 42 --on --lamp-hours 1500
poetry run python -m pysdcp_extended.simulator --sdap-target 127.0.0.1 --sdap-interval 2   # fast discovery on localhost
```

It logs every request it receives. In another terminal, use the command line client:

```shell
poetry run python -m pysdcp_extended --ip 127.0.0.1 status
poetry run python -m pysdcp_extended --ip 127.0.0.1 power on
poetry run python -m pysdcp_extended --ip 127.0.0.1 input 2
poetry run python -m pysdcp_extended --ip 127.0.0.1 get ASPECT_RATIO
poetry run python -m pysdcp_extended --ip 127.0.0.1 set ASPECT_RATIO ZOOM_2_35
poetry run python -m pysdcp_extended --ip 127.0.0.1 ir MENU
poetry run python -m pysdcp_extended discover --timeout 5     # needs the simulator's SDAP to reach this host
poetry run python -m pysdcp_extended --ip 127.0.0.1 info
```

Or from Python:

```python
from pysdcp_extended import Projector

p = Projector("127.0.0.1")
p.get_power_status()
p.set_setting("HDR", "AUTO")
```

Point any application that uses this library (a Home Assistant integration, a remote control
integration) at the machine running the simulator to test it without a projector. To test how
the application copes with a projector that is switched off, stop the simulator; to test
timeouts, start it with `--port` on a port where a firewall drops packets, or use
`SimulatorState(reply=False)` from Python.

### Against a real projector

Make sure IP control is enabled on the projector (**Setup** > **Network Setting**) and note the
PJ Talk community, which is `SONY` unless you changed it.

```shell
poetry run python -m pysdcp_extended discover --timeout 35        # waits one full SDAP interval
poetry run python -m pysdcp_extended --ip 10.1.2.3 info
poetry run python -m pysdcp_extended --ip 10.1.2.3 status
poetry run python -m pysdcp_extended --ip 10.1.2.3 get CALIBRATION_PRESET
poetry run python -m pysdcp_extended --ip 10.1.2.3 --community THEATER status
```

Things worth checking on hardware, because the simulator can only mirror the protocol manual:

- Every setting your model supports round-trips through `get`/`set` and the projector's menu
  shows the change. Settings the model does not support should produce
  `SDCPCommandError: ... Not Applicable Item` (or `Invalid Item`), not a hang.
- `status` while the projector is warming up and cooling down: `power` should move through
  `START_UP`, `START_UP_LAMP`, `POWER_ON`, `COOLING`, `COOLING2`, `STANDBY`.
- Pulling the network cable or powering the projector off at the mains should give a clear
  `SDCPConnectionError` / `SDCPTimeoutError` within the TCP timeout (2 seconds by default).

If a command behaves differently from what the manual says, please open an issue with the
model name and the output of `python -m pysdcp_extended --ip ... status`.

## Pull requests

- Keep each pull request to one topic.
- Add or update tests for behaviour changes, and run all four checks before pushing.
- Add an entry under `## [Unreleased]` in `CHANGELOG.md`.
- Do not bump the version in `pyproject.toml`; releases set it from the git tag.

## Releasing (maintainers)

Releases are built and published to PyPI by `.github/workflows/build+publish.yaml` when a
version tag is pushed. The tag sets the package version.

```shell
# move the Unreleased section in CHANGELOG.md under a new version heading, commit, then:
git tag 0.3.0
git push origin 0.3.0
```

The workflow refuses to publish a version that is not newer than the one already on PyPI.
