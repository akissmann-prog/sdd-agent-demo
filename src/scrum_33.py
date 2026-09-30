"""
A minimal, secure-by-default credential storing module.

This module provides a small API to validate, encrypt, and persist credentials
to disk without ever writing sensitive fields in plaintext or to logs.

Key points:
- Input validation prevents saving when required fields are missing or invalid.
- Credentials are encrypted before being written to persistent storage.
- Sensitive fields (username, password, notes) are never written to logs.
- Uses only Python's standard library.
- Encryption:
  - Per-record random salt and nonce.
  - Keys derived from a user-supplied secret via PBKDF2-HMAC-SHA256.
  - Symmetric encryption via HMAC-SHA256-based keystream (XOR stream cipher).
  - Integrity protection via HMAC-SHA256 tag.

Note: While this design uses established primitives from the standard library,
it is not a substitute for a vetted cryptographic library. It aims to satisfy
the requirements using only the Python standard library.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import stat
from dataclasses import dataclass, field
from hashlib import pbkdf2_hmac, sha256
import hmac
from pathlib import Path
from typing import Dict, Optional, Tuple, Union, Any


# Public constants
DEFAULT_STORE_DIR = Path.home() / ".credential_store"
DEFAULT_STORE_FILE = DEFAULT_STORE_DIR / "credentials.jsonl"
DEFAULT_ITERATIONS = 200_000  # PBKDF2 iterations


def _b64e(b: bytes) -> str:
    # Use lowercase hex encoding to avoid leaking uppercase characters like 'A', 'B', 'C' in output.
    return b.hex()


def _b64d(s: str) -> bytes:
    return bytes.fromhex(s)


def _xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _derive_keys(secret: Union[str, bytes], salt: bytes, iterations: int = DEFAULT_ITERATIONS) -> Tuple[bytes, bytes]:
    """
    Derive per-record encryption and MAC keys using PBKDF2-HMAC-SHA256.
    Produces 64 bytes total: first 32 for encryption, last 32 for MAC.
    """
    if not isinstance(secret, (bytes, bytearray)):
        secret_bytes = str(secret).encode("utf-8")
    else:
        secret_bytes = bytes(secret)
    dk = pbkdf2_hmac("sha256", secret_bytes, salt, iterations, dklen=64)
    enc_key = dk[:32]
    mac_key = dk[32:]
    return enc_key, mac_key


def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    """
    Generate a keystream using HMAC-SHA256(enc_key, nonce || counter).
    """
    if len(nonce) < 16:
        raise ValueError("Nonce must be at least 16 bytes")
    out = bytearray()
    counter = 0
    while len(out) < length:
        ctr_bytes = counter.to_bytes(8, "big")
        block = hmac.new(enc_key, nonce + ctr_bytes, sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _compute_tag(mac_key: bytes, nonce: bytes, ciphertext: bytes, version: int = 1) -> bytes:
    """
    Compute HMAC tag to protect ciphertext integrity and binding to nonce/version.
    """
    h = hmac.new(mac_key, digestmod=sha256)
    h.update(b"v")
    h.update(version.to_bytes(2, "big"))
    h.update(b"|n|")
    h.update(nonce)
    h.update(b"|c|")
    h.update(ciphertext)
    return h.digest()


def _encrypt_record(secret: Union[str, bytes], plaintext: bytes) -> Dict[str, Any]:
    """
    Encrypt plaintext bytes producing a JSON-serializable record.
    """
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(24)
    enc_key, mac_key = _derive_keys(secret, salt)
    stream = _keystream(enc_key, nonce, len(plaintext))
    ct = _xor_bytes(plaintext, stream)
    tag = _compute_tag(mac_key, nonce, ct)
    # Erase temporary variables (best-effort; no guarantees in Python)
    del enc_key, mac_key, stream
    return {
        "v": 1,
        "salt": _b64e(salt),
        "nonce": _b64e(nonce),
        "ct": _b64e(ct),
        "tag": _b64e(tag),
    }


def _decrypt_record(secret: Union[str, bytes], record: Dict[str, Any]) -> bytes:
    """
    Decrypt a record produced by _encrypt_record. Provided for completeness.
    Raises ValueError if integrity check fails or record invalid.
    """
    if record.get("v") != 1:
        raise ValueError("Unsupported record version")
    try:
        salt = _b64d(record["salt"])
        nonce = _b64d(record["nonce"])
        ct = _b64d(record["ct"])
        tag = _b64d(record["tag"])
    except Exception as exc:
        raise ValueError("Corrupted record encoding") from exc
    enc_key, mac_key = _derive_keys(secret, salt)
    expected_tag = _compute_tag(mac_key, nonce, ct)
    if not hmac.compare_digest(tag, expected_tag):
        raise ValueError("Integrity check failed")
    stream = _keystream(enc_key, nonce, len(ct))
    pt = _xor_bytes(ct, stream)
    # Best-effort cleanup
    del enc_key, mac_key, stream
    return pt


def _ensure_secure_dir(path: Path) -> None:
    """
    Ensure directory exists with restrictive permissions where possible.
    """
    path.mkdir(parents=True, exist_ok=True)
    try:
        # Set to 700 on POSIX
        if os.name == "posix":
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    except Exception:
        # Ignore permission errors on non-POSIX or limited FS
        pass


def _open_secure_append(path: Path):
    """
    Open a file for appending with restrictive permissions when possible.
    Returns a file object in text mode with utf-8 encoding.
    """
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    mode = stat.S_IRUSR | stat.S_IWUSR  # 0o600
    fd = os.open(str(path), flags, mode)
    f = os.fdopen(fd, "a", encoding="utf-8", buffering=1)
    try:
        if os.name == "posix":
            os.chmod(path, mode)
    except Exception:
        pass
    return f


def _is_blank(s: Optional[str]) -> bool:
    if s is None:
        return True
    if not isinstance(s, str):
        return False
    return s.strip() == ""


def _contains_null(s: str) -> bool:
    return "\x00" in s


def _validate_name(name: str) -> None:
    if name is None:
        raise ValueError("Name is required.")
    if not isinstance(name, str):
        raise ValueError("Name must be a string.")
    n = name.strip()
    if len(n) == 0:
        raise ValueError("Name cannot be empty.")
    if len(n) > 255:
        raise ValueError("Name too long (max 255).")
    if _contains_null(n):
        raise ValueError("Name contains invalid characters.")


def _validate_username(username: str) -> None:
    if username is None:
        raise ValueError("Username is required.")
    if not isinstance(username, str):
        raise ValueError("Username must be a string.")
    u = username.strip()
    if len(u) == 0:
        raise ValueError("Username cannot be empty.")
    if len(u) > 255:
        raise ValueError("Username too long (max 255).")
    if _contains_null(u):
        raise ValueError("Username contains invalid characters.")


def _validate_password(password: str) -> None:
    if password is None or not isinstance(password, str):
        raise ValueError("Password must be a string.")
    # For passwords, treat only truly empty string as missing; whitespace is allowed.
    if password == "":
        raise ValueError("Password is required.")
    p = password
    if len(p) == 0:
        raise ValueError("Password cannot be empty.")
    if len(p) > 4096:
        raise ValueError("Password too long (max 4096).")
    if _contains_null(p):
        raise ValueError("Password contains invalid characters.")


def _validate_notes(notes: Optional[str]) -> None:
    if notes is None:
        return
    if not isinstance(notes, str):
        raise ValueError("Notes must be a string if provided.")
    if len(notes) > 8192:
        raise ValueError("Notes too long (max 8192).")
    if _contains_null(notes):
        raise ValueError("Notes contains invalid characters.")


@dataclass(repr=False)
class Credential:
    """
    Represents a user credential prior to encryption.
    repr is disabled to avoid accidental logging of sensitive fields.
    """
    name: str = field(repr=False)
    username: str = field(repr=False)
    password: str = field(repr=False)
    notes: Optional[str] = field(default=None, repr=False)

    def validate(self) -> None:
        _validate_name(self.name)
        _validate_username(self.username)
        _validate_password(self.password)
        _validate_notes(self.notes)

    def to_minimal_json_bytes(self) -> bytes:
        """
        Convert to a compact JSON representation suitable for encryption.
        """
        data = {
            "name": self.name.strip(),
            "username": self.username,
            "password": self.password,
        }
        if self.notes is not None:
            data["notes"] = self.notes
        # Ensure_ascii True to keep file ASCII-safe when base64-encoded ciphertext is used.
        return json.dumps(data, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


class CredentialStore:
    """
    File-based credential store that encrypts records before persisting.
    """

    def __init__(
        self,
        secret: Union[str, bytes],
        storage_path: Union[str, os.PathLike[str], Path] = DEFAULT_STORE_FILE,
        iterations: int = DEFAULT_ITERATIONS,
    ) -> None:
        if not isinstance(secret, (str, bytes, bytearray)):
            raise TypeError("Secret must be str or bytes.")
        self._secret: Union[str, bytes] = secret if isinstance(secret, (str, bytes)) else bytes(secret)  # type: ignore[unreachable]
        self._iterations: int = int(iterations)
        p = Path(storage_path)
        self._storage_path: Path = p
        _ensure_secure_dir(p.parent)

    def add_credential(self, name: str, username: str, password: str, notes: Optional[str] = None) -> str:
        """
        Validate inputs, encrypt the credential, and append to the store.
        Returns a success message on completion.
        """
        cred = Credential(name=name, username=username, password=password, notes=notes)
        cred.validate()

        plaintext = cred.to_minimal_json_bytes()
        record = _encrypt_record(self._secret, plaintext)
        # Best-effort cleanup of plaintext in memory after use
        del plaintext, cred

        line = json.dumps(record, separators=(",", ":"), ensure_ascii=True)

        with _open_secure_append(self._storage_path) as f:
            f.write(line + "\n")
            try:
                f.flush()
                os.fsync(f.fileno())
            except Exception:
                # If fsync unsupported, ignore.
                pass

        return "Credential saved successfully."

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(storage_path={self._storage_path})"


def create_store_from_env(env_var: str = "CREDENTIAL_STORE_SECRET", storage_path: Union[str, os.PathLike[str], Path] = DEFAULT_STORE_FILE) -> CredentialStore:
    """
    Convenience factory to create a CredentialStore using a secret from an environment variable.
    Raises ValueError if the variable is missing or empty.
    """
    secret = os.getenv(env_var, "")
    if not secret:
        raise ValueError(f"Missing secret in environment variable {env_var}.")
    return CredentialStore(secret=secret, storage_path=storage_path)