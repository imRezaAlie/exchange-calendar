"""Build an exchangelib account for on-premises Exchange.

TLS verification is always left enabled. A private CA bundle may be added,
but certificate checks are never disabled. Basic authentication is used only
when the user selects it, and only over HTTPS.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from app.config import AppConfig
from app.exchange.errors import ExchangeAuthError, ExchangeConfigError, ExchangeError, ExchangeTransportError
from app.logging_config import redact

log = logging.getLogger(__name__)

AUTH_FAILED = (
    "Authentication failed. Check the username, password, domain, and authentication method."
)

_DEFAULT_ADAPTER = None


def format_username(username: str, domain: str) -> str:
    cleaned = username.strip()
    domain_name = domain.strip()
    if not cleaned:
        return domain_name
    if "\\" in cleaned or "@" in cleaned:
        return cleaned
    if domain_name:
        return f"{domain_name}\\{cleaned}"
    return cleaned


def tls_verify_setting(ca_bundle: str) -> str | bool:
    """Return a requests verify value that never disables TLS."""
    bundle = ca_bundle.strip()
    if bundle:
        return bundle
    return True


def _adapter_class(ca_bundle: str):
    from requests.adapters import HTTPAdapter

    class PrivateCAAdapter(HTTPAdapter):
        bundle = ca_bundle

        def send(self, request, **kwargs):
            verify = tls_verify_setting(self.bundle)
            if verify is False or verify is None:
                raise ExchangeConfigError("Refusing to disable TLS certificate verification.")
            kwargs["verify"] = verify
            return super().send(request, **kwargs)

    return PrivateCAAdapter


def configure_tls(ca_bundle: str) -> None:
    global _DEFAULT_ADAPTER
    from exchangelib.protocol import BaseProtocol

    if _DEFAULT_ADAPTER is None:
        _DEFAULT_ADAPTER = BaseProtocol.HTTP_ADAPTER_CLS
    bundle = ca_bundle.strip()
    if bundle:
        from pathlib import Path

        if not Path(bundle).is_file():
            raise ExchangeConfigError(f"The private CA bundle was not found: {bundle}")
        BaseProtocol.HTTP_ADAPTER_CLS = _adapter_class(bundle)
    else:
        BaseProtocol.HTTP_ADAPTER_CLS = _DEFAULT_ADAPTER
    BaseProtocol.TIMEOUT = 20


def _require_https(url: str) -> None:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ExchangeConfigError(
            "The EWS URL must be an HTTPS address. TLS verification cannot be disabled."
        )


def _load_symbols():
    from exchangelib import (
        BASIC,
        DELEGATE,
        NTLM,
        Account,
        Configuration,
        Credentials,
        EWSTimeZone,
    )

    try:
        from exchangelib import GSSAPI
    except ImportError:
        GSSAPI = None
    try:
        from exchangelib.protocol import FaultTolerance
    except ImportError:
        try:
            from exchangelib import FaultTolerance
        except ImportError:
            FaultTolerance = None
    return {
        "BASIC": BASIC,
        "DELEGATE": DELEGATE,
        "NTLM": NTLM,
        "GSSAPI": GSSAPI,
        "Account": Account,
        "Configuration": Configuration,
        "Credentials": Credentials,
        "EWSTimeZone": EWSTimeZone,
        "FaultTolerance": FaultTolerance,
    }


def _auth_type(method: str, symbols: dict):
    if method == "basic":
        return symbols["BASIC"]
    if method == "kerberos":
        if symbols["GSSAPI"] is None:
            raise ExchangeConfigError("This exchangelib build does not provide Kerberos authentication.")
        from exchangelib.transport import AUTH_TYPE_MAP

        if symbols["GSSAPI"] not in AUTH_TYPE_MAP:
            raise ExchangeConfigError(
                "Kerberos support is not installed. Install the system Kerberos libraries and the "
                "requests-gssapi package, then run kinit before connecting."
            )
        return symbols["GSSAPI"]
    return symbols["NTLM"]


def _credentials(config: AppConfig, password: str, symbols: dict):
    username = format_username(config.username or config.email, config.domain)
    if not username:
        raise ExchangeConfigError("Enter the Exchange username or email address.")
    if config.auth_method == "kerberos" and not password:
        # Kerberos uses the ticket from kinit. The password field is unused by GSSAPI.
        return symbols["Credentials"](username=username, password="")
    if not password:
        raise ExchangeConfigError("Enter the Exchange password. It is stored in the system keyring, not in a file.")
    return symbols["Credentials"](username=username, password=password)


def _configuration(config: AppConfig, credentials, auth_type, symbols: dict, endpoint: str | None):
    kwargs = {
        "credentials": credentials,
        "auth_type": auth_type,
    }
    if endpoint:
        kwargs["service_endpoint"] = endpoint
    fault = symbols["FaultTolerance"]
    if fault is not None:
        kwargs["retry_policy"] = fault(max_wait=20)
    return symbols["Configuration"](**kwargs)


def connect_account(config: AppConfig, password: str, tz: ZoneInfo | None = None):
    """Open an EWS account. The returned object belongs to exchangelib."""
    try:
        configure_tls(config.ca_bundle)
        symbols = _load_symbols()
    except ExchangeConfigError:
        raise
    except ImportError as exc:
        raise ExchangeConfigError(
            "The exchangelib package is not installed. Run ./install.sh and try again."
        ) from exc
    except Exception as exc:
        raise map_exception(exc) from exc

    if config.auth_method == "basic":
        if not config.ews_url and not config.use_autodiscover:
            raise ExchangeConfigError("Basic authentication requires an HTTPS EWS URL.")
        if config.ews_url:
            _require_https(config.ews_url)
    elif config.ews_url:
        _require_https(config.ews_url)

    if not config.email:
        raise ExchangeConfigError("Enter the Exchange email address.")

    credentials = _credentials(config, password, symbols)
    auth_type = _auth_type(config.auth_method, symbols)
    log.info(
        "Connecting to Exchange for %s with %s authentication.",
        config.email,
        config.auth_method,
    )
    try:
        account = _open_account(config, credentials, auth_type, symbols)
        _apply_timezone(account, tz, symbols["EWSTimeZone"])
        return account
    except ExchangeError:
        raise
    except Exception as exc:
        raise map_exception(exc) from exc


def _open_account(config: AppConfig, credentials, auth_type, symbols: dict):
    account_cls = symbols["Account"]
    if config.use_autodiscover:
        try:
            configuration = _configuration(config, credentials, auth_type, symbols, endpoint=None)
            return account_cls(
                primary_smtp_address=config.email,
                config=configuration,
                autodiscover=True,
                access_type=symbols["DELEGATE"],
            )
        except Exception as exc:
            if not config.ews_url:
                raise
            log.info("Autodiscover failed. Trying the configured EWS URL.")
            mapped = map_exception(exc)
            if isinstance(mapped, ExchangeAuthError):
                raise mapped from exc
    if not config.ews_url:
        raise ExchangeConfigError(
            "Enter the EWS URL or enable Autodiscover. An on-premises server usually uses "
            "https://exchange.company.com/EWS/Exchange.asmx."
        )
    _require_https(config.ews_url)
    configuration = _configuration(config, credentials, auth_type, symbols, endpoint=config.ews_url)
    return symbols["Account"](
        primary_smtp_address=config.email,
        config=configuration,
        autodiscover=False,
        access_type=symbols["DELEGATE"],
    )


def _apply_timezone(account, tz: ZoneInfo | None, ews_timezone) -> None:
    if tz is None:
        return
    try:
        account.default_timezone = ews_timezone.from_timezone(tz)
    except Exception:
        try:
            account.default_timezone = ews_timezone(key=getattr(tz, "key", "UTC"))
        except Exception:
            log.warning("Exchange responses will use the server timezone.")


def map_exception(exc: Exception) -> ExchangeError:
    if isinstance(exc, ExchangeError):
        return exc
    name = exc.__class__.__name__.lower()
    if "unauthorized" in name or "invalidcredentials" in name or "passwordexpired" in name:
        return ExchangeAuthError(AUTH_FAILED)
    if "autodiscover" in name:
        return ExchangeError(
            "Autodiscover failed. Enter the EWS URL, or check the email address and network connection."
        )
    if "ssl" in name or "certificate" in name:
        return ExchangeTransportError(
            "TLS certificate verification failed. Add the private CA certificate in Settings. "
            "Certificate verification stays enabled."
        )
    if "accessdenied" in name:
        return ExchangeError("Exchange denied access to this mailbox.")
    if "nonexistentmailbox" in name or "mailbox" in name and "not" in str(exc).lower():
        return ExchangeError("The mailbox was not found. Check the email address.")
    if any(token in name for token in ("timeout", "connection", "transport", "proxy", "redirect")):
        detail = redact(str(exc)).replace("\n", " ")
        if len(detail) > 180:
            detail = detail[:180] + "…"
        return ExchangeTransportError(f"Could not reach the Exchange server ({exc.__class__.__name__}). {detail}".strip())
    detail = redact(str(exc)).replace("\n", " ")
    if len(detail) > 180:
        detail = detail[:180] + "…"
    return ExchangeError(f"Exchange request failed ({exc.__class__.__name__}). {detail}".strip())
