import io
import json
import os
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

import scrum_29 as mod


def test_password_complexity_errors():
    # Too short
    errs = mod._password_complexity_errors("aA1!short")
    assert "at least 12 characters" in errs[0]
    # Missing lowercase
    errs = mod._password_complexity_errors("AAAAAAAAAAAA1!")
    assert any("lowercase" in e for e in errs)
    # Missing uppercase
    errs = mod._password_complexity_errors("aaaaaaaaaaaa1!")
    assert any("uppercase" in e for e in errs)
    # Missing digit
    errs = mod._password_complexity_errors("Aa" + "!" * 10)
    assert any("digit" in e for e in errs)
    # Missing special
    errs = mod._password_complexity_errors("Aa" + "1" * 10)
    assert any("special" in e for e in errs)
    # Strong password has no errors
    errs = mod._password_complexity_errors("StrongPass!123")
    assert errs == []


def test_keystream_repeatability_and_difference():
    key = b"\x01" * 32
    nonce = b"\x02" * 16
    ks1 = mod._keystream(key, nonce, 100)
    ks2 = mod._keystream(key, nonce, 100)
    assert ks1 == ks2
    ks3 = mod._keystream(key, b"\x03" * 16, 100)
    assert ks1 != ks3
    # Different length yields prefix equal
    ks4 = mod._keystream(key, nonce, 50)
    assert ks1[:50] == ks4


def test_xor_bytes_basic_and_mismatch():
    a = b"\x00\xff\x0f"
    b = b"\xff\x00\xf0"
    assert mod._xor_bytes(a, b) == b"\xff\xff\xff"
    # Mismatch lengths uses zip -> min length
    assert mod._xor_bytes(b"ABC", b"\x01\x02") == bytes([ord("A") ^ 1, ord("B") ^ 2])


def test_compute_mac_matches_hmac():
    key = b"k" * 32
    msg = b"header" + b"ciphertext"
    expected = mod.hmac.new(key, msg, mod.hashlib.sha256).digest()
    assert mod._compute_mac(key, msg) == expected


def test_pack_unpack_header_roundtrip():
    salt = b"\x10" * 16
    iterations = 123456
    nonce = b"\x20" * 16
    ciphertext = b"\x33" * 5
    header = mod._pack_header(salt, iterations, nonce, ciphertext)
    rsalt, riter, rnonce, ct_offset, ct_len = mod._unpack_header(header + ciphertext)
    assert rsalt == salt
    assert riter == iterations
    assert rnonce == nonce
    assert ct_len == len(ciphertext)
    assert ct_offset == len(header)


def test_pack_header_invalid_lengths():
    with pytest.raises(ValueError):
        mod._pack_header(b"", 1, b"\x00" * 16, b"ct")
    with pytest.raises(ValueError):
        mod._pack_header(b"\x00" * 300, 1, b"\x00" * 16, b"ct")
    with pytest.raises(ValueError):
        mod._pack_header(b"\x00" * 16, 1, b"", b"ct")
    with pytest.raises(ValueError):
        mod._pack_header(b"\x00" * 16, 1, b"\x00" * 300, b"ct")


def test_unpack_header_invalid_magic_and_truncated():
    with pytest.raises(mod.IntegrityError):
        mod._unpack_header(b"BAD!")
    # Build a valid header then truncate in the middle of salt
    salt = b"\x10" * 16
    nonce = b"\x20" * 16
    ct = b"abc"
    header = mod._pack_header(salt, 1, nonce, ct)
    data = header + ct
    for trunc in [1, 5, 10]:
        with pytest.raises(mod.IntegrityError):
            mod._unpack_header(data[:trunc])


def test_secure_write_atomic_writes_and_handles_chmod_error(tmp_path: Path, monkeypatch):
    target = tmp_path / "vault.dat"
    # Force chmod to raise
    monkeypatch.setattr(mod.os, "chmod", mock.Mock(side_effect=OSError("perm error")))
    content = b"hello world"
    mod._secure_write_atomic(target, content)
    assert target.read_bytes() == content
    # Ensure no tmp file remains
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())


def test_read_all(tmp_path: Path):
    p = tmp_path / "file.bin"
    p.write_bytes(b"data")
    assert mod._read_all(p) == b"data"


def test_vault_initialize_add_get_remove_persist(tmp_path: Path, monkeypatch):
    path = tmp_path / "vault.dat"
    v = mod.Vault(path, autolock_seconds=0)
    assert not v.is_initialized()
    # Freeze time
    monkeypatch.setattr(mod.time, "time", lambda: 1700000000)
    v.initialize_new_vault("StrongPass!123")
    assert v.is_initialized()
    assert v.is_unlocked()
    assert v.list_services() == []
    # Add credentials
    v.add_credential("ServiceA", "userA", "passA")
    v.add_credential("serviceB", "userB", "passB")
    # Internal data should have timestamps
    assert v._data is not None
    assert v._data["credentials"]["ServiceA"]["updated_at"] == 1700000000
    # List sorted
    assert v.list_services() == ["ServiceA", "serviceB"]
    # Get
    item = v.get_credential("ServiceA")
    assert item == {"username": "userA", "password": "passA"}
    # Remove existing
    assert v.remove_credential("ServiceA") is True
    # Remove non-existing
    assert v.remove_credential("nope") is False
    # Empty service name
    with pytest.raises(mod.VaultError):
        v.add_credential("   ", "u", "p")
    # Lock and ensure operations fail
    v.lock()
    with pytest.raises(mod.VaultError):
        v.list_services()
    with pytest.raises(mod.VaultError):
        v.add_credential("X", "u", "p")
    with pytest.raises(mod.VaultError):
        v.get_credential("X")
    with pytest.raises(mod.VaultError):
        v.remove_credential("X")
    # Unlock new instance and check persistence
    v2 = mod.Vault(path, autolock_seconds=0)
    v2.unlock("StrongPass!123")
    assert v2.list_services() == ["serviceB"]
    assert v2.get_credential("serviceB") == {"username": "userB", "password": "passB"}


def test_unlock_wrong_password_raises_vault_error(tmp_path: Path):
    path = tmp_path / "vault.dat"
    v = mod.Vault(path, autolock_seconds=0)
    v.initialize_new_vault("Correct!Pass123")
    v.lock()
    with pytest.raises(mod.VaultError) as ei:
        v.unlock("WrongPassword!1")
    assert "Incorrect master password" in str(ei.value)


def test_unlock_integrity_errors_on_corruption(tmp_path: Path):
    path = tmp_path / "vault.dat"
    v = mod.Vault(path, autolock_seconds=0)
    v.initialize_new_vault("StrongPass!123")
    v.lock()
    raw = path.read_bytes()
    # Corrupt magic
    corrupted = b"XXXX" + raw[4:]
    path.write_bytes(corrupted)
    with pytest.raises(mod.IntegrityError):
        v.unlock("StrongPass!123")
    # Restore then truncate to cause length mismatch
    path.write_bytes(raw[:-1])
    with pytest.raises(mod.IntegrityError) as ei:
        v.unlock("StrongPass!123")
    assert "incorrect length" in str(ei.value)


def test_last_activity_and_lock_states(tmp_path: Path):
    path = tmp_path / "vault.dat"
    v = mod.Vault(path, autolock_seconds=1)
    v.initialize_new_vault("StrongPass!123")
    la1 = v.last_activity()
    assert la1 is not None
    time.sleep(0.02)
    v.touch()
    la2 = v.last_activity()
    assert la2 is not None and la2 >= la1
    v.lock()
    assert v.last_activity() is None


def test_auto_lock_triggers_with_callback(tmp_path: Path):
    path = tmp_path / "vault.dat"
    event = threading.Event()
    received = []

    def on_autolock(msg: str):
        received.append(msg)
        event.set()

    v = mod.Vault(path, autolock_seconds=0.05, on_autolock=on_autolock)
    v.initialize_new_vault("StrongPass!123")
    fired = event.wait(2.0)
    assert fired is True
    assert v.is_unlocked() is False
    assert received and "auto-locked" in received[0]


def test_require_unlocked_error_on_operations(tmp_path: Path):
    path = tmp_path / "vault.dat"
    v = mod.Vault(path, autolock_seconds=0)
    v.initialize_new_vault("StrongPass!123")
    v.lock()
    with pytest.raises(mod.VaultError):
        v.list_services()
    with pytest.raises(mod.VaultError):
        v.add_credential("svc", "u", "p")
    with pytest.raises(mod.VaultError):
        v.get_credential("svc")
    with pytest.raises(mod.VaultError):
        v.remove_credential("svc")


def test_cli_first_time_flow(tmp_path: Path, monkeypatch, capsys):
    vault_path = tmp_path / "cli_vault.dat"
    # Provide two getpass inputs for create and confirm
    pw_iter = iter(["StrongPass!123", "StrongPass!123"])
    monkeypatch.setattr(mod.getpass, "getpass", lambda prompt: next(pw_iter))
    # Commands: list then exit
    input_iter = iter(["list", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(input_iter))
    mod.run_cli(vault_path)
    out = capsys.readouterr().out
    assert "No vault found. First-time setup." in out
    assert "Vault created and unlocked." in out
    assert "No credentials stored." in out
    assert "Goodbye." in out


def test_cli_unlock_existing_wrong_then_correct(tmp_path: Path, monkeypatch, capsys):
    vault_path = tmp_path / "cli_vault2.dat"
    # Pre-create vault
    v = mod.Vault(vault_path, autolock_seconds=0)
    v.initialize_new_vault("Correct!1Pwd")
    v.lock()
    # getpass returns wrong then correct
    pw_iter = iter(["Wrong!1Pwd", "Correct!1Pwd"])
    monkeypatch.setattr(mod.getpass, "getpass", lambda prompt: next(pw_iter))
    # Commands: exit after unlock
    input_iter = iter(["exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(input_iter))
    mod.run_cli(vault_path)
    out = capsys.readouterr().out
    assert "Unlock failed:" in out
    assert "Attempts remaining:" in out
    assert "Vault unlocked." in out
    assert "Goodbye." in out