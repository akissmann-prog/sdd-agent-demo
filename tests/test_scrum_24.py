import json
import threading
import http.client
import pytest

import scrum_24


def _request(host, port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection(host, port, timeout=5)
    hdrs = dict(headers or {})
    data = None
    if isinstance(body, (dict, list)):
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json; charset=utf-8")
    elif isinstance(body, str):
        data = body.encode("utf-8")
    elif isinstance(body, (bytes, bytearray)):
        data = body
    conn.request(method, path, body=data, headers=hdrs)
    resp = conn.getresponse()
    body_bytes = resp.read()
    headers_dict = {k.lower(): v for k, v in resp.getheaders()}
    status = resp.status
    conn.close()
    return status, headers_dict, body_bytes


@pytest.fixture
def server(monkeypatch):
    store = scrum_24.TodoStore()
    monkeypatch.setattr(scrum_24, "STORE", store)
    httpd = scrum_24.ThreadingHTTPServer(("127.0.0.1", 0), scrum_24.TodoRequestHandler)
    host, port = httpd.server_address
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield host, port, store
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=1)


def test_post_creates_todo_and_get_and_list(server):
    host, port, _ = server

    # Create a todo
    status, headers, body = _request(
        host,
        port,
        "POST",
        "/todos",
        body={"title": "Task A", "completed": True},
    )
    assert status == 201
    assert "location" in headers
    assert headers.get("content-type", "").startswith("application/json")
    obj = json.loads(body.decode("utf-8"))
    assert obj["title"] == "Task A"
    assert obj["completed"] is True
    assert isinstance(obj["id"], int)
    new_id = obj["id"]
    assert headers["location"] == f"/todos/{new_id}"
    # Content-Length should match body size
    assert int(headers["content-length"]) == len(body)

    # List todos
    status, headers, body = _request(host, port, "GET", "/todos")
    assert status == 200
    items = json.loads(body.decode("utf-8"))
    assert isinstance(items, list)
    assert any(item["id"] == new_id for item in items)

    # Get by id
    status, headers, body = _request(host, port, "GET", f"/todos/{new_id}")
    assert status == 200
    item = json.loads(body.decode("utf-8"))
    assert item["id"] == new_id
    assert item["title"] == "Task A"
    assert item["completed"] is True


def test_delete_existing_todo_returns_204_and_removes_only_that_item(server):
    host, port, _ = server

    # Create two todos
    s, h, b = _request(host, port, "POST", "/todos", body={"title": "A"})
    id1 = json.loads(b.decode("utf-8"))["id"]
    s, h, b = _request(host, port, "POST", "/todos", body={"title": "B"})
    id2 = json.loads(b.decode("utf-8"))["id"]

    # Confirm both exist
    s, h, b = _request(host, port, "GET", "/todos")
    assert s == 200
    lst = json.loads(b.decode("utf-8"))
    assert {item["id"] for item in lst} == {id1, id2}

    # Delete first
    status, headers, body = _request(host, port, "DELETE", f"/todos/{id1}")
    assert status == 204
    assert headers.get("content-length") == "0"
    assert body == b""

    # Deleted item now 404
    status, headers, body = _request(host, port, "GET", f"/todos/{id1}")
    assert status == 404
    assert headers.get("content-type", "").startswith("application/json")
    err = json.loads(body.decode("utf-8"))
    assert "not found" in err.get("error", "").lower()

    # Other item unaffected
    status, headers, body = _request(host, port, "GET", f"/todos/{id2}")
    assert status == 200
    item = json.loads(body.decode("utf-8"))
    assert item["id"] == id2

    # Deleting again is idempotent: returns 404
    status, headers, body = _request(host, port, "DELETE", f"/todos/{id1}")
    assert status == 404
    msg = json.loads(body.decode("utf-8")).get("error", "")
    assert str(id1) in msg


def test_delete_with_plus_prefix_and_path_normalization(server):
    host, port, _ = server

    # Create a todo
    status, headers, body = _request(host, port, "POST", "/todos", body={"title": "X"})
    assert status == 201
    todo_id = json.loads(body.decode("utf-8"))["id"]

    # Delete using + prefix
    status, headers, body = _request(host, port, "DELETE", f"/todos/+{todo_id}")
    assert status == 204

    # Recreate and delete using path with extra slashes and trailing slash
    status, headers, body = _request(host, port, "POST", "/todos", body={"title": "Y"})
    assert status == 201
    todo_id2 = json.loads(body.decode("utf-8"))["id"]

    status, headers, body = _request(host, port, "DELETE", f"///todos///{todo_id2}///")
    assert status == 204

    # Both should be gone
    s1, _, b1 = _request(host, port, "GET", f"/todos/{todo_id}")
    s2, _, b2 = _request(host, port, "GET", f"/todos/{todo_id2}")
    assert s1 == 404
    assert s2 == 404


def test_delete_nonexistent_and_invalid_id(server):
    host, port, _ = server

    # Nonexistent integer id
    status, headers, body = _request(host, port, "DELETE", "/todos/999")
    assert status == 404
    err = json.loads(body.decode("utf-8"))
    assert err.get("error") == "Todo with id 999 not found."
    assert headers.get("content-type", "").startswith("application/json")

    # Zero id (parsed as int)
    status, headers, body = _request(host, port, "DELETE", "/todos/0")
    assert status == 404
    err = json.loads(body.decode("utf-8"))
    assert err.get("error") == "Todo with id 0 not found."

    # Invalid id string -> generic not found
    status, headers, body = _request(host, port, "DELETE", "/todos/abc")
    assert status == 404
    err = json.loads(body.decode("utf-8"))
    assert err.get("error") == "Resource not found."


def test_options_returns_cors_and_allow_headers(server):
    host, port, _ = server
    status, headers, body = _request(host, port, "OPTIONS", "/any")
    assert status == 204
    assert headers.get("allow") == "GET,POST,DELETE,OPTIONS"
    assert headers.get("access-control-allow-origin") == "*"
    assert "GET,POST,DELETE,OPTIONS" in headers.get("access-control-allow-methods", "")
    assert "content-type" in headers.get("access-control-allow-headers", "").lower()
    assert headers.get("content-length") == "0"
    assert body == b""


def test_post_invalid_json_returns_400(server):
    host, port, _ = server
    status, headers, body = _request(
        host,
        port,
        "POST",
        "/todos",
        body='{"title": "A", bad',
        headers={"Content-Type": "application/json"},
    )
    assert status == 400
    assert headers.get("content-type", "").startswith("application/json")
    payload = json.loads(body.decode("utf-8"))
    assert payload.get("error") == "Invalid JSON"
    assert int(headers["content-length"]) == len(body)


def test_invalid_content_length_is_ignored_and_defaults_used(server):
    host, port, _ = server
    # Send a body with an invalid Content-Length header; server should read 0 bytes and use defaults
    status, headers, body = _request(
        host,
        port,
        "POST",
        "/todos",
        body='{"title":"ShouldBeIgnored","completed":true}',
        headers={"Content-Type": "application/json; charset=utf-8", "Content-Length": "invalid"},
    )
    assert status == 201
    obj = json.loads(body.decode("utf-8"))
    # Because the server read zero bytes due to invalid Content-Length, it should fall back to defaults
    assert obj["title"] == ""
    assert obj["completed"] is False
    assert isinstance(obj["id"], int)


def test_get_unknown_path_returns_404_with_json(server):
    host, port, _ = server
    status, headers, body = _request(host, port, "GET", "/unknown/path")
    assert status == 404
    assert headers.get("content-type", "").startswith("application/json")
    payload = json.loads(body.decode("utf-8"))
    assert payload.get("error") == "Resource not found."
    assert int(headers["content-length"]) == len(body)


def test_todostore_basic_operations():
    store = scrum_24.TodoStore()
    id1 = store.add({"title": "one", "completed": False})
    id2 = store.add({"title": "two", "completed": True})

    assert id1 == 1
    assert id2 == 2

    assert store.exists(id1)
    assert store.exists(id2)
    assert not store.exists(999)

    got1 = store.get(id1)
    assert got1 is not None and got1["id"] == id1 and got1["title"] == "one"

    all_items = store.list_all()
    assert set(all_items.keys()) == {id1, id2}
    assert all_items[id2]["completed"] is True

    assert store.delete(id1) is True
    assert store.delete(id1) is False
    assert store.get(id1) is None

    # IDs keep incrementing after deletion
    id3 = store.add({"title": "three", "completed": False})
    assert id3 == 3
    assert store.exists(id3)