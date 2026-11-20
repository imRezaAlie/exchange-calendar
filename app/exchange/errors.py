"""Errors raised by the Exchange client. Messages are safe to show in the UI."""


class ExchangeError(Exception):
    """A calendar request could not be completed."""


class ExchangeAuthError(ExchangeError):
    """The server rejected the credentials."""


class ExchangeConfigError(ExchangeError):
    """The connection settings are incomplete or unsafe."""


class ExchangeTransportError(ExchangeError):
    """The server could not be reached or the TLS handshake failed."""
