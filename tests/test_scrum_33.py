import json
import os
import stat
import builtins
import base64
from unittest import mock

import pytest

import scrum_33


def test_b64_roundtrip():
    data = b"\x00\x01hello world\xff"
    s = scrum_33._b64e(data)
    assert isinstance(s, str)
    out = scrum_33._b64d(s)
    assert out == data


def test_xor_bytes_symmetry_and_truncation():
    a = b"abcdef"
    b = b"\x01\x02\x03\x04\x05"
    x = scrum_33._xor_bytes(a, b)
    # Truncated to min length (5)
    assert len(x) == 5
    # Symmetry
    back = scrum_33._xor_bytes(x, b)
    assert back == a[:5]


def test_derive_keys_consistency_and_variation():
    secret = "mysecret"
    salt1 = b"A" * 16
    salt2 = b"B" * 16
    enc1, mac1 = scrum_33._derive_keys(secret, salt1)
    enc1_again, mac1_again = scrum_33._derive_keys(secret, salt1)
    assert enc1 == enc1_again and mac1 == mac1_again

    enc2, mac2 = scrum_33._derive_keys(secret, salt2)
    assert (enc1, mac1) != (enc2, mac2)

    # Different secret changes keys
    enc3, mac3 = scrum_33._derive_keys("other", salt1)
    assert (enc1, mac1) != (enc3, mac3)

    # Byte and str inputs behave
    enc4, mac4 = scrum_33._derive_keys(b"mysecret", salt1)
    assert (enc1, mac1) == (enc4, mac4)

    # Different iterations produce different keys
    enc5, mac5 = scrum_33._derive_keys(secret, salt1, iterations=1)
    assert (enc1, mac1) != (enc5, mac5)


def test_keystream_length_and_nonce_validation():
    enc_key = b"\x00" * 32
    nonce = b"\x11" * 24
    ks = scrum_33._keystream(enc_key, nonce, 100)
    assert isinstance(ks, bytes)
    assert len(ks) == 100

    with pytest.raises(ValueError, match="Nonce must be at least 16 bytes"):
        scrum_33._keystream(enc_key, b"\x00" * 8, 10)


def test_compute_tag_changes_on_ciphertext_modification():
    mac_key = b"\x01" * 32
    nonce = b"\x02" * 24
    ct = b"ciphertext"
    tag1 = scrum_33._compute_tag(mac_key, nonce, ct)
    tag2 = scrum_33._compute_tag(mac_key, nonce, ct + b"x")
    assert tag1 != tag2

    # Changing nonce changes tag
    tag3 = scrum_33._compute_tag(mac_key, nonce + b"\x00", ct)
    assert tag1 != tag3


def test_encrypt_decrypt_roundtrip():
    secret = "supersecret"
    payload = {"name": "Example", "username": "user", "password": "Pa$$", "notes": "n"}
    plaintext = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")

    record = scrum_33._encrypt_record(secret, plaintext)
    assert set(record.keys()) == {"v", "salt", "nonce", "ct", "tag"}
    # Base64 decodable fields
    for k in ("salt", "nonce", "ct", "tag"):
        base64.b64decode(record[k].encode("ascii"))

    out = scrum_33._decrypt_record(secret, record)
    assert out == plaintext


def test_decrypt_integrity_failure_on_tampered_ciphertext():
    secret = "anothersecret"
    plaintext = b'{"name":"N","username":"U","password":"P"}'
    record = scrum_33._encrypt_record(secret, plaintext)
    ct_bytes = base64.b64decode(record["ct"].encode("ascii"))
    # Flip a bit
    tampered = bytes([ct_bytes[0] ^ 0x01]) + ct_bytes[1:]
    record_bad = dict(record)
    record_bad["ct"] = base64.b64encode(tampered).decode("ascii")
    with pytest.raises(ValueError, match="Integrity check failed"):
        scrum_33._decrypt_record(secret, record_bad)


def test_decrypt_invalid_version_and_corrupted_encoding():
    secret = "s"
    plaintext = b'{"name":"x","username":"y","password":"z"}'
    record = scrum_33._encrypt_record(secret, plaintext)

    bad_version = dict(record)
    bad_version["v"] = 2
    with pytest.raises(ValueError, match="Unsupported record version"):
        scrum_33._decrypt_record(secret, bad_version)

    bad_encoding = dict(record)
    bad_encoding["salt"] = "not_base64!!*"
    with pytest.raises(ValueError, match="Corrupted record encoding"):
        scrum_33._decrypt_record(secret, bad_encoding)


def test_ensure_secure_dir_creates_and_chmod_called(monkeypatch, tmp_path):
    target_dir = tmp_path / "store_dir"
    chmod_calls = []

    def fake_chmod(path, mode):
        chmod_calls.append((str(path), mode))

    monkeypatch.setattr(os, "name", "posix", raising=False)
    monkeypatch.setattr(os, "chmod", fake_chmod)
    scrum_33._ensure_secure_dir(target_dir)
    assert target_dir.exists() and target_dir.is_dir()
    assert chmod_calls, "chmod should be called on posix"
    # mode 0o700
    assert chmod_calls[0][1] == (stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


def test_open_secure_append_actual_write_and_permissions(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "name", "posix", raising=False)
    chmod_calls = []
    monkeypatch.setattr(os, "chmod", lambda path, mode: chmod_calls.append((str(path), mode)))
    file_path = tmp_path / "file.txt"
    with scrum_33._open_secure_append(file_path) as f:
        f.write("hello\n")
    # File exists with content
    with open(file_path, encoding="utf-8") as rf:
        assert rf.read() == "hello\n"
    # File chmod to 0o600 attempted
    assert chmod_calls
    assert chmod_calls[-1][1] == (stat.S_IRUSR | stat.S_IWUSR)


def test_is_blank_and_contains_null():
    assert scrum_33._is_blank(None) is True
    assert scrum_33._is_blank("") is True
    assert scrum_33._is_blank("  ") is True
    assert scrum_33._is_blank("x") is False

    assert scrum_33._contains_null("a\x00b") is True
    assert scrum_33._contains_null("abc") is False


@pytest.mark.parametrize(
    "name,ok",
    [
        ("ValidName", True),
        (" " * 5 + "abc", True),
        ("\x00bad", False),
        ("", False),
        ("   ", False),
        (123, False),
        ("x" * 255, True),
        ("x" * 256, False),
    ],
)
def test_validate_name(name, ok):
    if ok:
        scrum_33._validate_name(name)  # type: ignore[arg-type]
    else:
        with pytest.raises(ValueError):
            scrum_33._validate_name(name)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "username,ok",
    [
        ("user", True),
        (" user ", True),
        ("\x00bad", False),
        ("", False),
        ("   ", False),
        ([], False),
        ("x" * 255, True),
        ("x" * 256, False),
    ],
)
def test_validate_username(username, ok):
    if ok:
        scrum_33._validate_username(username)  # type: ignore[arg-type]
    else:
        with pytest.raises(ValueError):
            scrum_33._validate_username(username)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "password,ok",
    [
        ("p", True),
        (" " * 5, True),
        ("\x00bad", False),
        ("", False),
        (None, False),
        (b"bytes", False),
        ("x" * 4096, True),
        ("x" * 4097, False),
    ],
)
def test_validate_password(password, ok):
    if ok:
        scrum_33._validate_password(password)  # type: ignore[arg-type]
    else:
        with pytest.raises(ValueError):
            scrum_33._validate_password(password)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "notes,ok",
    [
        (None, True),
        ("", True),
        ("note", True),
        ("\x00bad", False),
        (b"bytes", False),
        ("x" * 8192, True),
        ("x" * 8193, False),
    ],
)
def test_validate_notes(notes, ok):
    if ok:
        scrum_33._validate_notes(notes)  # type: ignore[arg-type]
    else:
        with pytest.raises(ValueError):
            scrum_33._validate_notes(notes)  # type: ignore[arg-type]


def test_credential_repr_and_minimal_json_notes_optional():
    cred = scrum_33.Credential(name="Site", username="alice", password="secret")
    # repr should not include fields
    r = repr(cred)
    assert "alice" not in r and "secret" not in r and "Site" not in r
    # to_minimal_json_bytes excludes notes key if None
    data = json.loads(cred.to_minimal_json_bytes())
    assert "notes" not in data
    assert data["name"] == "Site"
    assert data["username"] == "alice"
    assert data["password"] == "secret"

    cred2 = scrum_33.Credential(name="Site", username="alice", password="secret", notes="N")
    data2 = json.loads(cred2.to_minimal_json_bytes())
    assert data2["notes"] == "N"


def test_credential_validate_calls_all():
    # Valid case
    c = scrum_33.Credential(name="X", username="Y", password="Z", notes=None)
    c.validate()  # Should not raise
    # Invalid cases
    c_bad = scrum_33.Credential(name="", username="Y", password="Z")
    with pytest.raises(ValueError):
        c_bad.validate()


def test_credential_store_init_and_repr(monkeypatch, tmp_path):
    # Ensure secure dir called in init
    called = {}

    def fake_ensure_secure_dir(p):
        called["path"] = p

    monkeypatch.setattr(scrum_33, "_ensure_secure_dir", fake_ensure_secure_dir)
    storage_path = tmp_path / "dir" / "file.jsonl"
    cs = scrum_33.CredentialStore(secret=b"xyz", storage_path=storage_path)
    assert called["path"] == storage_path.parent
    # repr shows only storage path
    r = repr(cs)
    assert "storage_path=" in r
    assert "xyz" not in r

    with pytest.raises(TypeError):
        scrum_33.CredentialStore(secret=object(), storage_path=storage_path)  # type: ignore[arg-type]


def test_credential_store_add_credential_writes_to_file_and_decrypt(tmp_path):
    storage_path = tmp_path / "store.jsonl"
    secret = "topsecret"
    store = scrum_33.CredentialStore(secret=secret, storage_path=storage_path)
    msg = store.add_credential(name="Example", username="alice", password="passw0rd", notes="hello")
    assert msg == "Credential saved successfully."

    # One line written
    content = storage_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(content) == 1
    line = content[0]
    # Should not contain plaintext sensitive fields
    assert "alice" not in line
    assert "passw0rd" not in line
    assert "hello" not in line
    assert '"username"' not in line
    assert '"password"' not in line
    assert '"notes"' not in line

    record = json.loads(line)
    # Decrypt and verify plaintext
    pt = scrum_33._decrypt_record(secret, record)
    expected_plain = scrum_33.Credential(name="Example", username="alice", password="passw0rd", notes="hello").to_minimal_json_bytes()
    assert pt == expected_plain


def test_credential_store_add_credential_uses_fsync_and_handles_exception(monkeypatch):
    secret = "s3cr3t"
    store = scrum_33.CredentialStore(secret=secret, storage_path="/dev/null" if os.name != "nt" else "NUL")

    m = mock.mock_open()
    handle = m.return_value.__enter__.return_value
    # Augment with flush and fileno for fsync
    handle.flush = mock.MagicMock()
    handle.fileno = mock.MagicMock(return_value=42)
    monkeypatch.setattr(scrum_33, "_open_secure_append", m)
    monkeypatch.setattr(os, "fsync", mock.Mock(side_effect=OSError("no fsync")))
    msg = store.add_credential(name="A", username="B", password="C")
    assert msg == "Credential saved successfully."
    # Write called once with json line
    assert handle.write.call_count == 1
    written = handle.write.call_args[0][0]
    assert written.endswith("\n")
    # No sensitive fields
    assert '"username"' not in written and '"password"' not in written
    assert "A" not in written and "B" not in written and "C" not in written
    # Flush called
    handle.flush.assert_called_once()


@pytest.mark.parametrize(
    "args",
    [
        {"name": "", "username": "u", "password": "p"},
        {"name": "n", "username": "", "password": "p"},
        {"name": "n", "username": "u", "password": ""},
        {"name": "n", "username": "u", "password": "p", "notes": "\x00bad"},
    ],
)
def test_credential_store_add_credential_invalid_inputs_raise(tmp_path, args):
    store = scrum_33.CredentialStore(secret="k", storage_path=tmp_path / "x.jsonl")
    with pytest.raises(ValueError):
        store.add_credential(**args)  # type: ignore[arg-type]


def test_create_store_from_env(monkeypatch, tmp_path):
    monkeypatch.delenv("CREDENTIAL_STORE_SECRET", raising=False)
    with pytest.raises(ValueError, match="Missing secret"):
        scrum_33.create_store_from_env()

    monkeypatch.setenv("CREDENTIAL_STORE_SECRET", "envsecret")
    st = scrum_33.create_store_from_env(storage_path=tmp_path / "s.jsonl")
    assert isinstance(st, scrum_33.CredentialStore)

    # Custom env var name
    monkeypatch.setenv("MY_SECRET", "abc")
    st2 = scrum_33.create_store_from_env(env_var="MY_SECRET", storage_path=tmp_path / "t.jsonl")
    assert isinstance(st2, scrum_33.CredentialStore)