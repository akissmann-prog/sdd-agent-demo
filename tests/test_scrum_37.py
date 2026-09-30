import json
import types
import base64
import threading
import time
import os
import builtins
import pytest

import scrum_37


class ImmediateTimer:
    def __init__(self, delay, func):
        self.delay = delay
        self.func = func
        self.daemon = True

    def start(self):
        # Call immediately
        self.func()

    def cancel(self):
        pass


def deterministic_token_bytes(n):
    return b"\x01" * n


@pytest.fixture
def tmp_vault(tmp_path, monkeypatch):
    monkeypatch.setattr(scrum_37.secrets, "token_bytes", deterministic_token_bytes)
    path = tmp_path / "vault.json"
    v = scrum_37.Vault(path)
    v.create_new("master")
    return v


def test_vault_create_unlock_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(scrum_37.secrets, "token_bytes", deterministic_token_bytes)
    path = tmp_path / "vault.json"
    v = scrum_37.Vault(path)
    assert not v.exists()
    v.create_new("master")
    assert v.exists()
    assert not v.is_unlocked()
    v.unlock("master")
    assert v.is_unlocked()
    assert v.list_entries() == []
    v.lock()
    assert not v.is_unlocked()


def test_vault_unlock_wrong_password_raises(tmp_vault):
    v = tmp_vault
    with pytest.raises(scrum_37.VaultIntegrityError):
        v.unlock("wrong")


def test_vault_corrupt_tag_raises(tmp_vault):
    path = tmp_vault.path
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    # Corrupt the tag without updating it
    data["tag"] = base64.b64encode(b"\x00" * 32).decode("ascii")
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f)
    v2 = scrum_37.Vault(path)
    with pytest.raises(scrum_37.VaultIntegrityError):
        v2.unlock("master")


def test_vault_corrupt_plaintext_parse_error(tmp_vault):
    path = tmp_vault.path
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    salt = scrum_37._b64d(data["kdf"]["salt"])
    iterations = int(data["kdf"]["iterations"])
    nonce_b64 = data["nonce"]
    nonce = scrum_37._b64d(nonce_b64)
    key = scrum_37._pbkdf2_sha256("master", salt, iterations)
    bad_ciphertext = b"\x00\x01"
    data["vault"] = scrum_37._b64e(bad_ciphertext)
    new_tag = scrum_37._hmac_sha256(key, nonce + bad_ciphertext)
    data["tag"] = scrum_37._b64e(new_tag)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f)
    v2 = scrum_37.Vault(path)
    with pytest.raises(scrum_37.VaultError) as ei:
        v2.unlock("master")
    assert "Failed to parse vault plaintext" in str(ei.value)


def test_vault_add_and_persist_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(scrum_37.secrets, "token_bytes", deterministic_token_bytes)
    path = tmp_path / "vault.json"
    v = scrum_37.Vault(path)
    v.create_new("master")
    v.unlock("master")
    v.add_entry("Example", "user1", "p@ss")
    assert v.list_entries() == ["Example"]
    assert [e.name for e in v.search("ex")] == ["Example"]
    assert [e.name for e in v.search("  ")] == ["Example"]
    assert v.find_entry_by_name("Example") is not None
    e = v.get_entry(0)
    assert e.name == "Example" and e.username == "user1" and e.password == "p@ss"
    with pytest.raises(IndexError):
        v.get_entry(1)
    with pytest.raises(scrum_37.VaultError):
        v.add_entry("Example", "user2", "x")
    assert v.delete_entry("Example") is True
    assert v.delete_entry("Example") is False
    # Persisted content across unlocks
    v.add_entry("A", "u", "p")
    v2 = scrum_37.Vault(path)
    v2.unlock("master")
    assert v2.list_entries() == ["A"]


def test_vault_save_locked_raises(tmp_vault):
    v = tmp_vault
    v.unlock("master")
    v.lock()
    with pytest.raises(scrum_37.VaultLockedError):
        v._save()


def test_locked_operations_raise(tmp_vault):
    v = scrum_37.Vault(tmp_vault.path)
    with pytest.raises(scrum_37.VaultLockedError):
        v.list_entries()
    with pytest.raises(scrum_37.VaultLockedError):
        v.add_entry("x", "y", "z")
    with pytest.raises(scrum_37.VaultLockedError):
        v.search("x")
    with pytest.raises(scrum_37.VaultLockedError):
        v.find_entry_by_name("x")
    with pytest.raises(scrum_37.VaultLockedError):
        v.get_entry(0)
    with pytest.raises(scrum_37.VaultLockedError):
        v.delete_entry("x")


def test_mask_password_behavior():
    assert scrum_37._mask_password("") == "(empty)"
    # shorter than 8 -> 8 asterisks
    assert scrum_37._mask_password("abc") == "*" * 8
    # between 8 and 24 -> same as length
    assert scrum_37._mask_password("abcdefghij") == "*" * 10
    # longer than 24 -> 24 asterisks
    assert scrum_37._mask_password("x" * 100) == "*" * 24


def test_input_nonempty_loops(monkeypatch, capsys):
    inputs = ["", "  ", "ok"]
    it = iter(inputs)
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(it))
    val = scrum_37._input_nonempty("Enter: ")
    assert val == "ok"
    out = capsys.readouterr().out
    assert "Please enter a non-empty value." in out


def test_select_index_returns_none_on_empty(monkeypatch):
    inputs = ["", ]
    it = iter(inputs)
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(it))
    assert scrum_37._select_index(3) is None


def test_select_index_invalid_then_valid(monkeypatch, capsys):
    inputs = ["0", "abc", "2"]
    it = iter(inputs)
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(it))
    idx = scrum_37._select_index(3)
    assert idx == 1
    out = capsys.readouterr().out
    assert "Invalid selection. Try again." in out


def test_print_entries_output(capsys):
    entries = [
        scrum_37.CredentialEntry(name="Site A", username="u", password="p"),
        scrum_37.CredentialEntry(name="Site B", username="u2", password="p2"),
    ]
    scrum_37._print_entries(entries)
    out = capsys.readouterr().out.strip().splitlines()
    assert out[0].endswith("1. Site A")
    assert out[1].endswith("2. Site B")
    scrum_37._print_entries([])
    out2 = capsys.readouterr().out.strip()
    assert out2 == "No credentials in this vault."


def test_clipboard_windows_copy_and_clear(monkeypatch):
    monkeypatch.setattr(scrum_37.sys, "platform", "win32")
    cm = scrum_37.ClipboardManager()
    calls = []

    def run_stub(cmd, input=None, stdout=None, stderr=None, check=None):
        calls.append((tuple(cmd), input))
        # For read_clipboard we will stub method; this run is only for clip operations
        class Res:
            stdout = b""
        return Res()

    monkeypatch.setattr(scrum_37, "run", run_stub)
    # make timer immediate
    monkeypatch.setattr(scrum_37.threading, "Timer", lambda d, f: ImmediateTimer(d, f))
    # ensure read_clipboard returns the same to trigger clear
    monkeypatch.setattr(scrum_37.ClipboardManager, "_read_clipboard", lambda self: "secret")
    cm.copy("secret", clear_after_seconds=1)
    # Expect first call to copy to clip with UTF-16LE, second to clear
    assert calls[0][0] == ("clip",)
    assert calls[0][1] == "secret".encode("utf-16le")
    assert calls[1][0] == ("clip",)
    assert calls[1][1] == b"".encode("utf-16le")


def test_clipboard_macos_copy_and_clear(monkeypatch):
    monkeypatch.setattr(scrum_37.sys, "platform", "darwin")
    cm = scrum_37.ClipboardManager()
    calls = []

    def run_stub(cmd, input=None, stdout=None, stderr=None, check=None):
        calls.append((tuple(cmd), input))
        class Res:
            stdout = b""
        return Res()

    monkeypatch.setattr(scrum_37, "run", run_stub)
    monkeypatch.setattr(scrum_37.threading, "Timer", lambda d, f: ImmediateTimer(d, f))
    monkeypatch.setattr(scrum_37.ClipboardManager, "_read_clipboard", lambda self: "text")
    cm.copy("text", clear_after_seconds=1)
    assert calls[0][0] == ("pbcopy",)
    assert calls[0][1] == b"text"
    assert calls[1][0] == ("pbcopy",)
    assert calls[1][1] == b""


def test_clipboard_linux_no_tk_uses_xclip(monkeypatch):
    monkeypatch.setattr(scrum_37.sys, "platform", "linux")
    monkeypatch.setattr(scrum_37, "tkinter", None)
    cm = scrum_37.ClipboardManager()
    calls = []

    def run_stub(cmd, input=None, stdout=None, stderr=None, check=None):
        calls.append((tuple(cmd), input))
        class Res:
            stdout = b""
        return Res()

    monkeypatch.setattr(scrum_37, "run", run_stub)
    monkeypatch.setattr(scrum_37.threading, "Timer", lambda d, f: ImmediateTimer(d, f))
    cm.copy("abc", clear_after_seconds=1)
    # First should be xclip set, then clear via xclip
    # There might be only two calls, but accept at least two
    assert ("xclip", "-selection", "clipboard") in calls[0][0]
    assert calls[0][1] == b"abc"
    # ensure a clear call happened with empty input
    assert any(c[1] == b"" for c in calls[1:])


def test_clipboard_linux_no_tools_raises(monkeypatch):
    monkeypatch.setattr(scrum_37.sys, "platform", "linux")
    monkeypatch.setattr(scrum_37, "tkinter", None)

    def run_fail(cmd, input=None, stdout=None, stderr=None, check=None):
        raise RuntimeError("no tool")

    monkeypatch.setattr(scrum_37, "run", run_fail)
    cm = scrum_37.ClipboardManager()
    with pytest.raises(RuntimeError) as ei:
        cm.copy("abc", clear_after_seconds=1)
    assert "Clipboard access not available" in str(ei.value)


def test_clipboard_linux_with_tk_background(monkeypatch):
    monkeypatch.setattr(scrum_37.sys, "platform", "linux")

    actions = []

    class FakeTk:
        def __init__(self):
            actions.append("init")

        def withdraw(self):
            actions.append("withdraw")

        def clipboard_clear(self):
            actions.append("clear")

        def clipboard_append(self, text):
            actions.append(f"append:{text}")

        def update(self):
            actions.append("update")

        def update_idletasks(self):
            actions.append("update_idletasks")

        def destroy(self):
            actions.append("destroy")

    fake_tk_module = types.SimpleNamespace(Tk=FakeTk)
    monkeypatch.setattr(scrum_37, "tkinter", fake_tk_module)
    cm = scrum_37.ClipboardManager()
    # make sure no sleep loop
    cm.copy("xyz", clear_after_seconds=0)
    # Allow background thread to run
    time.sleep(0.05)
    assert "append:xyz" in actions
    assert "destroy" in actions


def test_read_clipboard_windows(monkeypatch):
    monkeypatch.setattr(scrum_37.sys, "platform", "win32")

    def run_stub(cmd, stdout=None, stderr=None, check=None, input=None):
        class Res:
            stdout = b"clipdata"
        return Res()

    monkeypatch.setattr(scrum_37, "run", run_stub)
    cm = scrum_37.ClipboardManager()
    assert cm._read_clipboard() == "clipdata"


def test_read_clipboard_darwin(monkeypatch):
    monkeypatch.setattr(scrum_37.sys, "platform", "darwin")

    def run_stub(cmd, stdout=None, stderr=None, check=None, input=None):
        class Res:
            stdout = b"pbdata"
        return Res()

    monkeypatch.setattr(scrum_37, "run", run_stub)
    cm = scrum_37.ClipboardManager()
    assert cm._read_clipboard() == "pbdata"


def test_read_clipboard_linux_fallbacks(monkeypatch):
    monkeypatch.setattr(scrum_37.sys, "platform", "linux")
    monkeypatch.setattr(scrum_37, "tkinter", None)

    def run_stub(cmd, stdout=None, stderr=None, check=None, input=None):
        if cmd[0] == "xclip":
            raise RuntimeError("xclip fail")
        class Res:
            stdout = b"xseldata"
        return Res()

    monkeypatch.setattr(scrum_37, "run", run_stub)
    cm = scrum_37.ClipboardManager()
    assert cm._read_clipboard() == "xseldata"