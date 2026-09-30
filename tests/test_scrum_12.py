import json
import re
import socket
import threading
import time
from itertools import count

import http.client
import pytest

import scrum_12


@pytest.fixture
def server():
    with scrum_12._TODOS_LOCK:
        scrum_12._TODOS_DB.clear()
        scrum_12._ID_COUNTER = count(start=1)
    srv = scrum_12.ThreadingHTTPServer(("127.0.0.1", 0), scrum_12.TodoAPIHandler)
    host, port = srv.server_address
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    # Wait briefly to ensure server is accepting connections
    for _ in range(10):
        try:
            conn = http.client.HTTPConnection(host, port, timeout=1)
            conn.connect()
            conn.close()
            break
        except Exception:
            time.sleep(0.01)
    yield host, port
    srv.shutdown()
    srv.server_close()
    t.join(timeout=2)


def http_post_json(host, port, path, payload, headers=None):
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        body = json.dumps(payload).encode("utf-8")
        hdrs = {"Content-Type": "application/json"}
        if headers:
            hdrs.update(headers)
        conn.request("POST", path, body=body, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, dict(resp.getheaders()), json.loads(data.decode("utf-8"))
    finally:
        conn.close()


def send_raw_request(host, port, request_bytes):
    s = socket.create_connection((host, port), timeout=5)
    try:
        s.sendall(request_bytes)
        s.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
    finally:
        s.close()

    # Parse HTTP response
    head, _, body = raw.partition(b"\r\n\r\n")
    head_lines = head.split(b"\r\n")
    status_line = head_lines[0].decode("iso-8859-1", errors="replace")
    parts = status_line.split()
    status = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None

    headers = {}
    for line in head_lines[1:]:
        if b":" in line:
            k, v = line.split(b":", 1)
            headers[k.decode("iso-8859-1").strip()] = v.decode("iso-8859-1").strip()

    content_length = headers.get("Content-Length")
    if content_length is not None:
        try:
            expected_len = int(content_length)
            # Body may be longer if server keeps connection open; truncate to expected length
            body = body[:expected_len]
        except ValueError:
            pass

    return status, headers, body


def test_normalize_content_type():
    assert scrum_12._normalize_content_type(None) is None
    assert scrum_12._normalize_content_type("") is None
    assert scrum_12._normalize_content_type("   ") is None
    assert scrum_12._normalize_content_type("application/json") == "application/json"
    assert scrum_12._normalize_content_type("Application/JSON; charset=UTF-8") == "application/json"
    assert scrum_12._normalize_content_type("text/plain; charset=utf-8") == "text/plain"


@pytest.mark.parametrize(
    "raw,ok,norm,err_contains",
    [
        (None, True, None, None),
        (123, False, None, "must be a string"),
        ("", False, None, "cannot be empty"),
        ("   ", False, None, "cannot be empty"),
        ("2020-02-29", True, "2020-02-29", None),
        ("2020-02-30", False, None, "Invalid dueDate format"),
        ("2020-01-01T00:00:00Z", True, "2020-01-01T00:00:00Z", None),
        ("2020-01-01T00:00:00+00:00", True, "2020-01-01T00:00:00Z", None),
        ("2020-01-01T12:34:56+02:00", True, "2020-01-01T12:34:56+02:00", None),
        ("2020-01-01T12:34:56", True, "2020-01-01T12:34:56", None),
    ],
)
def test_parse_iso_due_date(raw, ok, norm, err_contains):
    got_ok, got_norm, got_err = scrum_12._parse_iso_due_date(raw)
    assert got_ok == ok
    assert got_norm == norm
    if err_contains:
        assert got_err is not None and err_contains in got_err
    else:
        assert got_err is None


def test_validate_todo_payload_basic_and_errors():
    valid, errors, normalized = scrum_12._validate_todo_payload({"title": "  Hello  "})
    assert valid is True
    assert errors == {}
    assert normalized["title"] == "Hello"
    assert "description" not in normalized
    assert "dueDate" not in normalized

    valid, errors, normalized = scrum_12._validate_todo_payload({"title": None})
    assert valid is False
    assert "title" in errors

    valid, errors, normalized = scrum_12._validate_todo_payload({"title": ""})
    assert valid is False
    assert errors.get("title") == "title cannot be empty"

    valid, errors, normalized = scrum_12._validate_todo_payload({"title": 123})
    assert valid is False
    assert errors.get("title") == "title must be a string"

    # description handling
    valid, errors, normalized = scrum_12._validate_todo_payload({"title": "x", "description": None})
    assert valid is True
    assert normalized["description"] is None

    valid, errors, normalized = scrum_12._validate_todo_payload({"title": "x", "description": 123})
    assert valid is False
    assert errors.get("description") == "description must be a string"

    # dueDate None
    valid, errors, normalized = scrum_12._validate_todo_payload({"title": "x", "dueDate": None})
    assert valid is True
    assert "dueDate" in normalized and normalized["dueDate"] is None

    # dueDate invalid
    valid, errors, normalized = scrum_12._validate_todo_payload({"title": "x", "dueDate": {}})
    assert valid is False
    assert "dueDate" in errors


def test_build_error_payload():
    err = scrum_12._build_error_payload("code", "message", {"foo": "bar"})
    assert "error" in err
    assert err["error"]["code"] == "code"
    assert err["error"]["message"] == "message"
    assert err["error"]["details"] == {"foo": "bar"}


def test_post_todo_minimal_success(server):
    host, port = server
    status, headers, body = http_post_json(host, port, "/todos", {"title": "  Write tests  "})
    assert status == 201
    assert "Location" in headers
    location = headers["Location"]
    assert location.startswith(f"http://{host}:{port}/todos/")
    assert isinstance(body["id"], int)
    assert body["title"] == "Write tests"
    assert body["status"] == "pending"
    assert "createdAt" in body and "updatedAt" in body
    assert body["createdAt"] == body["updatedAt"]
    # Timestamp is ISO with Z
    assert body["createdAt"].endswith("Z")
    # Parseable datetime when replacing Z with +00:00
    ts = body["createdAt"].replace("Z", "+00:00")
    assert re.match(r"^\d{4}-\d{2}-\d{2}T", ts)
    # Location ends with the id
    assert location.endswith(f"/todos/{body['id']}")


def test_post_todo_with_optional_fields(server):
    host, port = server
    payload = {
        "title": "Item",
        "description": "desc",
        "dueDate": "2024-01-02",
    }
    status, headers, body = http_post_json(host, port, "/todos", payload)
    assert status == 201
    assert body["title"] == "Item"
    assert body["description"] == "desc"
    assert body["dueDate"] == "2024-01-02"


def test_post_todo_due_date_datetime_variants(server):
    host, port = server
    # UTC Z normalized
    status, headers, body = http_post_json(host, port, "/todos", {"title": "a", "dueDate": "2020-01-01T00:00:00Z"})
    assert status == 201
    assert body["dueDate"] == "2020-01-01T00:00:00Z"
    # UTC +00:00 normalized to Z
    status, headers, body = http_post_json(
        host, port, "/todos", {"title": "b", "dueDate": "2020-01-01T00:00:00+00:00"}
    )
    assert status == 201
    assert body["dueDate"].endswith("Z")
    # Non-UTC offset preserved
    status, headers, body = http_post_json(
        host, port, "/todos", {"title": "c", "dueDate": "2020-01-01T12:34:56+02:00"}
    )
    assert status == 201
    assert body["dueDate"].endswith("+02:00")


def test_post_todos_trailing_slash(server):
    host, port = server
    status, headers, body = http_post_json(host, port, "/todos/", {"title": "Trailing"})
    assert status == 201
    assert body["title"] == "Trailing"


def test_not_found_path(server):
    host, port = server
    status, headers, body = http_post_json(host, port, "/nope", {"title": "x"})
    assert status == 404
    assert body["error"]["code"] == "not_found"


def test_unsupported_media_type_no_content_type(server):
    host, port = server
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("POST", "/todos", body=b"{}", headers={})
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 415
        assert data["error"]["code"] == "unsupported_media_type"
        assert "details" in data["error"]
        assert "contentType" in data["error"]["details"]
        assert data["error"]["details"]["contentType"] is None
    finally:
        conn.close()


def test_unsupported_media_type_wrong_type(server):
    host, port = server
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        headers = {"Content-Type": "text/plain"}
        conn.request("POST", "/todos", body=b"{}", headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 415
        assert data["error"]["code"] == "unsupported_media_type"
    finally:
        conn.close()


def test_accepts_application_json_with_charset(server):
    host, port = server
    status, headers, body = http_post_json(
        host, port, "/todos", {"title": "ok"}, headers={"Content-Type": "Application/JSON; charset=UTF-8"}
    )
    assert status == 201
    assert body["title"] == "ok"


def test_missing_content_length_header(server):
    host, port = server
    req = b"POST /todos HTTP/1.0\r\nContent-Type: application/json\r\n\r\n"
    status, headers, body = send_raw_request(host, port, req)
    assert status == 400
    data = json.loads(body.decode("utf-8"))
    assert data["error"]["code"] == "invalid_request"
    assert data["error"]["message"] == "Request body is required."


def test_invalid_content_length_header(server):
    host, port = server
    req = (
        b"POST /todos HTTP/1.0\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: abc\r\n"
        b"\r\n"
    )
    status, headers, body = send_raw_request(host, port, req)
    assert status == 400
    data = json.loads(body.decode("utf-8"))
    assert data["error"]["code"] == "invalid_request"
    assert data["error"]["message"] == "Invalid Content-Length header."


def test_empty_request_body(server):
    host, port = server
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("POST", "/todos", body=b"", headers={"Content-Type": "application/json", "Content-Length": "0"})
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 400
        assert data["error"]["code"] == "invalid_request"
        assert data["error"]["message"] == "Request body is empty."
    finally:
        conn.close()


def test_malformed_json(server):
    host, port = server
    bad_json = b'{"title": "abc",}'
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("POST", "/todos", body=bad_json, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 400
        assert data["error"]["code"] == "invalid_json"
        assert "details" in data["error"] and "message" in data["error"]["details"]
    finally:
        conn.close()


@pytest.mark.parametrize(
    "payload,expected_field,expected_message",
    [
        ({}, "title", "Missing required field: title"),
        ({"title": ""}, "title", "title cannot be empty"),
        ({"title": 123}, "title", "title must be a string"),
        ({"title": "x", "description": 123}, "description", "description must be a string"),
        ({"title": "x", "dueDate": 123}, "dueDate", "dueDate must be a string"),
        ({"title": "x", "dueDate": ""}, "dueDate", "cannot be empty"),
        ({"title": "x", "dueDate": "not-a-date"}, "dueDate", "Invalid dueDate format"),
    ],
)
def test_validation_errors_via_http(server, payload, expected_field, expected_message):
    host, port = server
    status, headers, body = http_post_json(host, port, "/todos", payload)
    assert status == 400
    assert body["error"]["code"] == "validation_error"
    assert expected_field in body["error"]["details"]
    assert expected_message in body["error"]["details"][expected_field]


def test_location_header_without_host_header(server):
    host, port = server
    body = json.dumps({"title": "no host"}).encode("utf-8")
    req = (
        b"POST /todos HTTP/1.0\r\n"
        b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\n".encode("ascii")
        + b"\r\n"
        + body
    )
    status, headers, body_bytes = send_raw_request(host, port, req)
    assert status == 201
    assert "Location" in headers
    data = json.loads(body_bytes.decode("utf-8"))
    expected_prefix = f"http://{host}:{port}/todos/"
    assert headers["Location"].startswith(expected_prefix)
    assert headers["Location"].endswith(str(data["id"]))