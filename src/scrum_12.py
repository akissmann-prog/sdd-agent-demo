"""
scrum_12.py

A minimal HTTP API server to create todo items via POST /todos.

Features:
- Accepts JSON payload with required "title" and optional "description" and "dueDate".
- New todos default to status "pending" and include id, createdAt, and updatedAt.
- Returns 201 Created with Location header pointing to the new resource and the created object in the body.
- Returns 400 Bad Request for validation errors with a clear error payload.
- Returns 415 Unsupported Media Type when Content-Type is not application/json.

This module uses only Python's standard library.
"""

from __future__ import annotations

import json
import threading
from datetime import date, datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import count
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse


# In-memory storage for todos. Thread-safe access ensured with a lock.
_TODOS_DB: Dict[int, Dict[str, Any]] = {}
_TODOS_LOCK = threading.Lock()
_ID_COUNTER = count(start=1)


def _now_utc_iso() -> str:
    """Return current UTC time in ISO 8601 format with 'Z' suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_content_type(ct: Optional[str]) -> Optional[str]:
    """Normalize Content-Type to its media type (lowercased, without parameters)."""
    if not ct:
        return None
    media_type = ct.split(";", 1)[0].strip().lower()
    return media_type or None


def _parse_iso_due_date(raw: Any) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Parse and validate a dueDate string.
    Accepts ISO 8601 date (YYYY-MM-DD) or datetime strings.
    Returns (ok, normalized_value, error_message).
    """
    if raw is None:
        return True, None, None
    if not isinstance(raw, str):
        return False, None, "dueDate must be a string in ISO 8601 format"

    s = raw.strip()
    if not s:
        return False, None, "dueDate cannot be empty"

    # Handle 'Z' suffix by converting to +00:00 for fromisoformat
    if s.endswith("Z"):
        s_for_parse = s[:-1] + "+00:00"
    else:
        s_for_parse = s

    # Try date only
    try:
        d = date.fromisoformat(s)
        return True, d.isoformat(), None
    except ValueError:
        pass

    # Try datetime
    try:
        dt = datetime.fromisoformat(s_for_parse)
        # Normalize to ISO with 'Z' if UTC, otherwise keep offset
        if dt.tzinfo is not None and dt.utcoffset() == timezone.utc.utcoffset(None):
            norm = dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        else:
            norm = dt.isoformat()
        return True, norm, None
    except ValueError:
        return False, None, "Invalid dueDate format. Expected ISO 8601 date or datetime."


def _validate_todo_payload(data: Any) -> Tuple[bool, Dict[str, str], Dict[str, Any]]:
    """
    Validate incoming JSON for creating a todo.
    Returns (is_valid, errors, normalized_data).
    """
    errors: Dict[str, str] = {}
    normalized: Dict[str, Any] = {}

    if not isinstance(data, dict):
        return False, {"payload": "JSON payload must be an object"}, {}

    # Title validation
    title = data.get("title")
    if title is None:
        errors["title"] = "Missing required field: title"
    elif not isinstance(title, str):
        errors["title"] = "title must be a string"
    else:
        title_stripped = title.strip()
        if not title_stripped:
            errors["title"] = "title cannot be empty"
        else:
            normalized["title"] = title_stripped

    # Description (optional)
    if "description" in data:
        desc = data.get("description")
        if desc is None:
            normalized["description"] = None
        elif not isinstance(desc, str):
            errors["description"] = "description must be a string"
        else:
            normalized["description"] = desc

    # dueDate (optional)
    if "dueDate" in data:
        ok, norm_due, err = _parse_iso_due_date(data.get("dueDate"))
        if not ok:
            errors["dueDate"] = err or "Invalid dueDate"
        else:
            normalized["dueDate"] = norm_due

    return (len(errors) == 0), errors, normalized


def _build_error_payload(code: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    err: Dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        err["error"]["details"] = details
    return err


class TodoAPIHandler(BaseHTTPRequestHandler):
    server_version = "TodoAPIServer/1.0"

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.rstrip("/") != "/todos":
            self._send_json(
                HTTPStatus.NOT_FOUND,
                _build_error_payload("not_found", "The requested resource was not found."),
            )
            return

        # Content-Type check
        ct = _normalize_content_type(self.headers.get("Content-Type"))
        if ct != "application/json":
            self._send_json(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                _build_error_payload(
                    "unsupported_media_type",
                    "Content-Type must be application/json.",
                    {"contentType": self.headers.get("Content-Type")},
                ),
            )
            return

        # Read body
        length_header = self.headers.get("Content-Length")
        if not length_header:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                _build_error_payload("invalid_request", "Request body is required."),
            )
            return

        try:
            content_length = int(length_header)
        except ValueError:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                _build_error_payload("invalid_request", "Invalid Content-Length header."),
            )
            return

        try:
            raw_body = self.rfile.read(content_length)
        except Exception:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                _build_error_payload("invalid_request", "Unable to read request body."),
            )
            return

        if not raw_body:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                _build_error_payload("invalid_request", "Request body is empty."),
            )
            return

        # Parse JSON
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as e:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                _build_error_payload(
                    "invalid_json",
                    "Malformed JSON.",
                    {"message": str(e)},
                ),
            )
            return

        # Validate
        is_valid, errors, normalized = _validate_todo_payload(payload)
        if not is_valid:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                _build_error_payload("validation_error", "Payload validation failed.", errors),
            )
            return

        # Create todo
        with _TODOS_LOCK:
            todo_id = next(_ID_COUNTER)
            now = _now_utc_iso()
            todo_obj: Dict[str, Any] = {
                "id": todo_id,
                "title": normalized["title"],
                "status": "pending",
                "createdAt": now,
                "updatedAt": now,
            }
            if "description" in normalized:
                todo_obj["description"] = normalized["description"]
            if "dueDate" in normalized:
                todo_obj["dueDate"] = normalized["dueDate"]
            _TODOS_DB[todo_id] = todo_obj

        location = self._build_location_header(f"/todos/{todo_id}")
        self._send_json(HTTPStatus.CREATED, todo_obj, extra_headers={"Location": location})

    # Utility methods

    def _build_location_header(self, resource_path: str) -> str:
        # Prefer Host header, fallback to server addr
        host = self.headers.get("Host")
        if not host:
            server_addr = self.server.server_address  # type: ignore[attr-defined]
            host = f"{server_addr[0]}:{server_addr[1]}"
        scheme = "http"
        return f"{scheme}://{host}{resource_path}"

    def _send_json(
        self,
        status: HTTPStatus,
        data: Dict[str, Any],
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value, status.phrase)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the Todo API server."""
    server = ThreadingHTTPServer((host, port), TodoAPIHandler)
    try:
        print(f"Serving Todo API on http://{host}:{port}")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()