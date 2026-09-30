"""A simple password vault secured by a master password.

This module implements a secure-at-rest credential vault using only Python's standard library.
Features:
- On first launch, prompts to create a master password that meets complexity requirements.
- Vault remains inaccessible until the correct master password is entered; incorrect attempts provide feedback.
- All credentials are encrypted at rest using a key derived from the master password (PBKDF2-HMAC-SHA256).
- Authenticated encryption using HMAC-SHA256 (encrypt-then-MAC) with a nonce-based stream cipher.
- Auto-locks after a period of inactivity or on demand.
- Includes a basic CLI for interacting with the vault.

Note: Cryptography implemented here uses standard primitives but is a simplified construction due to the constraint of using only the Python standard library.
"""

from __future__ import annotations

import getpass
import hmac
import hashlib
import json
import os
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Callable


# File format constants
MAGIC = b"SV29"  # Scrum Vault v29 magic
SALT_LEN = 16
NONCE_LEN = 16
ITER_COUNT = 200_000  # PBKDF2 iterations
MAC_LEN = 32

# Auto-lock defaults
DEFAULT_AUTOLOCK_SECONDS = 300  # 5 minutes

# Default vault file path
DEFAULT_VAULT_PATH = Path.home() / ".vault_scrum29.dat"


class VaultError(Exception):
    """Base exception for vault errors."""


class IntegrityError(VaultError):
    """Raised when integrity checks fail."""


def _pbkdf2_sha256(password: str, salt: bytes, iterations: int, dklen: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=dklen)


def _derive_keys(password: str, salt: bytes, iterations: int) -> Tuple[bytes, bytes]:
    """Derive encryption and MAC keys from a password using PBKDF2-HMAC-SHA256."""
    dk = _pbkdf2_sha256(password, salt, iterations, dklen=64)
    enc_key = dk[:32]
    mac_key = dk[32:]
    return enc_key, mac_key


def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    """Generate a keystream using HMAC-SHA256 over (nonce || counter)."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(enc_key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _compute_mac(mac_key: bytes, header_and_ciphertext: bytes) -> bytes:
    return hmac.new(mac_key, header_and_ciphertext, hashlib.sha256).digest()


def _password_complexity_errors(password: str) -> List[str]:
    errors: List[str] = []
    if len(password) < 12:
        errors.append("Password must be at least 12 characters long.")
    if not any(c.islower() for c in password):
        errors.append("Password must contain at least one lowercase letter.")
    if not any(c.isupper() for c in password):
        errors.append("Password must contain at least one uppercase letter.")
    if not any(c.isdigit() for c in password):
        errors.append("Password must contain at least one digit.")
    specials = set("!@#$%^&*()-_=+[]{}|;:,.<>/?`~")
    if not any(c in specials for c in password):
        errors.append("Password must contain at least one special character.")
    return errors


def _secure_write_atomic(path: Path, data: bytes) -> None:
    """Write data to a file atomically, with restrictive permissions."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    # Set restrictive permissions (best-effort)
    try:
        os.chmod(tmp_path, 0o600)
    except Exception:
        pass
    os.replace(tmp_path, path)


def _read_all(path: Path) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _pack_header(salt: bytes, iterations: int, nonce: bytes, ciphertext: bytes) -> bytes:
    if not (1 <= len(salt) <= 255 and 1 <= len(nonce) <= 255):
        raise ValueError("Invalid salt or nonce length for header.")
    parts = []
    parts.append(MAGIC)
    parts.append(bytes([len(salt)]))
    parts.append(salt)
    parts.append(iterations.to_bytes(4, "big"))
    parts.append(bytes([len(nonce)]))
    parts.append(nonce)
    parts.append(len(ciphertext).to_bytes(8, "big"))
    return b"".join(parts)


def _unpack_header(data: bytes) -> Tuple[bytes, int, bytes, int, int]:
    """
    Parse header and return (salt, iterations, nonce, ct_offset, ct_len).

    Raises IntegrityError on invalid format.
    """
    offset = 0
    if len(data) < 4 or data[:4] != MAGIC:
        raise IntegrityError("Invalid vault file magic.")
    offset += 4
    if offset + 1 > len(data):
        raise IntegrityError("Invalid header.")
    salt_len = data[offset]
    offset += 1
    if offset + salt_len > len(data):
        raise IntegrityError("Invalid salt length.")
    salt = data[offset:offset + salt_len]
    offset += salt_len
    if offset + 4 > len(data):
        raise IntegrityError("Invalid header (iterations).")
    iterations = int.from_bytes(data[offset:offset + 4], "big")
    offset += 4
    if offset + 1 > len(data):
        raise IntegrityError("Invalid header.")
    nonce_len = data[offset]
    offset += 1
    if offset + nonce_len > len(data):
        raise IntegrityError("Invalid nonce length.")
    nonce = data[offset:offset + nonce_len]
    offset += nonce_len
    if offset + 8 > len(data):
        raise IntegrityError("Invalid header (ciphertext length).")
    ct_len = int.from_bytes(data[offset:offset + 8], "big")
    offset += 8
    return salt, iterations, nonce, offset, ct_len


class Vault:
    """Encrypted password vault with master password protection and auto-lock."""

    def __init__(
        self,
        path: Path,
        autolock_seconds: int = DEFAULT_AUTOLOCK_SECONDS,
        on_autolock: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.path = path
        self.autolock_seconds = autolock_seconds
        self._on_autolock = on_autolock

        self._lock_obj = threading.RLock()
        self._timer: Optional[threading.Timer] = None
        self._last_activity: Optional[float] = None

        # Unlocked state
        self._data: Optional[Dict[str, Any]] = None
        self._salt: Optional[bytes] = None
        self._iterations: Optional[int] = None
        self._enc_key: Optional[bytes] = None
        self._mac_key: Optional[bytes] = None

    def is_initialized(self) -> bool:
        return self.path.exists()

    def is_unlocked(self) -> bool:
        with self._lock_obj:
            return self._data is not None

    def _reset_timer(self) -> None:
        if self.autolock_seconds <= 0:
            return
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self.autolock_seconds, self._auto_lock)
        self._timer.daemon = True
        self._timer.start()
        self._last_activity = time.time()

    def touch(self) -> None:
        """Mark activity and reset auto-lock timer."""
        with self._lock_obj:
            if self._data is not None:
                self._reset_timer()

    def _auto_lock(self) -> None:
        with self._lock_obj:
            if self._data is None:
                return
        # Call public lock outside to reuse logic
        try:
            self.lock()
            if self._on_autolock:
                self._on_autolock("Vault auto-locked due to inactivity.")
        except Exception:
            # Swallow exceptions in timer context
            pass

    def initialize_new_vault(self, master_password: str) -> None:
        """Initialize a new vault with the given master password."""
        with self._lock_obj:
            if self.path.exists():
                raise VaultError("Vault already exists.")
            salt = secrets.token_bytes(SALT_LEN)
            iterations = ITER_COUNT
            enc_key, mac_key = _derive_keys(master_password, salt, iterations)
            self._salt = salt
            self._iterations = iterations
            self._enc_key = enc_key
            self._mac_key = mac_key
            self._data = {"credentials": {}}
            self._write_encrypted()
            self._reset_timer()

    def unlock(self, master_password: str) -> None:
        """Unlock an existing vault with the master password."""
        with self._lock_obj:
            if not self.path.exists():
                raise VaultError("Vault file does not exist.")
            raw = _read_all(self.path)
            # Parse header
            if len(raw) < 4 + 1 + SALT_LEN + 4 + 1 + NONCE_LEN + 8 + MAC_LEN:
                raise IntegrityError("Vault file appears corrupted or incomplete.")
            try:
                salt, iterations, nonce, ct_offset, ct_len = _unpack_header(raw)
            except IntegrityError as e:
                raise IntegrityError(str(e))
            if ct_offset + ct_len + MAC_LEN != len(raw):
                raise IntegrityError("Vault file has incorrect length.")
            ciphertext = raw[ct_offset:ct_offset + ct_len]
            mac = raw[ct_offset + ct_len:ct_offset + ct_len + MAC_LEN]
            header = raw[:ct_offset] + ciphertext  # Build for MAC verification
            enc_key, mac_key = _derive_keys(master_password, salt, iterations)
            expected_mac = _compute_mac(mac_key, header)
            if not hmac.compare_digest(mac, expected_mac):
                raise VaultError("Incorrect master password or corrupted vault (MAC mismatch).")
            # Decrypt
            ks = _keystream(enc_key, nonce, len(ciphertext))
            plaintext = _xor_bytes(ciphertext, ks)
            try:
                data = json.loads(plaintext.decode("utf-8"))
            except Exception as e:
                raise IntegrityError(f"Failed to parse vault contents: {e}")
            if not isinstance(data, dict) or "credentials" not in data or not isinstance(data["credentials"], dict):
                raise IntegrityError("Vault contents are invalid.")
            # Set state
            self._salt = salt
            self._iterations = iterations
            self._enc_key = enc_key
            self._mac_key = mac_key
            self._data = data
            self._reset_timer()

    def lock(self) -> None:
        """Lock the vault; clears sensitive material from memory."""
        with self._lock_obj:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            self._last_activity = None
            # No pending changes beyond what's persisted after each operation
            self._data = None
            # Best-effort key clearing (strings/bytes are immutable; dereference)
            self._enc_key = None
            self._mac_key = None
            # Do not clear salt/iterations since those are non-sensitive file parameters
            # but they will be re-read on unlock anyway.
            self._salt = None
            self._iterations = None

    def _require_unlocked(self) -> None:
        if self._data is None:
            raise VaultError("Vault is locked. Please unlock first.")

    def _write_encrypted(self) -> None:
        """Serialize current data and write encrypted to disk."""
        assert self._data is not None
        assert self._enc_key is not None and self._mac_key is not None
        assert self._salt is not None and self._iterations is not None

        plaintext = json.dumps(self._data, separators=(",", ":")).encode("utf-8")
        nonce = secrets.token_bytes(NONCE_LEN)
        ks = _keystream(self._enc_key, nonce, len(plaintext))
        ciphertext = _xor_bytes(plaintext, ks)
        header = _pack_header(self._salt, self._iterations, nonce, ciphertext)
        mac = _compute_mac(self._mac_key, header + ciphertext)
        blob = header + ciphertext + mac

        # Ensure directory exists
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _secure_write_atomic(self.path, blob)

    def list_services(self) -> List[str]:
        with self._lock_obj:
            self._require_unlocked()
            self._reset_timer()
            return sorted(self._data["credentials"].keys())  # type: ignore[index]

    def add_credential(self, service: str, username: str, password: str) -> None:
        with self._lock_obj:
            self._require_unlocked()
            service_key = service.strip()
            if not service_key:
                raise VaultError("Service name cannot be empty.")
            self._data["credentials"][service_key] = {  # type: ignore[index]
                "username": username,
                "password": password,
                "updated_at": int(time.time()),
            }
            self._write_encrypted()
            self._reset_timer()

    def remove_credential(self, service: str) -> bool:
        with self._lock_obj:
            self._require_unlocked()
            existed = self._data["credentials"].pop(service, None) is not None  # type: ignore[index]
            if existed:
                self._write_encrypted()
            self._reset_timer()
            return existed

    def get_credential(self, service: str) -> Optional[Dict[str, str]]:
        with self._lock_obj:
            self._require_unlocked()
            self._reset_timer()
            entry = self._data["credentials"].get(service)  # type: ignore[index]
            if entry is None:
                return None
            return {
                "username": entry.get("username", ""),
                "password": entry.get("password", ""),
            }

    def last_activity(self) -> Optional[float]:
        with self._lock_obj:
            return self._last_activity


def _prompt_create_master_password() -> str:
    """Prompt user to create a master password that meets complexity."""
    print("Create a new master password for your vault.")
    while True:
        pw1 = getpass.getpass("Enter master password: ")
        errs = _password_complexity_errors(pw1)
        if errs:
            print("Password does not meet complexity requirements:")
            for e in errs:
                print(f"- {e}")
            continue
        pw2 = getpass.getpass("Confirm master password: ")
        if pw1 != pw2:
            print("Passwords do not match. Try again.")
            continue
        return pw1


def _prompt_unlock_password() -> str:
    return getpass.getpass("Enter master password: ")


def _print_autolock(msg: str) -> None:
    # Note: printing from timer thread; best effort
    try:
        sys.stdout.write(f"\n{msg}\n")
        sys.stdout.flush()
    except Exception:
        pass


def run_cli(vault_path: Path = DEFAULT_VAULT_PATH) -> None:
    vault = Vault(vault_path, autolock_seconds=DEFAULT_AUTOLOCK_SECONDS, on_autolock=_print_autolock)

    print(f"Vault location: {vault_path}")

    if not vault.is_initialized():
        print("No vault found. First-time setup.")
        master_pw = _prompt_create_master_password()
        try:
            vault.initialize_new_vault(master_pw)
        except Exception as e:
            print(f"Failed to create vault: {e}")
            sys.exit(1)
        print("Vault created and unlocked.")
    else:
        attempts = 0
        max_attempts = 5
        while attempts < max_attempts:
            master_pw = _prompt_unlock_password()
            try:
                vault.unlock(master_pw)
                print("Vault unlocked.")
                break
            except VaultError as e:
                attempts += 1
                remaining = max_attempts - attempts
                print(f"Unlock failed: {e}")
                if remaining > 0:
                    print(f"Please try again. Attempts remaining: {remaining}")
                else:
                    print("Too many failed attempts. Exiting.")
                    sys.exit(1)

    help_text = (
        "Commands:\n"
        "  help            Show this help\n"
        "  list            List services\n"
        "  add             Add or update a credential\n"
        "  get             Retrieve a credential\n"
        "  remove          Remove a credential\n"
        "  lock            Lock the vault\n"
        "  exit            Exit the application\n"
    )
    print(help_text)

    while True:
        try:
            cmd = input("vault> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            try:
                vault.lock()
            except Exception:
                pass
            break

        if cmd in ("help", "?"):
            print(help_text)
            continue

        if cmd == "list":
            try:
                services = vault.list_services()
                if services:
                    print("Services:")
                    for s in services:
                        print(f"- {s}")
                else:
                    print("No credentials stored.")
            except VaultError as e:
                print(f"Error: {e}")
            continue

        if cmd == "add":
            try:
                service = input("Service name: ").strip()
                username = input("Username: ").strip()
                pw = getpass.getpass("Password (stored encrypted): ")
                vault.add_credential(service, username, pw)
                print(f"Credential for '{service}' saved.")
            except VaultError as e:
                print(f"Error: {e}")
            continue

        if cmd == "get":
            try:
                service = input("Service name: ").strip()
                item = vault.get_credential(service)
                if not item:
                    print(f"No credential found for '{service}'.")
                else:
                    print(f"Username: {item['username']}")
                    print(f"Password: {item['password']}")
            except VaultError as e:
                print(f"Error: {e}")
            continue

        if cmd == "remove":
            try:
                service = input("Service name: ").strip()
                confirm = input(f"Remove credential for '{service}'? (y/N): ").strip().lower()
                if confirm == "y":
                    existed = vault.remove_credential(service)
                    if existed:
                        print(f"Removed '{service}'.")
                    else:
                        print(f"No credential found for '{service}'.")
                else:
                    print("Aborted.")
            except VaultError as e:
                print(f"Error: {e}")
            continue

        if cmd == "lock":
            try:
                vault.lock()
                print("Vault locked.")
                # Prompt to unlock again or allow exit
                attempts = 0
                max_attempts = 5
                while attempts < max_attempts:
                    choice = input("Type 'unlock' to unlock again, or 'exit' to quit: ").strip().lower()
                    if choice == "exit":
                        print("Goodbye.")
                        return
                    if choice == "unlock":
                        pw = _prompt_unlock_password()
                        try:
                            vault.unlock(pw)
                            print("Vault unlocked.")
                            break
                        except VaultError as e:
                            attempts += 1
                            remaining = max_attempts - attempts
                            print(f"Unlock failed: {e}")
                            if remaining > 0:
                                print(f"Attempts remaining: {remaining}")
                            else:
                                print("Too many failed attempts. Exiting.")
                                return
                    else:
                        print("Unknown choice.")
            except VaultError as e:
                print(f"Error: {e}")
            continue

        if cmd == "exit":
            try:
                vault.lock()
            except Exception:
                pass
            print("Goodbye.")
            break

        if cmd == "":
            # Empty input - ignore but still count as activity
            vault.touch()
            continue

        print("Unknown command. Type 'help' for available commands.")


if __name__ == "__main__":
    run_cli()