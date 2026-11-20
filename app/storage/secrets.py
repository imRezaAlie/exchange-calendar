"""Encrypted credential storage.

The password and account profile are encrypted. They are never written to
config.json, the calendar cache, or the log. The login keyring is preferred.
A local encrypted file is the fallback when the keyring cannot be opened.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from app.config import AppPaths

log = logging.getLogger(__name__)

SERVICE_NAME = "exchange-calendar"
_VAULT_KEY_ACCOUNT = "local-vault-key"
_PROFILE_FIELDS = ("email", "username", "domain", "ews_url", "auth_method")


def load_password(account: str, paths: AppPaths | None = None) -> str:
    record = _load_record(account, paths or AppPaths())
    return str(record.get("password") or "")


def load_profile(account: str = "", paths: AppPaths | None = None) -> dict[str, str]:
    paths = paths or AppPaths()
    record = _load_record(account, paths) if account else _only_record(paths)
    return {field: str(record.get(field) or "") for field in _PROFILE_FIELDS}


def save_credentials(
    account: str,
    password: str,
    profile: dict | None = None,
    paths: AppPaths | None = None,
) -> tuple[bool, str]:
    if not account:
        return False, "Enter an email address before saving the account."
    paths = paths or AppPaths()
    current = _load_record(account, paths)
    record = {field: str((profile or {}).get(field) or current.get(field) or "") for field in _PROFILE_FIELDS}
    record["password"] = password if password else str(current.get("password") or "")
    if password:
        record["password"] = password
    keyring_ok = False
    if paths.root is None and record["password"]:
        keyring_ok = _keyring_set(account, record["password"])
    try:
        _write_record(account, record, paths)
    except Exception:
        log.warning("The encrypted credential file could not be written.")
        if keyring_ok:
            return True, ""
        return False, "The account could not be saved."
    if keyring_ok or record["password"] or any(record[field] for field in _PROFILE_FIELDS):
        return True, ""
    return False, "No account details were entered."


def save_password(account: str, password: str, paths: AppPaths | None = None) -> tuple[bool, str]:
    if not account:
        return False, "Enter an email address before saving a password."
    if not password:
        return False, "No password was entered."
    return save_credentials(account, password, None, paths)


def delete_password(account: str, paths: AppPaths | None = None) -> None:
    if not account:
        return
    paths = paths or AppPaths()
    if paths.root is None:
        _keyring_delete(account)
    data = _read_vault(paths)
    accounts = data.get("accounts", {})
    identifier = _account_id(account)
    if identifier in accounts:
        accounts.pop(identifier, None)
        _write_vault(data, paths)


def _load_record(account: str, paths: AppPaths) -> dict:
    if not account:
        return {}
    password = _keyring_get(account) if paths.root is None else ""
    token = _read_vault(paths).get("accounts", {}).get(_account_id(account), "")
    record = _decrypt(token, paths) if token else {}
    if password:
        record["password"] = password
    return record


def _only_record(paths: AppPaths) -> dict:
    accounts = _read_vault(paths).get("accounts", {})
    if len(accounts) != 1:
        return {}
    return _decrypt(next(iter(accounts.values())), paths)


def _decrypt(token: str, paths: AppPaths) -> dict:
    if not token:
        return {}
    try:
        payload = json.loads(_fernet(paths).decrypt(token.encode("ascii")).decode("utf-8"))
    except Exception:
        log.warning("A saved account could not be decrypted.")
        return {}
    return payload if isinstance(payload, dict) else {}


def _account_id(account: str) -> str:
    return hashlib.sha256(account.strip().lower().encode("utf-8")).hexdigest()


def _write_record(account: str, record: dict, paths: AppPaths) -> None:
    token = _fernet(paths).encrypt(json.dumps(record, separators=(",", ":")).encode("utf-8")).decode("ascii")
    data = _read_vault(paths)
    accounts = data.setdefault("accounts", {})
    accounts[_account_id(account)] = token
    _write_vault(data, paths)


def _vault_file(paths: AppPaths) -> Path:
    return paths.data_dir / "credentials.vault"


def _read_vault(paths: AppPaths) -> dict:
    path = _vault_file(paths)
    if not path.exists():
        return {"accounts": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("The encrypted credential file could not be read.")
        return {"accounts": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("accounts"), dict):
        return {"accounts": {}}
    return payload


def _write_vault(payload: dict, paths: AppPaths) -> None:
    path = _vault_file(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        log.warning("Could not restrict the credential directory permissions.")
    temporary = path.with_suffix(".vault.tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)


def _fernet(paths: AppPaths):
    from cryptography.fernet import Fernet

    key = _vault_key(paths)
    return Fernet(key)


def _vault_key(paths: AppPaths) -> bytes:
    from cryptography.fernet import Fernet

    if paths.root is None:
        stored = _keyring_get(_VAULT_KEY_ACCOUNT)
        if stored:
            return stored.encode("ascii")
    key_path = paths.data_dir / "vault.key"
    if key_path.exists():
        key = key_path.read_bytes().strip()
        if key:
            return key
    key = Fernet.generate_key()
    if paths.root is None and _keyring_set(_VAULT_KEY_ACCOUNT, key.decode("ascii")):
        return key
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key + b"\n")
    try:
        os.chmod(key_path.parent, 0o700)
        os.chmod(key_path, 0o600)
    except OSError:
        log.warning("Could not restrict the vault key permissions.")
    return key


def _keyring_get(account: str) -> str:
    try:
        import keyring

        value = keyring.get_password(SERVICE_NAME, account)
    except Exception:
        log.warning("The system keyring is unavailable.")
        return ""
    return value or ""


def _keyring_set(account: str, secret: str) -> bool:
    try:
        import keyring

        keyring.set_password(SERVICE_NAME, account, secret)
    except Exception:
        log.warning("The system keyring could not store this secret.")
        return False
    return True


def _keyring_delete(account: str) -> None:
    try:
        import keyring

        keyring.delete_password(SERVICE_NAME, account)
    except Exception:
        log.info("No keyring secret was removed for this account.")
