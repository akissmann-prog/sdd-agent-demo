import json
import threading
import http.client
import urllib.parse
import pytest


@pytest.fixture(scope="module")
def http_server():
    import scrum_16 as m

    repo = m.TodoRepository(m.sample_todos())
    m.TodoRequestHandler.repository = repo
    server = m.HTTPServer(("127.0.0.1", 0), m.TodoRequestHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    try:
        yield base_url
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=1)


def _request(base_url, method, path, body=None, headers=None):
    url = urllib.parse.urlparse(base_url)
    conn = http.client.HTTPConnection(url.hostname, url.port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        try:
            body_json = json.loads(data.decode("utf-8"))
        except Exception:
            body_json = None
        return resp.status, dict(resp.getheaders()), data, body_json
    finally:
        conn.close()


def test_list_todos_default(http_server):
    import scrum_16 as m
    status, headers, raw, body = _request(http_server, "GET", "/todos")
    assert status == 200
    assert isinstance(body, list)
    assert len(body) == len(m.sample_todos())
    # check fields format
    first = body[0]
    assert set(["id", "title", "description", "status", "dueDate", "createdAt", "updatedAt"]).issubset(first.keys())


def test_list_todos_trailing_slash(http_server):
    status, headers, raw, body = _request(http_server, "GET", "/todos/")
    assert status == 200
    assert isinstance(body, list)


def test_list_todos_filter_status_case_insensitive(http_server):
    status, headers, raw, body = _request(http_server, "GET", "/todos?status=Pending")
    assert status == 200
    assert all(item["status"] == "pending" for item in body)
    # ensure it returns only pending items
    assert len(body) >= 1


def test_list_todos_filter_invalid_status(http_server):
    status, headers, raw, body = _request(http_server, "GET", "/todos?status=done")
    assert status == 400
    assert body["error"] == "Invalid query parameter: status"


def test_list_todos_filter_multiple_status_values(http_server):
    status, headers, raw, body = _request(http_server, "GET", "/todos?status=pending&status=completed")
    assert status == 400
    assert body["error"] == "Invalid query parameter: status"


def test_list_todos_pagination_basic(http_server):
    # Request page 2 with pageSize 2 -> items indices 2 and 3
    status, headers, raw, body_page2 = _request(http_server, "GET", "/todos?page=2&pageSize=2")
    assert status == 200
    assert isinstance(body_page2, list)
    assert len(body_page2) == 2

    # Confirm non-overlap with page 1
    status1, _, _, body_page1 = _request(http_server, "GET", "/todos?page=1&pageSize=2")
    assert status1 == 200
    assert body_page1 != body_page2
    # Combined should equal first four items in order
    combined = body_page1 + body_page2
    status_all, _, _, body_all = _request(http_server, "GET", "/todos?page=1&pageSize=10")
    assert combined == body_all[:4]


def test_list_todos_pagination_beyond_range_returns_empty(http_server):
    status, headers, raw, body = _request(http_server, "GET", "/todos?page=10&pageSize=5")
    assert status == 200
    assert body == []


@pytest.mark.parametrize(
    "query,expected_error",
    [
        ("page=0", "Invalid query parameter: page"),
        ("page=-1", "Invalid query parameter: page"),
        ("page=abc", "Invalid query parameter: page"),
        ("page=", "Invalid query parameter: page"),
        ("page=1&page=2", "Invalid query parameter: page"),
        ("pageSize=0", "Invalid query parameter: pageSize"),
        ("pageSize=-5", "Invalid query parameter: pageSize"),
        ("pageSize=abc", "Invalid query parameter: pageSize"),
        ("pageSize=", "Invalid query parameter: pageSize"),
        ("pageSize=1&pageSize=2", "Invalid query parameter: pageSize"),
    ],
)
def test_list_todos_invalid_pagination_params(http_server, query, expected_error):
    status, headers, raw, body = _request(http_server, "GET", f"/todos?{query}")
    assert status == 400
    assert body["error"] == expected_error


@pytest.mark.parametrize("path_suffix", ["", "/"])
def test_get_todo_by_id_success(http_server, path_suffix):
    status, headers, raw, body = _request(http_server, "GET", f"/todos/1{path_suffix}")
    assert status == 200
    assert isinstance(body, dict)
    assert body["id"] == 1
    # verify camelCase keys
    assert "dueDate" in body and "createdAt" in body and "updatedAt" in body


def test_get_todo_by_id_not_found(http_server):
    status, headers, raw, body = _request(http_server, "GET", "/todos/9999")
    assert status == 404
    assert body["error"] == "Todo not found"


def test_get_todo_by_id_invalid_format(http_server):
    status, headers, raw, body = _request(http_server, "GET", "/todos/abc")
    assert status == 404
    assert body["error"] == "Todo not found"


def test_get_todo_with_extra_segments_not_found(http_server):
    status, headers, raw, body = _request(http_server, "GET", "/todos/1/extra")
    assert status == 404
    assert body["error"] == "Not Found"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_method_not_allowed_on_todos(method, http_server):
    status, headers, raw, body = _request(http_server, method, "/todos")
    assert status == 405
    assert body["error"] == "Method Not Allowed"


def test_unknown_path_returns_not_found(http_server):
    status, headers, raw, body = _request(http_server, "GET", "/unknown")
    assert status == 404
    assert body["error"] == "Not Found"


def test_response_headers_content_type_and_length(http_server):
    status, headers, raw, body = _request(http_server, "GET", "/todos?status=pending&page=1&pageSize=3")
    assert status == 200
    assert headers.get("Content-Type") == "application/json; charset=utf-8"
    # Content-Length must equal the raw bytes length returned
    assert int(headers.get("Content-Length", "0")) == len(raw)