import json
import threading
import time
from datetime import datetime
from http.client import HTTPConnection

import pytest

import scrum_20 as mod


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


@pytest.fixture
def fresh_store():
    return mod.TodoStore()


@pytest.fixture
def http_server(monkeypatch):
    store = mod.TodoStore()
    monkeypatch.setattr(mod, "STORE", store)
    server = mod.ThreadingHTTPServer(("127.0.0.1", 0), mod.TodoRequestHandler)
    host, port = server.server_address

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield host, port, store
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=2)


def http_request(host, port, method, path, body=None, headers=None):
    conn = HTTPConnection(host, port, timeout=5)
    try:
        if isinstance(body, (dict, list)):
            body_bytes = json.dumps(body).encode("utf-8")
        elif isinstance(body, (bytes, bytearray)) or body is None:
            body_bytes = body
        else:
            body_bytes = str(body).encode("utf-8")
        hdrs = headers.copy() if headers else {}
        conn.request(method, path, body=body_bytes, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        try:
            payload = json.loads(data.decode("utf-8"))
        except Exception:
            payload = None
        return resp.status, dict(resp.getheaders()), payload
    finally:
        conn.close()


def test_normalize_due_date_accepts_none_and_date_and_datetime():
    assert mod.normalize_due_date(None) is None
    assert mod.normalize_due_date("2023-01-02") == "2023-01-02"
    # strip whitespace
    assert mod.normalize_due_date(" 2023-01-02 ") == "2023-01-02"
    # Z normalization
    assert mod.normalize_due_date("2023-01-02T03:04:05Z") == "2023-01-02T03:04:05+00:00"
    # timezone aware datetime preserved
    dt = "2023-01-02T03:04:05.123456+02:00"
    assert mod.normalize_due_date(dt) == dt


@pytest.mark.parametrize(
    "value, msg_part",
    [
        (123, "string or null"),
        ("", "cannot be empty"),
        ("not-a-date", "ISO 8601"),
    ],
)
def test_normalize_due_date_invalid_values(value, msg_part):
    with pytest.raises(ValueError) as exc:
        mod.normalize_due_date(value)
    assert msg_part in str(exc.value)


def test_validate_title_and_description_and_status():
    assert mod.validate_title("Hello") == "Hello"
    assert mod.validate_description("world") == "world"
    # description can be empty string
    assert mod.validate_description("") == ""
    assert mod.validate_status("pending") == "pending"
    # invalid title
    with pytest.raises(ValueError, match="title must be a string"):
        mod.validate_title(123)
    with pytest.raises(ValueError, match="title cannot be empty"):
        mod.validate_title("   ")
    # invalid description
    with pytest.raises(ValueError, match="description must be a string"):
        mod.validate_description(123)
    # invalid status
    with pytest.raises(ValueError) as exc:
        mod.validate_status("done")
    assert "status must be one of" in str(exc.value)


def test_store_update_put_success_refreshed_updatedAt(fresh_store):
    store = fresh_store
    todo = store.get(1)
    prev_updated = _dt(todo.updatedAt)
    prev_created = todo.createdAt

    payload = {
        "title": "New Title",
        "description": "New Desc",
        "dueDate": "2024-01-01T00:00:00Z",
        "status": "completed",
    }
    updated = store.update_put(1, payload)
    assert updated["title"] == "New Title"
    assert updated["description"] == "New Desc"
    assert updated["dueDate"] == "2024-01-01T00:00:00+00:00"
    assert updated["status"] == "completed"
    assert updated["createdAt"] == prev_created
    assert _dt(updated["updatedAt"]) > prev_updated


def test_store_update_put_missing_fields(fresh_store):
    store = fresh_store
    payload = {"title": "Only Title"}
    with pytest.raises(mod.BadRequest) as exc:
        store.update_put(1, payload)
    assert "Missing required fields for PUT" in str(exc.value)


def test_store_update_patch_no_fields(fresh_store):
    store = fresh_store
    with pytest.raises(mod.BadRequest, match="No mutable fields provided for PATCH"):
        store.update_patch(1, {"foo": "bar"})


def test_store_update_patch_partial_and_updatedAt_changes(fresh_store):
    store = fresh_store
    before = store.get(2)
    prev_title = before.title
    prev_desc = before.description
    prev_due = before.dueDate
    prev_status = before.status
    prev_updated = _dt(before.updatedAt)

    updated = store.update_patch(2, {"title": "Patched"})
    assert updated["title"] == "Patched"
    assert updated["description"] == prev_desc
    assert updated["dueDate"] == prev_due
    assert updated["status"] == prev_status
    assert _dt(updated["updatedAt"]) > prev_updated


def test_store_not_found(fresh_store):
    store = fresh_store
    with pytest.raises(mod.NotFound):
        store.update_put(9999, {"title": "a", "description": "b", "dueDate": None, "status": "pending"})
    with pytest.raises(mod.NotFound):
        store.update_patch(9999, {"title": "x"})


def test_http_put_success(http_server):
    host, port, store = http_server
    pre = store.get(1)
    prev_updated = pre.updatedAt

    body = {
        "title": "HTTP PUT Title",
        "description": "HTTP PUT Desc",
        "dueDate": "2025-12-31",
        "status": "in_progress",
    }
    status, headers, payload = http_request(host, port, "PUT", "/todos/1", body=body, headers={"Content-Type": "application/json"})
    assert status == 200
    assert headers.get("Content-Type", "").startswith("application/json")
    assert payload["title"] == "HTTP PUT Title"
    assert payload["description"] == "HTTP PUT Desc"
    assert payload["dueDate"] == "2025-12-31"
    assert payload["status"] == "in_progress"
    assert payload["updatedAt"] != prev_updated
    assert _dt(payload["updatedAt"]) > _dt(prev_updated)
    # Store reflects changes
    updated = store.get(1)
    assert updated.title == "HTTP PUT Title"


def test_http_put_missing_required_fields_returns_400(http_server):
    host, port, _ = http_server
    body = {"title": "Only Title"}
    status, _, payload = http_request(host, port, "PUT", "/todos/1", body=body, headers={"Content-Type": "application/json"})
    assert status == 400
    assert "Missing required fields for PUT" in payload.get("error", "")


def test_http_patch_partial_update(http_server):
    host, port, store = http_server
    status, _, payload = http_request(host, port, "PATCH", "/todos/2", body={"status": "completed"}, headers={"Content-Type": "application/json"})
    assert status == 200
    assert payload["status"] == "completed"
    assert store.get(2).status == "completed"


def test_http_patch_clear_due_date_with_null(http_server):
    host, port, store = http_server
    # set dueDate to something first
    http_request(host, port, "PATCH", "/todos/1", body={"dueDate": "2024-01-01"}, headers={"Content-Type": "application/json"})
    assert store.get(1).dueDate == "2024-01-01"
    # clear it
    status, _, payload = http_request(host, port, "PATCH", "/todos/1", body={"dueDate": None}, headers={"Content-Type": "application/json"})
    assert status == 200
    assert payload["dueDate"] is None
    assert store.get(1).dueDate is None


def test_http_patch_no_mutable_fields_400(http_server):
    host, port, _ = http_server
    status, _, payload = http_request(host, port, "PATCH", "/todos/1", body={}, headers={"Content-Type": "application/json"})
    assert status == 400
    assert payload["error"] == "No mutable fields provided for PATCH"


def test_http_not_found_id_returns_404(http_server):
    host, port, _ = http_server
    body = {"title": "x", "description": "y", "dueDate": None, "status": "pending"}
    status, _, payload = http_request(host, port, "PUT", "/todos/9999", body=body, headers={"Content-Type": "application/json"})
    assert status == 404
    assert "not found" in payload.get("error", "").lower()


def test_http_invalid_path_returns_404(http_server):
    host, port, _ = http_server
    status, _, payload = http_request(host, port, "PUT", "/invalid/1", body={"foo": "bar"}, headers={"Content-Type": "application/json"})
    assert status == 404
    assert payload["error"] == "Not Found"


def test_http_invalid_status_returns_400(http_server):
    host, port, _ = http_server
    status, _, payload = http_request(host, port, "PATCH", "/todos/1", body={"status": "done"}, headers={"Content-Type": "application/json"})
    assert status == 400
    assert "status must be one of" in payload.get("error", "")


def test_http_invalid_json_returns_400(http_server):
    host, port, _ = http_server
    # invalid JSON string
    status, _, payload = http_request(host, port, "PUT", "/todos/1", body=b"not json", headers={"Content-Type": "application/json"})
    assert status == 400
    assert payload["error"] == "Request body must be valid JSON"
    # invalid UTF-8
    status, _, payload = http_request(host, port, "PUT", "/todos/1", body=b"\x80", headers={"Content-Type": "application/json"})
    assert status == 400
    assert payload["error"] == "Request body must be valid JSON"


def test_http_non_object_json_returns_400(http_server):
    host, port, _ = http_server
    status, _, payload = http_request(host, port, "PUT", "/todos/1", body=[1, 2, 3], headers={"Content-Type": "application/json"})
    assert status == 400
    assert payload["error"] == "JSON payload must be an object"


def test_http_missing_content_length_returns_400(http_server):
    host, port, _ = http_server
    # No body and no Content-Length header
    status, _, payload = http_request(host, port, "PUT", "/todos/1", body=None, headers={})
    assert status == 400
    assert payload["error"] == "Missing Content-Length"


def test_http_invalid_content_length_returns_400(http_server):
    host, port, _ = http_server
    # Provide a body but a bogus Content-Length header
    status, _, payload = http_request(host, port, "PUT", "/todos/1", body=b"{}", headers={"Content-Type": "application/json", "Content-Length": "abc"})
    assert status == 400
    assert payload["error"] == "Invalid Content-Length"


def test_http_empty_body_length_zero_returns_400(http_server):
    host, port, _ = http_server
    status, _, payload = http_request(host, port, "PUT", "/todos/1", body=None, headers={"Content-Length": "0"})
    assert status == 400
    assert payload["error"] == "Empty request body"


def test_http_internal_server_error_on_unexpected_exception(http_server, monkeypatch):
    host, port, store = http_server
    # Force update_put to raise an unexpected Exception
    def boom(todo_id, payload):
        raise Exception("boom")
    monkeypatch.setattr(mod.STORE, "update_put", boom)
    status, _, payload = http_request(host, port, "PUT", "/todos/1", body={"title": "a", "description": "b", "dueDate": None, "status": "pending"}, headers={"Content-Type": "application/json"})
    assert status == 500
    assert payload["error"] == "Internal Server Error"