"""
scrum_20.py

A minimal HTTP API for updating Todo items.

Endpoints:
- PUT /todos/{id}   : Replace mutable fields (title, description, dueDate, status).
- PATCH /todos/{id} : Partially update any subset of mutable fields.

Behavior:
- 200 OK with the updated resource on success.
- 400 Bad Request for invalid updates (e.g., empty title, invalid status, bad JSON).
- 404 Not Found when the id does not exist.
- updatedAt is refreshed on successful update.

No external dependencies beyond Python's standard library.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple


ALLOWED_STATUSES = {"pending", "in_progress", "completed"}
MUTABLE_FIELDS = {"title", "description", "dueDate", "status"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_due_date(value: Optional[Any]) -> Optional[str]:
    """
    Validate and normalize dueDate.
    Accepts:
      - null (None) to clear the dueDate.
      - ISO 8601 date (YYYY-MM-DD)
      - ISO 8601 datetime (e.g., YYYY-MM-DDTHH:MM:SS[.ffffff][Z|+HH:MM])
    Returns normalized ISO string or None.
    Raises ValueError for invalid value.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("dueDate must be a string or null")
    s = value.strip()
    if not s:
        raise ValueError("dueDate cannot be empty")
    # Try date
    try:
        d = date.fromisoformat(s)
        return d.isoformat()
    except ValueError:
        pass
    # Try datetime, handle 'Z'
    s2 = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s2)
        return dt.isoformat()
    except ValueError as exc:
        raise ValueError("dueDate must be ISO 8601 date or datetime") from exc


def validate_title(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("title must be a string")
    if not value.strip():
        raise ValueError("title cannot be empty")
    return value


def validate_description(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("description must be a string")
    return value


def validate_status(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("status must be a string")
    if value not in ALLOWED_STATUSES:
        raise ValueError(f"status must be one of {sorted(ALLOWED_STATUSES)}")
    return value


@dataclass
class Todo:
    id: int
    title: str
    description: str
    dueDate: Optional[str]
    status: str
    createdAt: str
    updatedAt: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BadRequest(Exception):
    pass


class NotFound(Exception):
    pass


class TodoStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._todos: Dict[int, Todo] = {}
        self._next_id: int = 1
        self._initialize_sample_data()

    def _initialize_sample_data(self) -> None:
        with self._lock:
            self._add_sample(
                title="Buy milk",
                description="2% milk from the store",
                dueDate=None,
                status="pending",
            )
            self._add_sample(
                title="Write report",
                description="Draft quarterly report",
                dueDate=(datetime.now(timezone.utc)).isoformat(),
                status="in_progress",
            )

    def _add_sample(self, title: str, description: str, dueDate: Optional[str], status: str) -> None:
        todo = Todo(
            id=self._next_id,
            title=title,
            description=description,
            dueDate=dueDate,
            status=status,
            createdAt=now_iso(),
            updatedAt=now_iso(),
        )
        self._todos[self._next_id] = todo
        self._next_id += 1

    def get(self, todo_id: int) -> Todo:
        with self._lock:
            todo = self._todos.get(todo_id)
            if not todo:
                raise NotFound(f"Todo with id {todo_id} not found")
            return todo

    def update_put(self, todo_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Replace all mutable fields. Payload must include title, description, dueDate, status.
        """
        with self._lock:
            if todo_id not in self._todos:
                raise NotFound(f"Todo with id {todo_id} not found")

            missing = [k for k in MUTABLE_FIELDS if k not in payload]
            if missing:
                raise BadRequest(f"Missing required fields for PUT: {missing}")

            # Validate fields
            try:
                title = validate_title(payload["title"])
                description = validate_description(payload["description"])
                due_date = normalize_due_date(payload["dueDate"])
                status = validate_status(payload["status"])
            except ValueError as exc:
                raise BadRequest(str(exc)) from exc

            # Apply update
            todo = self._todos[todo_id]
            todo.title = title
            todo.description = description
            todo.dueDate = due_date
            todo.status = status
            todo.updatedAt = now_iso()
            return todo.to_dict()

    def update_patch(self, todo_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Partially update mutable fields.
        """
        with self._lock:
            if todo_id not in self._todos:
                raise NotFound(f"Todo with id {todo_id} not found")

            provided_fields = MUTABLE_FIELDS.intersection(payload.keys())
            if not provided_fields:
                raise BadRequest("No mutable fields provided for PATCH")

            todo = self._todos[todo_id]

            # Validate and apply each provided field
            try:
                if "title" in provided_fields:
                    todo.title = validate_title(payload["title"])
                if "description" in provided_fields:
                    todo.description = validate_description(payload["description"])
                if "dueDate" in provided_fields:
                    todo.dueDate = normalize_due_date(payload["dueDate"])
                if "status" in provided_fields:
                    todo.status = validate_status(payload["status"])
            except ValueError as exc:
                raise BadRequest(str(exc)) from exc

            todo.updatedAt = now_iso()
            return todo.to_dict()


STORE = TodoStore()


class TodoRequestHandler(BaseHTTPRequestHandler):
    server_version = "TodoAPI/1.0"

    _todos_re = re.compile(r"^/todos/(\d+)$")

    def do_PUT(self) -> None:
        self._handle_update(method="PUT")

    def do_PATCH(self) -> None:
        self._handle_update(method="PATCH")

    def _handle_update(self, method: str) -> None:
        todo_id, err = self._parse_id_from_path(self.path)
        if err:
            self._send_json(404, {"error": "Not Found"})
            return

        try:
            payload = self._read_json_body()
        except BadRequest as exc:
            self._send_json(400, {"error": str(exc)})
            return

        try:
            if method == "PUT":
                updated = STORE.update_put(todo_id, payload)
            else:
                updated = STORE.update_patch(todo_id, payload)
            self._send_json(200, updated)
        except NotFound as exc:
            self._send_json(404, {"error": str(exc)})
        except BadRequest as exc:
            self._send_json(400, {"error": str(exc)})
        except Exception:
            # Unexpected error
            self._send_json(500, {"error": "Internal Server Error"})

    def _parse_id_from_path(self, path: str) -> Tuple[Optional[int], Optional[str]]:
        m = self._todos_re.match(path)
        if not m:
            return None, "invalid_path"
        try:
            return int(m.group(1)), None
        except ValueError:
            return None, "invalid_id"

    def _read_json_body(self) -> Dict[str, Any]:
        length_header = self.headers.get("Content-Length")
        if not length_header:
            raise BadRequest("Missing Content-Length")
        try:
            length = int(length_header)
        except ValueError:
            raise BadRequest("Invalid Content-Length")
        if length <= 0:
            raise BadRequest("Empty request body")

        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise BadRequest("Request body must be valid JSON")
        if not isinstance(payload, dict):
            raise BadRequest("JSON payload must be an object")
        return payload

    def _send_json(self, status_code: int, body: Dict[str, Any]) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # Reduce default logging noise
    def log_message(self, format: str, *args: Any) -> None:
        return


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), TodoRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()