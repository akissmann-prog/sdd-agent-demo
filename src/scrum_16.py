"""
Simple HTTP server providing a read-only Todos API.

Endpoints:
- GET /todos
    Returns a list of todos with fields:
    id, title, description, status, dueDate, createdAt, updatedAt.
    Supports query parameters:
        - status: "pending" or "completed"
        - page: positive integer (default 1)
        - pageSize: positive integer (default 10)

- GET /todos/{id}
    Returns a single todo by id.

Responses:
- 200 OK on success with JSON body.
- 404 Not Found when the requested id does not exist.
- 400 Bad Request for invalid query parameters.

Run:
    python scrum_16.py
This starts a development HTTP server on http://127.0.0.1:8000
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse


@dataclass(frozen=True)
class Todo:
    id: int
    title: str
    description: str
    status: str  # "pending" | "completed"
    due_date: str  # ISO 8601 string
    created_at: str  # ISO 8601 string
    updated_at: str  # ISO 8601 string

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "dueDate": self.due_date,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


class TodoRepository:
    def __init__(self, todos: Optional[List[Todo]] = None) -> None:
        self._todos: List[Todo] = todos[:] if todos else []

    def list(self, status: Optional[str] = None) -> List[Todo]:
        if status is None:
            return self._todos[:]
        return [t for t in self._todos if t.status == status]

    def get_by_id(self, todo_id: int) -> Optional[Todo]:
        for t in self._todos:
            if t.id == todo_id:
                return t
        return None


def sample_todos() -> List[Todo]:
    # Example static dataset with ISO 8601 timestamps (UTC 'Z' suffix)
    return [
        Todo(
            id=1,
            title="Buy groceries",
            description="Milk, Bread, Eggs, and Fruits",
            status="pending",
            due_date="2026-10-15T12:00:00Z",
            created_at="2026-09-01T08:30:00Z",
            updated_at="2026-09-02T09:45:00Z",
        ),
        Todo(
            id=2,
            title="Finish report",
            description="Complete the quarterly financial report",
            status="completed",
            due_date="2026-09-20T17:00:00Z",
            created_at="2026-08-31T10:00:00Z",
            updated_at="2026-09-15T15:20:00Z",
        ),
        Todo(
            id=3,
            title="Plan vacation",
            description="Research destinations and book flights",
            status="pending",
            due_date="2026-12-01T09:00:00Z",
            created_at="2026-09-10T11:15:00Z",
            updated_at="2026-09-10T11:15:00Z",
        ),
        Todo(
            id=4,
            title="Doctor appointment",
            description="Annual physical checkup",
            status="completed",
            due_date="2026-09-10T14:00:00Z",
            created_at="2026-09-01T12:00:00Z",
            updated_at="2026-09-10T15:00:00Z",
        ),
        Todo(
            id=5,
            title="Team meeting",
            description="Discuss project milestones",
            status="pending",
            due_date="2026-10-05T10:30:00Z",
            created_at="2026-09-12T09:00:00Z",
            updated_at="2026-09-12T09:00:00Z",
        ),
        Todo(
            id=6,
            title="Call plumber",
            description="Fix the kitchen sink leakage",
            status="pending",
            due_date="2026-10-02T16:00:00Z",
            created_at="2026-09-11T13:45:00Z",
            updated_at="2026-09-11T13:45:00Z",
        ),
    ]


class TodoRequestHandler(BaseHTTPRequestHandler):
    # Repository is injected via run() by setting this class variable.
    repository: TodoRepository

    server_version = "TodosAPI/1.0"

    def do_GET(self) -> None:  # noqa: N802 (http.server signature)
        path, query = self._parse_url()
        if path == "/todos" or path == "/todos/":
            self._handle_list_todos(query)
            return

        if path.startswith("/todos/"):
            self._handle_get_todo_by_id(path)
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not Found"})

    # Reject other methods explicitly with 405 Method Not Allowed
    def do_POST(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PUT(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PATCH(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def _method_not_allowed(self) -> None:
        self._send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Method Not Allowed"})

    def _parse_url(self) -> Tuple[str, Dict[str, List[str]]]:
        parsed = urlparse(self.path)
        return parsed.path, parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False)

    def _handle_list_todos(self, query: Dict[str, List[str]]) -> None:
        # Validate and extract query parameters
        try:
            status = self._validate_status_param(query)
            page = self._validate_positive_int(query, "page", default=1)
            page_size = self._validate_positive_int(query, "pageSize", default=10)
        except ValueError as e:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            return

        # Filter by status
        todos = self.repository.list(status=status)

        # Pagination
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_items = todos[start_idx:end_idx]

        payload = [t.to_dict() for t in page_items]
        self._send_json(HTTPStatus.OK, payload)

    def _handle_get_todo_by_id(self, path: str) -> None:
        # Accept both /todos/{id} and /todos/{id}/
        parts = path.strip("/").split("/")
        if len(parts) < 2 or parts[0] != "todos":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not Found"})
            return

        id_part = parts[1]
        # If there are extra segments beyond ID, treat as not found
        if len(parts) > 2 and parts[2] != "":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not Found"})
            return

        try:
            todo_id = int(id_part)
        except (TypeError, ValueError):
            # Treat invalid ID format as not found
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Todo not found"})
            return

        todo = self.repository.get_by_id(todo_id)
        if not todo:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Todo not found"})
            return

        self._send_json(HTTPStatus.OK, todo.to_dict())

    def _validate_status_param(self, query: Dict[str, List[str]]) -> Optional[str]:
        if "status" not in query:
            return None
        values = query.get("status", [])
        if len(values) != 1:
            raise ValueError("Invalid query parameter: status")
        status_val = values[0].strip().lower()
        if status_val not in ("pending", "completed"):
            raise ValueError("Invalid query parameter: status")
        return status_val

    def _validate_positive_int(self, query: Dict[str, List[str]], key: str, default: int) -> int:
        if key not in query:
            return default
        values = query.get(key, [])
        if len(values) != 1:
            raise ValueError(f"Invalid query parameter: {key}")
        raw = values[0].strip()
        try:
            n = int(raw)
        except ValueError:
            raise ValueError(f"Invalid query parameter: {key}")
        if n <= 0:
            raise ValueError(f"Invalid query parameter: {key}")
        return n

    def _send_json(self, status: HTTPStatus, body: object) -> None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # Silence default logging for cleaner output; override log_message if needed.
    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        # Uncomment the next line to enable request logging to stderr
        # super().log_message(format, *args)
        pass


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    repo = TodoRepository(sample_todos())
    TodoRequestHandler.repository = repo
    server = HTTPServer((host, port), TodoRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()