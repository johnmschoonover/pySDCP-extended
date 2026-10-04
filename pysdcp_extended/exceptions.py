"""Exceptions raised by pysdcp-extended.

All library errors derive from :class:`SDCPError`, so callers can catch that one
class to handle any failure. The connection related errors also derive from the
matching built-in exception (``ConnectionError`` / ``TimeoutError``) so code that
already handles those keeps working.

Invalid arguments passed to the library (an unknown setting name, a value that is
not in the value table, an HDMI number other than 1 or 2) raise ``ValueError``,
not an ``SDCPError``: they are programming errors rather than projector errors.
"""

from __future__ import annotations

from pysdcp_extended.protocol import RESPONSE_ERRORS


class SDCPError(Exception):
    """Base class for every error raised by pysdcp-extended."""


class SDCPConnectionError(SDCPError, ConnectionError):
    """The projector could not be reached or the connection broke."""


class SDCPTimeoutError(SDCPConnectionError, TimeoutError):
    """The projector did not answer before the timeout expired."""


class SDCPProtocolError(SDCPError):
    """The projector answered with data that is not a valid SDCP / SDAP message."""


class SDCPDiscoveryError(SDCPError):
    """No projector was found via SDAP advertisement."""


class SDCPCommandError(SDCPError):
    """The projector answered a command with a failure status.

    :ivar command: the SDCP command code that was sent
    :ivar error_code: the error code returned by the projector (``None`` if the
        reply carried no data)
    :ivar error_message: the human readable text for ``error_code``
    """

    def __init__(self, command: int, error_code: int | None) -> None:
        self.command = command
        self.error_code = error_code
        if error_code is None:
            self.error_message = "No error code in response"
        else:
            self.error_message = RESPONSE_ERRORS.get(error_code, f"Unknown error code: 0x{error_code:x}")
        super().__init__(f"Projector returned an error for command 0x{command:04x}: {self.error_message}")
