import io
import json
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

import scrum_33 as m


def test_b64e_and_b64d_roundtrip_lowercase():
    data = b"\xff\x00\xab\xcd\x01\x23"
    enc = m._b64e(data)
    assert enc == data.hex()
    assert enc.islower()
    dec = m._b64d(enc)
    assert dec == data


def test_xor_bytes_min_length_behavior():
    a = b"\x01\x02\x03\x04"
    b = b"\x01\x02"
    x = m._xor_bytes(a, b)
    assert x == b"\x00\x00"
    assert len(x) == len(b)


def test_derive_keys_deterministic_and_separation():
    secret = "passphrase"
    salt = b"0123456789abcdef"
    k1, k2 = m._derive_keys(secret, salt, iterations=10)
    k1b, k2b = m._derive_keys(secret, salt, iterations=10)
    assert k1 == k1b and k2 == k2b
    assert k1 != k2
    # Different iterations produce different keys
    k1c, k2c = m._derive_keys(secret, salt, iterations=11)
    assert (k1, k2) != (k1c, k2c)


def test_keystream_length_and_counter_and_short_nonce_error():
    enc_key = b"\x00" * 32
    nonce = b"\x01" * 24
    s1 = m._keystream(enc_key, nonce, 33)
    s2 = m._keystream(enc_key, nonce, 64)
    assert len(s1) == 33
    assert len(s2) == 64
    assert s1 == s2[:33]
    with pytest.raises(ValueError, match="Nonce must be at least 16 bytes"):
        m._keystream(enc_key, b"\x00" * 15, 1)


def test_compute_tag_deterministic():
    mac_key = b"M" * 32
    nonce = b"N" * 24
    ct = b"\x10\x20\x30"
    tag1 = m._compute_tag(mac_key, nonce, ct, version=1)
    tag2 = m._compute_tag(mac_key, nonce, ct, version=1)
    assert tag1 == tag2
    tag3 = m._compute_tag(mac_key, nonce, ct, version=2)
    assert tag1 != tag3


@pytest.mark.parametrize("secret", ["s3cr3t", b"s3cr3t"])
def test_encrypt_decrypt_record_roundtrip_fast_keys(secret, monkeypatch):
    # Patch key derivation to avoid slow PBKDF2
    def fast_derive(s, salt, iterations=m.DEFAULT_ITERATIONS):
        return (b"E" * 32, b"M" * 32)

    monkeypatch.setattr(m, "_derive_keys", fast_derive)

    # Deterministic randomness
    def fake_token_bytes(n):
        return bytes([n]) * n

    monkeypatch.setattr(m.secrets, "token_bytes", fake_token_bytes)

    plaintext = json.dumps({"name": "site", "username": "user", "password": "pw"}).encode("utf-8")
    record = m._encrypt_record(secret, plaintext)
    assert set(record.keys()) == {"v", "salt", "nonce", "ct", "tag"}
    assert record["v"] == 1
    # Validate hex lengths
    assert len(record["salt"]) == 16 * 2
    assert len(record["nonce"]) == 24 * 2
    assert len(record["tag"]) == 32 * 2
    # Roundtrip
    out = m._decrypt_record(secret, record)
    assert out == plaintext


def test_decrypt_record_errors_fast_keys(monkeypatch):
    def fast_derive(s, salt, iterations=m.DEFAULT_ITERATIONS):
        return (b"E" * 32, b"M" * 32)

    monkeypatch.setattr(m, "_derive_keys", fast_derive)

    def fake_token_bytes(n):
        return bytes([n]) * n

    monkeypatch.setattr(m.secrets, "token_bytes", fake_token_bytes)

    secret = "sekrit"
    pt = b"{}"
    record = m._encrypt_record(secret, pt)

    # Integrity failure by modifying tag
    bad = dict(record)
    t = bad["tag"]
    flip = "0" if t[-1] != "0" else "1"
    bad["tag"] = t[:-1] + flip
    with pytest.raises(ValueError, match="Integrity check failed"):
        m._decrypt_record(secret, bad)

    # Unsupported version
    bad2 = dict(record)
    bad2["v"] = 2
    with pytest.raises(ValueError, match="Unsupported record version"):
        m._decrypt_record(secret, bad2)

    # Corrupted encoding
    bad3 = dict(record)
    bad3["tag"] = "zzzz"
    with pytest.raises(ValueError, match="Corrupted record encoding"):
        m._decrypt_record(secret, bad3)


def test_is_blank_behaviors():
    assert m._is_blank(None) is True
    assert m._is_blank("") is True
    assert m._is_blank("   ") is True
    assert m._is_blank("x") is False
    # Non-string non-None values should return False
    assert m._is_blank(123) is False
    assert m._is_blank([]) is False


def test_contains_null():
    assert m._contains_null("a\x00b") is True
    assert m._contains_null("abc") is False


def test_validate_name_errors():
    with pytest.raises(ValueError, match="Name is required"):
        m._validate_name(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Name must be a string"):
        m._validate_name(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Name cannot be empty"):
        m._validate_name("   ")
    with pytest.raises(ValueError, match="Name too long"):
        m._validate_name("a" * 256)
    with pytest.raises(ValueError, match="invalid characters"):
        m._validate_name("bad\x00name")
    # Valid
    m._validate_name(" ok ")


def test_validate_username_errors():
    with pytest.raises(ValueError, match="Username is required"):
        m._validate_username(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Username must be a string"):
        m._validate_username(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Username cannot be empty"):
        m._validate_username("   ")
    with pytest.raises(ValueError, match="Username too long"):
        m._validate_username("u" * 256)
    with pytest.raises(ValueError, match="invalid characters"):
        m._validate_username("bad\x00user")
    # Valid
    m._validate_username(" user ")


def test_validate_password_errors_and_whitespace_ok():
    with pytest.raises(ValueError, match="Password must be a string"):
        m._validate_password(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Password must be a string"):
        m._validate_password(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Password is required"):
        m._validate_password("")
    with pytest.raises(ValueError, match="Password too long"):
        m._validate_password("p" * 4097)
    with pytest.raises(ValueError, match="invalid characters"):
        m._validate_password("a\x00b")
    # Whitespace allowed and not treated as empty
    m._validate_password("   ")
    m._validate_password(" ok ")


def test_validate_notes_cases():
    # None ok
    m._validate_notes(None)
    with pytest.raises(ValueError, match="Notes must be a string"):
        m._validate_notes(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Notes too long"):
        m._validate_notes("n" * 8193)
    with pytest.raises(ValueError, match="invalid characters"):
        m._validate_notes("note\x00s")
    # Max length ok
    m._validate_notes("n" * 8192)


def test_credential_repr_hides_sensitive_and_json_bytes_handling():
    cred = m.Credential(name="  My Site  ", username="user", password="pass", notes=None)
    r = repr(cred)
    assert "My Site" not in r
    assert "user" not in r
    assert "pass" not in r

    # Minimal JSON: name trimmed, notes omitted if None
    data = json.loads(cred.to_minimal_json_bytes().decode("utf-8"))
    assert data == {"name": "My Site", "username": "user", "password": "pass"}

    # When notes provided, included; ensure ensure_ascii escapes non-ascii
    cred2 = m.Credential(name="Name", username="u", password="p", notes="café")
    data_bytes = cred2.to_minimal_json_bytes()
    assert b"\\u00e9" in data_bytes  # 'é' escaped
    assert json.loads(data_bytes.decode("utf-8"))["notes"] == "café"


def test_ensure_secure_dir_calls_mkdir_and_chmod_on_posix(monkeypatch):
    fake_path = MagicMock()
    fake_path.mkdir = MagicMock()
    calls = {}

    def fake_chmod(path, mode):
        calls["chmod"] = (path, mode)

    monkeypatch.setattr(os, "name", "posix", raising=False)
    monkeypatch.setattr(os, "chmod", fake_chmod)

    m._ensure_secure_dir(fake_path)

    fake_path.mkdir.assert_called_once_with(parents=True, exist_ok=True)
    assert calls["chmod"][0] == fake_path
    assert calls["chmod"][1] == stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR


def test_open_secure_append_opens_with_secure_flags_and_chmod_on_posix(monkeypatch, tmp_path):
    test_path = tmp_path / "creds.jsonl"
    open_calls = {}

    def fake_os_open(path, flags, mode):
        open_calls["args"] = (path, flags, mode)
        return 123

    fdopen_file = MagicMock()
    fdopen_file.__enter__.return_value = fdopen_file
    fdopen_file.__exit__.return_value = False
    fdopen_calls = {}

    def fake_fdopen(fd, mode, encoding=None, buffering=None):
        fdopen_calls["args"] = (fd, mode, encoding, buffering)
        return fdopen_file

    chmod_calls = {}

    def fake_chmod(path, mode):
        chmod_calls["args"] = (path, mode)

    monkeypatch.setattr(os, "open", fake_os_open)
    monkeypatch.setattr(os, "fdopen", fake_fdopen)
    monkeypatch.setattr(os, "name", "posix", raising=False)
    monkeypatch.setattr(os, "chmod", fake_chmod)

    f = m._open_secure_append(test_path)
    assert f is fdopen_file

    path_str, flags, mode = open_calls["args"]
    assert Path(path_str) == test_path
    expected_flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    assert flags == expected_flags
    assert mode == stat.S_IRUSR | stat.S_IWUSR

    fd, mode_s, enc, buf = fdopen_calls["args"]
    assert fd == 123
    assert mode_s == "a"
    assert enc == "utf-8"
    assert buf == 1

    assert chmod_calls["args"] == (test_path, stat.S_IRUSR | stat.S_IWUSR)


def test_credential_store_init_and_repr_and_iterations(monkeypatch, tmp_path):
    # Ensure directory creation is called
    called = {"dir": None}

    def fake_ensure_dir(p):
        called["dir"] = p

    monkeypatch.setattr(m, "_ensure_secure_dir", fake_ensure_dir)
    p = tmp_path / "store.jsonl"
    store = m.CredentialStore(secret="sekrit", storage_path=p, iterations=12345)
    assert called["dir"] == p.parent
    assert store._iterations == 12345
    rep = repr(store)
    assert "sekrit" not in rep
    assert str(p) in rep

    with pytest.raises(TypeError, match="Secret must be str or bytes"):
        m.CredentialStore(secret=123, storage_path=p)  # type: ignore[arg-type]


def test_add_credential_writes_encrypted_jsonl_and_flush_fsync(monkeypatch, tmp_path):
    # Patch key derivation to avoid slow PBKDF2
    def fast_derive(s, salt, iterations=m.DEFAULT_ITERATIONS):
        return (b"E" * 32, b"M" * 32)

    monkeypatch.setattr(m, "_derive_keys", fast_derive)

    # Deterministic randomness for salt and nonce
    def fake_token_bytes(n):
        return bytes([n]) * n

    monkeypatch.setattr(m.secrets, "token_bytes", fake_token_bytes)

    # Mock the secure append to capture writes
    written = []

    file_mock = MagicMock()
    file_mock.__enter__.return_value = file_mock
    file_mock.__exit__.return_value = False

    def write_side_effect(s):
        written.append(s)
        return len(s)

    file_mock.write.side_effect = write_side_effect
    file_mock.flush.return_value = None
    file_mock.fileno.return_value = 99

    monkeypatch.setattr(m, "_open_secure_append", lambda path: file_mock)
    fsync_mock = MagicMock()
    monkeypatch.setattr(os, "fsync", fsync_mock)

    store = m.CredentialStore(secret="master", storage_path=tmp_path / "creds.jsonl")
    msg = store.add_credential(name="  Example  ", username="user", password=" pa ss ", notes=None)
    assert msg == "Credential saved successfully."

    # One line written, newline terminated
    content = "".join(written)
    assert content.endswith("\n")

    record = json.loads(content.strip())
    assert set(record.keys()) == {"v", "salt", "nonce", "ct", "tag"}
    # Decrypt to inspect plaintext
    plaintext = m._decrypt_record("master", record)
    data = json.loads(plaintext.decode("utf-8"))
    assert data["name"] == "Example"  # trimmed
    assert data["username"] == "user"
    assert data["password"] == " pa ss "
    assert "notes" not in data

    file_mock.flush.assert_called_once()
    fsync_mock.assert_called_once_with(99)


def test_add_credential_flush_or_fsync_errors_ignored(monkeypatch, tmp_path):
    # Patch derivation fast
    def fast_derive(s, salt, iterations=m.DEFAULT_ITERATIONS):
        return (b"E" * 32, b"M" * 32)

    monkeypatch.setattr(m, "_derive_keys", fast_derive)

    def fake_token_bytes(n):
        return bytes([n]) * n

    monkeypatch.setattr(m.secrets, "token_bytes", fake_token_bytes)

    # Case 1: flush raises
    file_mock1 = MagicMock()
    file_mock1.__enter__.return_value = file_mock1
    file_mock1.__exit__.return_value = False
    file_mock1.write.return_value = None
    file_mock1.flush.side_effect = OSError("fail flush")
    file_mock1.fileno.return_value = 123
    fsync_mock = MagicMock()
    monkeypatch.setattr(m, "_open_secure_append", lambda path: file_mock1)
    monkeypatch.setattr(os, "fsync", fsync_mock)

    store = m.CredentialStore(secret="s", storage_path=tmp_path / "a.jsonl")
    assert store.add_credential("n", "u", "p") == "Credential saved successfully."
    fsync_mock.assert_not_called()

    # Case 2: fsync raises
    file_mock2 = MagicMock()
    file_mock2.__enter__.return_value = file_mock2
    file_mock2.__exit__.return_value = False
    file_mock2.write.return_value = None
    file_mock2.flush.return_value = None
    file_mock2.fileno.return_value = 456
    monkeypatch.setattr(m, "_open_secure_append", lambda path: file_mock2)
    fsync_mock2 = MagicMock(side_effect=OSError("fail fsync"))
    monkeypatch.setattr(os, "fsync", fsync_mock2)

    assert store.add_credential("n2", "u2", "p2") == "Credential saved successfully."
    file_mock2.flush.assert_called_once()
    fsync_mock2.assert_called_once_with(456)


def test_create_store_from_env_success_and_missing(monkeypatch, tmp_path):
    # Missing env var
    var = "TEST_SECRET_ENV_MISSING"
    if var in os.environ:
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ValueError, match=var):
        m.create_store_from_env(env_var=var, storage_path=tmp_path / "x.jsonl")

    # Success
    var2 = "TEST_SECRET_ENV_PRESENT"
    monkeypatch.setenv(var2, "envsecret")
    # Avoid touching filesystem on init
    monkeypatch.setattr(m, "_ensure_secure_dir", lambda p: None)
    store = m.create_store_from_env(env_var=var2, storage_path=tmp_path / "y.jsonl")
    assert isinstance(store, m.CredentialStore)
    assert store._secret == "envsecret"
    assert store._storage_path == tmp_path / "y.jsonl"
    assert "envsecret" not in repr(store)