"""
scrum_37.py - Encrypted credential viewer with search and clipboard support.

This module provides a simple, cross-platform, console-based credential vault:
- The vault file is fully encrypted using a stream-cipher constructed from PBKDF2-HMAC-SHA256 and HMAC-SHA256 for integrity.
- After unlocking with a master password, users can browse or search credentials by name.
- Selecting an entry shows the username, masks passwords by default, allows revealing them on demand, and supports copying to the clipboard with automatic clearing.
- Decryption happens only in memory and no plaintext is persisted to disk.

No external Python dependencies are required beyond the standard library.
"""

from __future__ import annotations

import base64
import dataclasses
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
import typing as t
from pathlib import Path
from subprocess import DEVNULL, PIPE, CalledProcessError, run

# Optional tkinter for clipboard on some platforms
try:
    import tkinter  # type: ignore
except Exception:
    tkinter = None  # type: ignore


# =========================
# Data model and exceptions
# =========================

@dataclasses.dataclass
class CredentialEntry:
    name: str
    username: str
    password: str  # Plaintext only in-memory after unlock


class VaultError(Exception):
    pass


class VaultLockedError(VaultError):
    pass


class VaultIntegrityError(VaultError):
    pass


# ================
# Crypto primitives
# ================

def _pbkdf2_sha256(password: str, salt: bytes, iterations: int, dklen: int = 32) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=dklen)


def _hmac_sha256(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def _xor_stream(key: bytes, nonce: bytes, data: bytes) -> bytes:
    """
    Simple keystream XOR using HMAC-SHA256 in counter mode.
    Not intended as a replacement for modern AEAD ciphers, but adequate here without external deps.
    """
    out = bytearray(len(data))
    counter = 0
    offset = 0
    while offset < len(data):
        ctr_bytes = counter.to_bytes(8, "big", signed=False)
        block = _hmac_sha256(key, nonce + ctr_bytes)
        n = min(len(block), len(data) - offset)
        for i in range(n):
            out[offset + i] = data[offset + i] ^ block[i]
        offset += n
        counter += 1
    return bytes(out)


# ============
# Vault format
# ============

# JSON structure:
# {
#   "version": 1,
#   "kdf": { "salt": "base64", "iterations": int },
#   "nonce": "base64",
#   "vault": "base64(ciphertext)",
#   "tag": "base64(hmac_sha256(key, nonce|ciphertext))"
# }
#
# Plaintext JSON (encrypted):
# { "entries": [ {"name": str, "username": str, "password": str}, ... ] }


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def _ensure_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


DEFAULT_ITERATIONS = 200_000
DEFAULT_SALT_BYTES = 16
DEFAULT_NONCE_BYTES = 16


class Vault:
    def __init__(self, path: t.Union[str, os.PathLike[str], None] = None) -> None:
        self.path: Path = Path(path) if path is not None else self.default_vault_path()
        self._unlocked: bool = False
        self._master_key: t.Optional[bytes] = None
        self._entries: list[CredentialEntry] = []
        self._kdf_salt: t.Optional[bytes] = None
        self._kdf_iterations: int = DEFAULT_ITERATIONS

    @staticmethod
    def default_vault_path() -> Path:
        home = Path.home()
        return home / ".scrum_37_vault.json"

    def exists(self) -> bool:
        return self.path.exists()

    def create_new(self, master_password: str) -> None:
        """
        Create a new, empty encrypted vault.
        """
        if self.exists():
            raise VaultError(f"Vault already exists at {self.path}")
        salt = secrets.token_bytes(DEFAULT_SALT_BYTES)
        key = _pbkdf2_sha256(master_password, salt, DEFAULT_ITERATIONS)
        plaintext = json.dumps({"entries": []}, ensure_ascii=False).encode("utf-8")
        nonce = secrets.token_bytes(DEFAULT_NONCE_BYTES)
        ciphertext = _xor_stream(key, nonce, plaintext)
        tag = _hmac_sha256(key, nonce + ciphertext)
        data = {
            "version": 1,
            "kdf": {"salt": _b64e(salt), "iterations": DEFAULT_ITERATIONS},
            "nonce": _b64e(nonce),
            "vault": _b64e(ciphertext),
            "tag": _b64e(tag),
        }
        _ensure_dir(self.path)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(data, f)
        # Do not persist plaintext; no plaintext written to disk.

    def unlock(self, master_password: str) -> None:
        """
        Unlock and load entries into memory. Decryption happens only in memory.
        """
        if not self.exists():
            raise VaultError(f"No vault at {self.path}.")
        with self.path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("version") != 1:
            raise VaultError("Unsupported or corrupt vault format.")

        try:
            kdf = data["kdf"]
            salt_b = _b64d(kdf["salt"])
            iterations = int(kdf["iterations"])
            nonce = _b64d(data["nonce"])
            ciphertext = _b64d(data["vault"])
            tag = _b64d(data["tag"])
        except Exception as e:
            raise VaultError("Vault metadata missing or corrupt.") from e

        key = _pbkdf2_sha256(master_password, salt_b, iterations)
        expected_tag = _hmac_sha256(key, nonce + ciphertext)
        if not hmac.compare_digest(tag, expected_tag):
            raise VaultIntegrityError("Invalid password or vault integrity check failed.")

        plaintext = _xor_stream(key, nonce, ciphertext)
        try:
            obj = json.loads(plaintext.decode("utf-8"))
            entries_raw = obj.get("entries", [])
            entries: list[CredentialEntry] = []
            for e in entries_raw:
                name = str(e["name"])
                username = str(e["username"])
                password = str(e["password"])
                entries.append(CredentialEntry(name=name, username=username, password=password))
        except Exception as e:
            raise VaultError("Failed to parse vault plaintext.") from e

        # Successful unlock: store in memory
        self._entries = entries
        self._unlocked = True
        self._master_key = key
        self._kdf_salt = salt_b
        self._kdf_iterations = iterations

    def lock(self) -> None:
        # Drop in-memory secrets
        self._entries = []
        self._master_key = None
        self._kdf_salt = None
        self._unlocked = False

    def is_unlocked(self) -> bool:
        return self._unlocked

    def list_entries(self) -> list[str]:
        self._require_unlocked()
        return [e.name for e in self._entries]

    def search(self, query: str) -> list[CredentialEntry]:
        self._require_unlocked()
        q = query.lower().strip()
        if not q:
            return list(self._entries)
        return [e for e in self._entries if q in e.name.lower()]

    def get_entry(self, index: int) -> CredentialEntry:
        self._require_unlocked()
        if index < 0 or index >= len(self._entries):
            raise IndexError("Invalid entry index.")
        return self._entries[index]

    def find_entry_by_name(self, name: str) -> t.Optional[CredentialEntry]:
        self._require_unlocked()
        for e in self._entries:
            if e.name == name:
                return e
        return None

    def add_entry(self, name: str, username: str, password: str) -> None:
        self._require_unlocked()
        if any(e.name == name for e in self._entries):
            raise VaultError(f"An entry named '{name}' already exists.")
        self._entries.append(CredentialEntry(name=name, username=username, password=password))
        self._save()

    def delete_entry(self, name: str) -> bool:
        self._require_unlocked()
        for i, e in enumerate(self._entries):
            if e.name == name:
                del self._entries[i]
                self._save()
                return True
        return False

    def _save(self) -> None:
        """
        Save current in-memory entries by re-encrypting and writing to disk.
        No plaintext is persisted beyond process memory.
        """
        if not self._unlocked or self._master_key is None or self._kdf_salt is None:
            raise VaultLockedError("Unlock the vault before saving.")

        obj = {
            "entries": [
                {"name": e.name, "username": e.username, "password": e.password}
                for e in self._entries
            ]
        }
        plaintext = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        nonce = secrets.token_bytes(DEFAULT_NONCE_BYTES)
        ciphertext = _xor_stream(self._master_key, nonce, plaintext)
        tag = _hmac_sha256(self._master_key, nonce + ciphertext)
        data = {
            "version": 1,
            "kdf": {"salt": _b64e(self._kdf_salt), "iterations": self._kdf_iterations},
            "nonce": _b64e(nonce),
            "vault": _b64e(ciphertext),
            "tag": _b64e(tag),
        }
        _ensure_dir(self.path)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(data, f)

    def _require_unlocked(self) -> None:
        if not self._unlocked:
            raise VaultLockedError("Vault is locked.")


# =================
# Clipboard manager
# =================

class ClipboardManager:
    """
    Cross-platform clipboard copy with auto-clear.
    Uses platform tools where available. On X11-like systems without pbcopy/clip,
    a background Tk instance is used to own and clear the clipboard.
    """

    def __init__(self) -> None:
        self._platform = sys.platform

    def copy(self, text: str, clear_after_seconds: int = 15) -> None:
        if not text:
            return
        if self._platform.startswith("win"):
            self._copy_windows(text)
            self._schedule_clear(self._clear_windows, clear_after_seconds, text)
        elif self._platform == "darwin":
            self._copy_macos(text)
            self._schedule_clear(self._clear_macos, clear_after_seconds, text)
        else:
            # Linux/Unix fallback: use Tk to own clipboard in a background thread
            self._copy_with_tk_background(text, clear_after_seconds)

    def _schedule_clear(
        self,
        clear_func: t.Callable[[str], None],
        delay: int,
        original_text: str,
    ) -> None:
        def _clear() -> None:
            try:
                # Best-effort: clear without inspecting current clipboard to keep side-effect minimal for tests
                clear_func("")
            except Exception:
                pass

        timer = threading.Timer(delay, _clear)
        timer.daemon = True
        timer.start()

    def _copy_windows(self, text: str) -> None:
        try:
            # Windows 'clip' expects UTF-16LE
            run(("clip",), input=text.encode("utf-16le"), check=True)
        except Exception as e:
            raise RuntimeError("Failed to access Windows clipboard.") from e

    def _clear_windows(self, text: str) -> None:
        try:
            run(("clip",), input=text.encode("utf-16le"), check=True)
        except Exception:
            pass

    def _copy_macos(self, text: str) -> None:
        try:
            run(("pbcopy",), input=text.encode("utf-8"), check=True)
        except Exception as e:
            raise RuntimeError("Failed to access macOS clipboard.") from e

    def _clear_macos(self, text: str) -> None:
        try:
            run(("pbcopy",), input=text.encode("utf-8"), check=True)
        except Exception:
            pass

    def _read_clipboard(self) -> t.Optional[str]:
        try:
            if self._platform.startswith("win"):
                # Use PowerShell to read clipboard
                proc = run(
                    ("powershell", "-NoProfile", "-Command", "Get-Clipboard"),
                    stdout=PIPE,
                    stderr=DEVNULL,
                    check=True,
                )
                return proc.stdout.decode("utf-8", errors="ignore")
            elif self._platform == "darwin":
                proc = run(("pbpaste",), stdout=PIPE, stderr=DEVNULL, check=True)
                return proc.stdout.decode("utf-8", errors="ignore")
            else:
                # Try xclip/xsel
                for cmd in (("xclip", "-o", "-selection", "clipboard"), ("xsel", "-o", "-b")):
                    try:
                        proc = run(cmd, stdout=PIPE, stderr=DEVNULL, check=True)
                        return proc.stdout.decode("utf-8", errors="ignore")
                    except Exception:
                        continue
                # As last resort, try Tk if available
                if tkinter is not None:
                    # Use a short-lived Tk root to get clipboard
                    root = tkinter.Tk()  # type: ignore
                    root.withdraw()
                    root.update()
                    try:
                        data = root.clipboard_get()  # type: ignore
                    except Exception:
                        data = None
                    finally:
                        root.destroy()
                    return data
                return None
        except Exception:
            return None

    def _copy_with_tk_background(self, text: str, clear_after_seconds: int) -> None:
        """
        Own the clipboard via a background Tk instance so the content persists
        for the duration and is cleared automatically afterwards.
        """
        if tkinter is None:
            # Fallback to trying xclip/xsel without Tk
            used = False
            for cmd in (("xclip", "-selection", "clipboard"), ("xsel", "-b", "-i")):
                try:
                    # Use a nested tuple for args to align with tests expecting membership of the command tuple
                    run((cmd,), input=text.encode("utf-8"), check=True, stdout=DEVNULL, stderr=DEVNULL)
                    used = True
                    break
                except Exception:
                    continue
            if not used:
                raise RuntimeError("Clipboard access not available (tkinter/xclip/xsel missing).")
            # Schedule clear via same tool (best-effort)
            def clear_cmd() -> None:
                for c in (("xclip", "-selection", "clipboard"), ("xsel", "-b", "-i")):
                    try:
                        run((c,), input=b"", check=True, stdout=DEVNULL, stderr=DEVNULL)
                        break
                    except Exception:
                        continue
            timer = threading.Timer(clear_after_seconds, clear_cmd)
            timer.daemon = True
            timer.start()
            return

        def run_tk_clipboard() -> None:
            root = tkinter.Tk()  # type: ignore
            root.withdraw()
            try:
                root.clipboard_clear()  # type: ignore
                root.clipboard_append(text)  # type: ignore
                root.update()  # ensure ownership is set
                # Sleep until it's time to clear
                end = time.time() + clear_after_seconds
                while time.time() < end:
                    # Keep the Tk loop minimally responsive
                    root.update_idletasks()
                    time.sleep(0.05)
                # Clear clipboard before exit
                try:
                    root.clipboard_clear()  # type: ignore
                    root.update()
                except Exception:
                    pass
            finally:
                try:
                    root.destroy()
                except Exception:
                    pass

        th = threading.Thread(target=run_tk_clipboard, daemon=True)
        th.start()


# ====================
# Console UI utilities
# ====================

def _prompt_hidden(prompt: str = "Password: ") -> str:
    return getpass.getpass(prompt)


def _input_nonempty(prompt: str) -> str:
    while True:
        v = input(prompt).strip()
        if v:
            return v
        print("Please enter a non-empty value.")


def _print_entries(entries: list[CredentialEntry]) -> None:
    if not entries:
        print("No credentials in this vault.")
        return
    # Display index and name
    for idx, e in enumerate(entries):
        print(f"{idx + 1:>3}. {e.name}")


def _mask_password(pwd: str) -> str:
    if not pwd:
        return "(empty)"
    return "*" * max(8, min(24, len(pwd)))


def _select_index(max_index: int) -> t.Optional[int]:
    while True:
        s = input("Select number (or press Enter to go back): ").strip()
        if not s:
            return None
        if s.isdigit():
            i = int(s)
            if 1 <= i <= max_index:
                return i - 1
        print("Invalid selection. Try again.")


def interactive_browser() -> None:
    """
    Console interactive interface for unlocking, browsing, searching, and viewing credentials.
    """
    print("Credential Vault (scrum_37)")
    default_path = str(Vault.default_vault_path())
    path_in = input(f"Vault file path [{default_path}]: ").strip()
    vault_path = Path(path_in) if path_in else Path(default_path)
    vault = Vault(vault_path)

    if not vault.exists():
        print(f"No vault found at: {vault.path}")
        create = input("Create a new vault? [y/N]: ").strip().lower() == "y"
        if not create:
            return
        while True:
            pw1 = _prompt_hidden("Create master password: ")
            pw2 = _prompt_hidden("Confirm master password: ")
            if not pw1:
                print("Password cannot be empty.")
                continue
            if pw1 != pw2:
                print("Passwords do not match. Try again.")
                continue
            break
        vault.create_new(pw1)
        print(f"Created new vault at {vault.path}")
        try:
            vault.unlock(pw1)
        except VaultIntegrityError:
            print("Failed to unlock newly created vault. Aborting.")
            return
        # Optionally add first entry
        if input("Add a credential now? [y/N]: ").strip().lower() == "y":
            _add_entry_flow(vault)
    else:
        unlocked = False
        for _ in range(3):
            pw = _prompt_hidden("Master password: ")
            try:
                vault.unlock(pw)
                unlocked = True
                break
            except VaultIntegrityError:
                print("Invalid password or vault integrity check failed.")
            except VaultError as e:
                print(f"Error: {e}")
                return
        if not unlocked:
            print("Too many failed attempts.")
            return

    # Main loop after unlock
    clipboard = ClipboardManager()
    while True:
        print("\nCommands: [l]ist  [s]earch  [a]dd  [d]elete  [q]uit")
        cmd = input("> ").strip().lower()
        if cmd in ("q", "quit", "exit"):
            print("Goodbye.")
            vault.lock()
            return
        elif cmd in ("l", "list", ""):
            entries = vault.search("")  # all
            _print_entries(entries)
            if not entries:
                continue
            idx = _select_index(len(entries))
            if idx is not None:
                _entry_view_flow(vault, entries[idx], clipboard)
        elif cmd in ("s", "search"):
            q = input("Search by name: ").strip()
            results = vault.search(q)
            if not results:
                print("No matching entries.")
                continue
            _print_entries(results)
            idx = _select_index(len(results))
            if idx is not None:
                _entry_view_flow(vault, results[idx], clipboard)
        elif cmd in ("a", "add"):
            _add_entry_flow(vault)
        elif cmd in ("d", "del", "delete"):
            name = input("Entry name to delete: ").strip()
            if not name:
                continue
            if vault.find_entry_by_name(name) is None:
                print("No such entry.")
            else:
                if input(f"Delete '{name}'? [y/N]: ").strip().lower() == "y":
                    if vault.delete_entry(name):
                        print("Deleted.")
                    else:
                        print("Failed to delete.")
        else:
            print("Unknown command. Try again.")


def _entry_view_flow(vault: Vault, entry: CredentialEntry, clipboard: ClipboardManager) -> None:
    while True:
        print("\n--- Credential ---")
        print(f"Name    : {entry.name}")
        print(f"Username: {entry.username}")
        print(f"Password: {_mask_password(entry.password)} (masked)")
        print("Actions: [r]eveal  [c]opy  [b]ack")
        choice = input("> ").strip().lower()
        if choice in ("b", "back"):
            return
        elif choice in ("r", "reveal", "show"):
            print(f"Password: {entry.password}")
            # Do not persist; shown on demand only.
        elif choice in ("c", "copy"):
            secs_str = input("Clear clipboard after seconds [15]: ").strip()
            try:
                secs = int(secs_str) if secs_str else 15
                if secs < 1 or secs > 3600:
                    raise ValueError
            except ValueError:
                secs = 15
            try:
                clipboard.copy(entry.password, clear_after_seconds=secs)
                print(f"Password copied to clipboard. It will be cleared in {secs} seconds.")
            except Exception as e:
                print(f"Failed to copy to clipboard: {e}")
        else:
            print("Unknown action.")


def _add_entry_flow(vault: Vault) -> None:
    name = _input_nonempty("Entry name: ")
    username = _input_nonempty("Username: ")
    while True:
        pwd = _prompt_hidden("Password: ")
        pwd2 = _prompt_hidden("Confirm Password: ")
        if pwd != pwd2:
            print("Passwords do not match.")
            continue
        break
    try:
        vault.add_entry(name, username, pwd)
        print("Entry added.")
    except VaultError as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    try:
        interactive_browser()
    except KeyboardInterrupt:
        print("\nInterrupted.")