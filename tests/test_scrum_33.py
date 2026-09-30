import io
import json
import os
import stat
from pathlib import Path
from typing import Any, Dict

import pytest

import scrum_33


class DummyFile:
    def __init__(self):
        self.buffer = []
        self.closed = False
        self._fileno = 42
        self.flush_called = False
        self.write_calls = []

    def write(self, s: str):
        self.write_calls.append(s)
        self.buffer.append(s)
        return len(s)

    def flush(self):
        self.flush_called = True

    def fileno(self):
        return self._fileno

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def test_b64_roundtrip():
    data = b"\x00\x01\xab\xcdXYZ"
    enc = scrum_33._b64e(data)
    assert enc == data.hex()
    dec = scrum_33._b64d(enc)
    assert dec == data
    assert enc.islower()


def test_xor_bytes_basic_and_truncate():
    a = bytes([0x00, 0xFF, 0x55])
    b = bytes([0xFF, 0x00, 0xAA, 0x12, 0x34])
    res = scrum_33._xor_bytes(a, b)
    assert res == bytes([0xFF, 0xFF, 0xFF])
    # Truncates to min length
    assert len(res) == 3


def test_derive_keys_types_deterministic():
    secret_str = "mysecret"
    secret_bytes = b"mysecret"
    salt = b"salty-salt-123456"  # 16+ bytes okay
    enc1, mac1 = scrum_33._derive_keys(secret_str, salt, iterations=10_000)
    enc2, mac2 = scrum_33._derive_keys(secret_bytes, salt, iterations=10_000)
    assert enc1 == enc2 and mac1 == mac2
    assert len(enc1) == 32 and len(mac1) == 32

    # Different salt yields different keys
    enc3, mac3 = scrum_33._derive_keys(secret_str, b"another-salt-123", iterations=10_000)
    assert (enc1, mac1) != (enc3, mac3)


def test_keystream_length_and_nonce_validation():
    key = b"k" * 32
    nonce = b"n" * 24
    ks = scrum_33._keystream(key, nonce, 0)
    assert ks == b""

    ks = scrum_33._keystream(key, nonce, 64)
    assert len(ks) == 64
    assert ks != b"\x00" * 64

    with pytest.raises(ValueError, match="Nonce must be at least 16 bytes"):
        scrum_33._keystream(key, b"short", 16)


def test_compute_tag_deterministic():
    mac_key = b"m" * 32
    nonce = b"n" * 24
    ct = b"ciphertext"
    tag1 = scrum_33._compute_tag(mac_key, nonce, ct)
    tag2 = scrum_33._compute_tag(mac_key, nonce, ct)
    assert tag1 == tag2
    assert len(tag1) == 32


def test_encrypt_decrypt_roundtrip_and_record_structure():
    secret = "topsecret"
    plaintext = b'{"name":"Example","username":"user","password":"pass"}'
    record: Dict[str, Any] = scrum_33._encrypt_record(secret, plaintext)
    assert record["v"] == 1
    for k in ("salt", "nonce", "ct", "tag"):
        assert isinstance(record[k], str)
        assert len(record[k]) > 0

    # check sizes: salt=16 bytes->32 hex, nonce=24->48 hex, tag=32->64 hex
    assert len(record["salt"]) == 32
    assert len(record["nonce"]) == 48
    assert len(record["tag"]) == 64
    assert len(scrum_33._b64d(record["ct"])) == len(plaintext)

    decrypted = scrum_33._decrypt_record(secret, record)
    assert decrypted == plaintext


def test_decrypt_record_errors():
    secret = "secret"
    pt = b'{"name":"N","username":"U","password":"P"}'
    record = scrum_33._encrypt_record(secret, pt)

    # Wrong version
    bad_version = dict(record)
    bad_version["v"] = 2
    with pytest.raises(ValueError, match="Unsupported record version"):
        scrum_33._decrypt_record(secret, bad_version)

    # Corrupted encoding
    bad_enc = dict(record)
    bad_enc["salt"] = "zz"  # not hex
    with pytest.raises(ValueError, match="Corrupted record encoding"):
        scrum_33._decrypt_record(secret, bad_enc)

    # Integrity check fails
    bad_tag = dict(record)
    bad_tag["tag"] = "00" * 32
    with pytest.raises(ValueError, match="Integrity check failed"):
        scrum_33._decrypt_record(secret, bad_tag)

    # Wrong secret
    with pytest.raises(ValueError, match="Integrity check failed"):
        scrum_33._decrypt_record("wrong", record)


def test_is_blank_and_contains_null():
    assert scrum_33._is_blank(None) is True
    assert scrum_33._is_blank("") is True
    assert scrum_33._is_blank("  ") is True
    assert scrum_33._is_blank(" a ") is False
    assert scrum_33._is_blank(123) is False

    assert scrum_33._contains_null("nope") is False
    assert scrum_33._contains_null("bad\x00string") is True


def test_validate_name():
    with pytest.raises(ValueError, match="Name must be a string"):
        scrum_33._validate_name(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Name is required"):
        scrum_33._validate_name("")
    with pytest.raises(ValueError, match="Name cannot be empty"):
        scrum_33._validate_name("   ")
    with pytest.raises(ValueError, match="Name too long"):
        scrum_33._validate_name("a" * 256)
    with pytest.raises(ValueError, match="invalid characters"):
        scrum_33._validate_name("bad\x00name")
    # valid
    scrum_33._validate_name("  Valid Name  ")


def test_validate_username():
    with pytest.raises(ValueError, match="Username must be a string"):
        scrum_33._validate_username(3.14)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Username is required"):
        scrum_33._validate_username("")
    with pytest.raises(ValueError, match="Username cannot be empty"):
        scrum_33._validate_username("   ")
    with pytest.raises(ValueError, match="Username too long"):
        scrum_33._validate_username("u" * 256)
    with pytest.raises(ValueError, match="invalid characters"):
        scrum_33._validate_username("bad\x00user")
    # valid
    scrum_33._validate_username("user")


def test_validate_password():
    with pytest.raises(ValueError, match="Password must be a string"):
        scrum_33._validate_password(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Password must be a string"):
        scrum_33._validate_password(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Password is required"):
        scrum_33._validate_password("")
    with pytest.raises(ValueError, match="Password too long"):
        scrum_33._validate_password("p" * 4097)
    with pytest.raises(ValueError, match="invalid characters"):
        scrum_33._validate_password("bad\x00pass")
    # Whitespace-only is allowed
    scrum_33._validate_password("   ")
    scrum_33._validate_password("ok")


def test_validate_notes():
    # None is OK
    scrum_33._validate_notes(None)
    with pytest.raises(ValueError, match="Notes must be a string"):
        scrum_33._validate_notes(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Notes too long"):
        scrum_33._validate_notes("n" * 8193)
    with pytest.raises(ValueError, match="invalid characters"):
        scrum_33._validate_notes("bad\x00notes")
    # valid
    scrum_33._validate_notes("some notes")


def test_credential_repr_and_json_bytes():
    c = scrum_33.Credential(name=" Name ", username="ユーザー", password="päss", notes=None)
    c.validate()
    r = repr(c)
    assert "Name" not in r
    assert "ユーザー" not in r
    assert "päss" not in r

    data_bytes = c.to_minimal_json_bytes()
    data_str = data_bytes.decode("utf-8")
    # name is stripped
    assert '"name":"Name"' in data_str
    # ensure_ascii True, so non-ascii is escaped
    assert "\\u30e6" in data_str  # part of ユ
    # notes omitted when None
    assert '"notes"' not in data_str


def test_ensure_secure_dir_posix(monkeypatch, tmp_path):
    called = {"mkdir": False, "chmod": False}
    def fake_mkdir(self, parents=False, exist_ok=False):
        called["mkdir"] = True
        assert parents is True
        assert exist_ok is True

    monkeypatch.setattr(Path, "mkdir", fake_mkdir, raising=True)
    monkeypatch.setattr(os, "name", "posix", raising=False)

    def fake_chmod(path, mode):
        called["chmod"] = True
        assert mode == stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR

    monkeypatch.setattr(os, "chmod", fake_chmod)
    scrum_33._ensure_secure_dir(tmp_path)
    assert called["mkdir"] is True
    assert called["chmod"] is True


def test_ensure_secure_dir_nonposix(monkeypatch, tmp_path):
    called = {"chmod": False}
    monkeypatch.setattr(os, "name", "nt", raising=False)

    def fake_chmod(path, mode):
        called["chmod"] = True

    monkeypatch.setattr(os, "chmod", fake_chmod)
    # Should not raise and should not call chmod on non-posix
    scrum_33._ensure_secure_dir(tmp_path)
    assert called["chmod"] is False


def test_open_secure_append_flags_and_mode(monkeypatch, tmp_path):
    calls = {"open": None, "fdopen": None, "chmod": None}

    def fake_os_open(path, flags, mode):
        calls["open"] = (path, flags, mode)
        return 99

    def fake_fdopen(fd, mode, encoding=None, buffering=None):
        calls["fdopen"] = (fd, mode, encoding, buffering)
        return DummyFile()

    def fake_chmod(path, mode):
        calls["chmod"] = (path, mode)

    monkeypatch.setattr(os, "open", fake_os_open)
    monkeypatch.setattr(os, "fdopen", fake_fdopen)
    monkeypatch.setattr(os, "name", "posix", raising=False)
    monkeypatch.setattr(os, "chmod", fake_chmod)

    path = tmp_path / "file.jsonl"
    f = scrum_33._open_secure_append(path)
    assert calls["open"][0] == str(path)
    assert calls["open"][1] & os.O_APPEND
    assert calls["open"][1] & os.O_CREAT
    assert calls["open"][1] & os.O_WRONLY
    assert calls["open"][2] == stat.S_IRUSR | stat.S_IWUSR

    assert calls["fdopen"] == (99, "a", "utf-8", 1)
    assert calls["chmod"] == (path, stat.S_IRUSR | stat.S_IWUSR)
    f.close()
    assert f.closed is True


def test_credential_store_init_calls_ensure_secure_dir(monkeypatch, tmp_path):
    called = {"ensure": None}

    def fake_ensure(p):
        called["ensure"] = p

    monkeypatch.setattr(scrum_33, "_ensure_secure_dir", fake_ensure)
    store_path = tmp_path / "sub" / "creds.jsonl"
    store = scrum_33.CredentialStore(secret="s", storage_path=store_path)
    assert isinstance(store, scrum_33.CredentialStore)
    assert called["ensure"] == store_path.parent


def test_credential_store_add_credential_writes_encrypted_line_and_flush_fsync(monkeypatch):
    dummy = DummyFile()
    monkeypatch.setattr(scrum_33, "_open_secure_append", lambda path: dummy)
    fsync_calls = {"args": None}

    def fake_fsync(fd):
        fsync_calls["args"] = fd

    monkeypatch.setattr(os, "fsync", fake_fsync)

    store = scrum_33.CredentialStore(secret="supersecret", storage_path=Path("/tmp/creds.jsonl"))
    msg = store.add_credential(name=" Example ", username="user", password="pass", notes="note")
    assert msg == "Credential saved successfully."
    # One line written
    assert len(dummy.write_calls) == 1
    line = dummy.write_calls[0]
    assert line.endswith("\n")
    record = json.loads(line)
    assert set(record.keys()) == {"v", "salt", "nonce", "ct", "tag"}
    # Decrypt and verify plaintext
    pt = scrum_33._decrypt_record("supersecret", record)
    expected = scrum_33.Credential(name=" Example ", username="user", password="pass", notes="note").to_minimal_json_bytes()
    assert pt == expected
    assert dummy.flush_called is True
    assert fsync_calls["args"] == dummy.fileno()


def test_credential_store_add_credential_rejects_invalid_inputs_and_does_not_write(monkeypatch):
    called = {"open": False}
    def fake_open(path):
        called["open"] = True
        return DummyFile()

    monkeypatch.setattr(scrum_33, "_open_secure_append", fake_open)
    store = scrum_33.CredentialStore(secret="s", storage_path=Path("/tmp/creds.jsonl"))
    with pytest.raises(ValueError):
        store.add_credential(name="Valid", username="   ", password="pass")
    assert called["open"] is False


def test_credential_store_repr_does_not_leak_secret(tmp_path):
    store = scrum_33.CredentialStore(secret="topsecret", storage_path=tmp_path / "x.jsonl")
    r = repr(store)
    assert "topsecret" not in r
    assert "CredentialStore(" in r
    assert str(tmp_path / "x.jsonl") in r


def test_create_store_from_env_success_and_missing(monkeypatch, tmp_path):
    env_name = "CREDENTIAL_STORE_SECRET_TEST"
    # Missing or empty -> error
    monkeypatch.delenv(env_name, raising=False)
    with pytest.raises(ValueError, match=f"Missing secret in environment variable {env_name}"):
        scrum_33.create_store_from_env(env_var=env_name, storage_path=tmp_path / "f.jsonl")

    monkeypatch.setenv(env_name, "")
    with pytest.raises(ValueError):
        scrum_33.create_store_from_env(env_var=env_name, storage_path=tmp_path / "f.jsonl")

    # Success path
    monkeypatch.setenv(env_name, "envsecret")
    store = scrum_33.create_store_from_env(env_var=env_name, storage_path=tmp_path / "f.jsonl")
    assert isinstance(store, scrum_33.CredentialStore)
    # Verify secret propagated
    assert getattr(store, "_secret") == "envsecret"