import json
import types
import base64
import builtins
import threading
import time

import pytest

import scrum_37


@pytest.fixture
def vault_path(tmp_path):
    return tmp_path / "vault.json"


@pytest.fixture
def new_vault(vault_path):
    v = scrum_37.Vault(vault_path)
    v.create_new("masterpw")
    return v


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def test_vault_create_unlock_add_delete_persist(vault_path):
    v = scrum_37.Vault(vault_path)
    assert not v.exists()
    v.create_new("masterpw")
    assert v.exists()

    # Unlock empty vault
    v.unlock("masterpw")
    assert v.is_unlocked()
    assert v.list_entries() == []
    assert v.search("") == []

    # Add entry and persist
    v.add_entry("github", "alice", "s3cr3t")
    assert v.list_entries() == ["github"]
    e = v.find_entry_by_name("github")
    assert e is not None
    assert e.username == "alice"
    assert e.password == "s3cr3t"

    # Search is case-insensitive substring
    assert [x.name for x in v.search("HUB")] == ["github"]
    assert [x.name for x in v.search("git")] == ["github"]
    assert v.search("nope") == []

    # Lock and unlock again; entry should persist
    v.lock()
    assert not v.is_unlocked()
    v.unlock("masterpw")
    assert v.list_entries() == ["github"]

    # Delete entry and persist
    assert v.delete_entry("github") is True
    assert v.list_entries() == []
    # Deleting non-existent returns False
    assert v.delete_entry("github") is False

    # Lock and unlock again; still empty
    v.lock()
    v.unlock("masterpw")
    assert v.list_entries() == []


def test_vault_duplicate_add_raises(new_vault):
    new_vault.unlock("masterpw")
    new_vault.add_entry("site", "bob", "pw")
    with pytest.raises(scrum_37.VaultError):
        new_vault.add_entry("site", "someone", "else")


def test_vault_locked_methods_raise(vault_path):
    v = scrum_37.Vault(vault_path)
    v.create_new("pw")
    with pytest.raises(scrum_37.VaultLockedError):
        v.list_entries()
    with pytest.raises(scrum_37.VaultLockedError):
        v.search("")
    with pytest.raises(scrum_37.VaultLockedError):
        v.get_entry(0)
    with pytest.raises(scrum_37.VaultLockedError):
        v.find_entry_by_name("x")
    with pytest.raises(scrum_37.VaultLockedError):
        v.add_entry("a", "u", "p")
    with pytest.raises(scrum_37.VaultLockedError):
        v.delete_entry("a")
    with pytest.raises(scrum_37.VaultLockedError):
        v._save()


def test_vault_get_entry_index_bounds(new_vault):
    new_vault.unlock("masterpw")
    new_vault.add_entry("only", "u", "p")
    with pytest.raises(IndexError):
        new_vault.get_entry(-1)
    with pytest.raises(IndexError):
        new_vault.get_entry(1)
    assert new_vault.get_entry(0).name == "only"


def test_unlock_wrong_password_raises_integrity_error(vault_path):
    v = scrum_37.Vault(vault_path)
    v.create_new("right")
    with pytest.raises(scrum_37.VaultIntegrityError):
        v.unlock("wrong")


def test_unlock_corrupt_metadata_raises(vault_path):
    v = scrum_37.Vault(vault_path)
    v.create_new("pw")
    data = read_json(vault_path)
    # Remove kdf block to trigger metadata error
    data.pop("kdf", None)
    write_json(vault_path, data)
    with pytest.raises(scrum_37.VaultError):
        v.unlock("pw")


def test_unlock_unsupported_version_raises(vault_path):
    v = scrum_37.Vault(vault_path)
    v.create_new("pw")
    data = read_json(vault_path)
    data["version"] = 999
    write_json(vault_path, data)
    with pytest.raises(scrum_37.VaultError):
        v.unlock("pw")


def test_unlock_corrupt_tag_raises_integrity(vault_path):
    v = scrum_37.Vault(vault_path)
    v.create_new("pw")
    data = read_json(vault_path)
    # Replace tag with incorrect value
    data["tag"] = base64.b64encode(b"badtag" * 5).decode("ascii")
    write_json(vault_path, data)
    with pytest.raises(scrum_37.VaultIntegrityError):
        v.unlock("pw")


def test_mask_password_variants():
    assert scrum_37._mask_password("") == "(empty)"
    assert scrum_37._mask_password("abc") == "*" * 8  # minimum 8
    assert scrum_37._mask_password("abcdefghij") == "*" * 10
    assert scrum_37._mask_password("x" * 100) == "*" * 24  # maximum 24


def test_input_nonempty(monkeypatch, capsys):
    inputs = ["", "   ", "value"]
    it = iter(inputs)
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(it))
    result = scrum_37._input_nonempty("Enter: ")
    captured = capsys.readouterr()
    # Should have printed warning twice (for two empty-like inputs)
    assert "Please enter a non-empty value." in captured.out
    assert result == "value"


def test_select_index(monkeypatch, capsys):
    # Invalid selection, then valid
    inputs = ["0", "abc", "2"]
    it = iter(inputs)
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(it))
    idx = scrum_37._select_index(3)
    out = capsys.readouterr().out
    assert "Invalid selection" in out
    assert idx == 1  # 2 -> 1 (0-based)

    # Empty to go back returns None
    it2 = iter(["", "should_not_be_used"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(it2))
    assert scrum_37._select_index(5) is None


def test_entry_view_flow_copy_and_reveal(monkeypatch, capsys):
    # Prepare entry and clipboard mock
    entry = scrum_37.CredentialEntry(name="site", username="user", password="pass123")
    clipboard_calls = []

    class FakeClipboard:
        def copy(self, text, clear_after_seconds=15):
            clipboard_calls.append((text, clear_after_seconds))

    # Simulate actions: reveal, copy with default seconds, back
    inputs = iter(["r", "c", "", "b"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(inputs))
    scrum_37._entry_view_flow(vault=None, entry=entry, clipboard=FakeClipboard())
    out = capsys.readouterr().out
    assert "Password: pass123" in out  # revealed
    assert clipboard_calls == [("pass123", 15)]
    assert "Password copied to clipboard" in out


def test_entry_view_flow_copy_invalid_seconds(monkeypatch, capsys):
    entry = scrum_37.CredentialEntry(name="site", username="user", password="pass123")
    clipboard_calls = []

    class FakeClipboard:
        def copy(self, text, clear_after_seconds=15):
            clipboard_calls.append((text, clear_after_seconds))

    # Provide invalid seconds, then back
    inputs = iter(["c", "bogus", "b"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(inputs))
    scrum_37._entry_view_flow(vault=None, entry=entry, clipboard=FakeClipboard())
    assert clipboard_calls == [("pass123", 15)]


def test_add_entry_flow_success_and_error(monkeypatch, capsys):
    # First, success with one mismatch then match
    add_calls = []

    class FakeVault:
        def add_entry(self, name, username, password):
            add_calls.append((name, username, password))

    # Mock _prompt_hidden to return mismatched first, then match
    hidden_inputs = iter(["p1", "p2", "p3", "p3"])
    monkeypatch.setattr(scrum_37, "_prompt_hidden", lambda prompt="": next(hidden_inputs))
    # Mock input_nonempty via builtins.input; _input_nonempty calls input then strips
    input_values = iter(["My Entry", "user1"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(input_values))

    scrum_37._add_entry_flow(FakeVault())
    out = capsys.readouterr().out
    assert "Passwords do not match." in out
    assert add_calls == [("My Entry", "user1", "p3")]
    assert "Entry added." in out

    # Now, error in add_entry
    class ErrorVault:
        def add_entry(self, name, username, password):
            raise scrum_37.VaultError("duplicate")

    hidden_inputs2 = iter(["x", "x"])
    monkeypatch.setattr(scrum_37, "_prompt_hidden", lambda prompt="": next(hidden_inputs2))
    input_values2 = iter(["Entry2", "user2"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(input_values2))

    scrum_37._add_entry_flow(ErrorVault())
    out2 = capsys.readouterr().out
    assert "Error: duplicate" in out2


def test_clipboard_windows_copy_and_clear(monkeypatch):
    mgr = scrum_37.ClipboardManager()
    mgr._platform = "win32"

    calls = []

    def fake_run(args, input=None, check=None, stdout=None, stderr=None):
        calls.append(("run", args, input))
        return types.SimpleNamespace()

    class ImmediateTimer:
        def __init__(self, *a, **k):
            self.func = a[1] if len(a) > 1 else k.get("function")
            self.daemon = False

        def start(self):
            # Call immediately
            self.func()

    monkeypatch.setattr(scrum_37, "run", fake_run)
    monkeypatch.setattr(scrum_37.threading, "Timer", ImmediateTimer)

    mgr.copy("Secret", clear_after_seconds=1)
    # Expect two calls: copy and clear (empty)
    assert len(calls) == 2
    # First call: copy to clip with UTF-16LE
    assert calls[0][1] == ("clip",)
    assert calls[0][2] == "Secret".encode("utf-16le")
    # Second call: clear with empty UTF-16LE
    assert calls[1][1] == ("clip",)
    assert calls[1][2] == "".encode("utf-16le")


def test_clipboard_macos_copy_and_clear(monkeypatch):
    mgr = scrum_37.ClipboardManager()
    mgr._platform = "darwin"

    calls = []

    def fake_run(args, input=None, check=None, stdout=None, stderr=None):
        calls.append(("run", args, input))
        return types.SimpleNamespace()

    class ImmediateTimer:
        def __init__(self, *a, **k):
            self.func = a[1] if len(a) > 1 else k.get("function")
            self.daemon = False

        def start(self):
            self.func()

    monkeypatch.setattr(scrum_37, "run", fake_run)
    monkeypatch.setattr(scrum_37.threading, "Timer", ImmediateTimer)

    mgr.copy("Secret", clear_after_seconds=1)
    assert len(calls) == 2
    assert calls[0][1] == ("pbcopy",)
    assert calls[0][2] == "Secret".encode("utf-8")
    assert calls[1][1] == ("pbcopy",)
    assert calls[1][2] == b""


def test_clipboard_linux_without_tk_uses_xclip_and_clear(monkeypatch):
    mgr = scrum_37.ClipboardManager()
    mgr._platform = "linux"

    # Force tkinter to None
    monkeypatch.setattr(scrum_37, "tkinter", None)

    calls = []

    def fake_run(args, input=None, check=None, stdout=None, stderr=None):
        # args is a nested tuple: ((cmd, ...),)
        calls.append(("run", args, input))
        return types.SimpleNamespace()

    class ImmediateTimer:
        def __init__(self, *a, **k):
            self.func = a[1] if len(a) > 1 else k.get("function")
            self.daemon = False

        def start(self):
            self.func()

    monkeypatch.setattr(scrum_37, "run", fake_run)
    monkeypatch.setattr(scrum_37.threading, "Timer", ImmediateTimer)

    mgr.copy("Secret", clear_after_seconds=1)
    # Expect two calls: one to set clipboard via xclip and one to clear via same tool
    assert len(calls) >= 2
    # First call should be xclip with input
    first_cmd = calls[0][1][0]
    assert first_cmd[0] in ("xclip", "xsel")
    assert calls[0][2] == "Secret".encode("utf-8")
    # Clear call should have empty input
    clear_cmd = calls[1][1][0]
    assert clear_cmd[0] in ("xclip", "xsel")
    assert calls[1][2] == b""


def test_clipboard_linux_with_tk_background(monkeypatch):
    mgr = scrum_37.ClipboardManager()
    mgr._platform = "linux"

    # Fake tkinter module
    class FakeRoot:
        def __init__(self):
            self.appended = None
            self.destroyed = False

        def withdraw(self):
            pass

        def clipboard_clear(self):
            self.appended = None

        def clipboard_append(self, text):
            self.appended = text

        def update(self):
            pass

        def update_idletasks(self):
            pass

        def destroy(self):
            self.destroyed = True

    class FakeTkModule:
        def __init__(self):
            self._root = None

        def Tk(self):
            self._root = FakeRoot()
            return self._root

    fake_tk = FakeTkModule()
    monkeypatch.setattr(scrum_37, "tkinter", fake_tk)

    # Make the background thread run synchronously
    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target
            self.daemon = daemon

        def start(self):
            if self._target:
                self._target()

    monkeypatch.setattr(scrum_37.threading, "Thread", ImmediateThread)

    # Use clear_after_seconds=0 to avoid loop sleeping
    mgr.copy("Secret", clear_after_seconds=0)
    # After run, clipboard should have been cleared before exit due to seconds=0 path
    # But we can at least assert that append was attempted, and destroy called
    root = fake_tk._root
    assert isinstance(root, FakeRoot)
    # Because clear_after_seconds=0, append then immediate clear -> appended becomes None
    assert root.destroyed is True


def test_clipboard_copy_empty_does_nothing(monkeypatch):
    mgr = scrum_37.ClipboardManager()
    mgr._platform = "darwin"
    called = {"run": False}

    def fake_run(args, input=None, check=None, stdout=None, stderr=None):
        called["run"] = True
        return types.SimpleNamespace()

    monkeypatch.setattr(scrum_37, "run", fake_run)
    mgr.copy("")
    assert called["run"] is False