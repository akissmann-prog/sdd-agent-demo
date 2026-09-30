"""
A minimal HTTP API server for managing todo items, focusing on DELETE /todos/{id}.

Features:
- DELETE /todos/{id} removes the specified todo.
- Returns 204 No Content on successful deletion.
- Returns 404 Not Found when the id does not exist.
- Deletion is idempotent and does not affect other resources.

This module uses only Python's standard library and can be run as a standalone server.
"""

from __future__ import annotations

import json
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse


class TodoStore:
    """
    Thread-safe in-memory store for todo items.
    Each todo is represented by an integer id and an associated payload.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._todos: Dict[int, Dict] = {}
        self._next_id: int = 1

    def add(self, payload: Dict) -> int:
        """
        Add a new todo item with the given payload.
        Returns the newly assigned integer id.
        """
        with self._lock:
            todo_id = self._next_id
            self._next_id += 1
            self._todos[todo_id] = dict(payload, id=todo_id)
            return todo_id

    def delete(self, todo_id: int) -> bool:
        """
        Delete a todo item by id.
        Returns True if the item existed and was deleted, False if it did not exist.
        """
        with self._lock:
            return self._todos.pop(todo_id, None) is not None

    def exists(self, todo_id: int) -> bool:
        """
        Check whether a todo with the given id exists.
        """
        with self._lock:
            return todo_id in self._todos

    def list_all(self) -> Dict[int, Dict]:
        """
        Return a snapshot copy of all todos.
        """
        with self._lock:
            return dict(self._todos)

    def get(self, todo_id: int) -> Optional[Dict]:
        """
        Get a todo by id. Returns None if not found.
        """
        with self._lock:
            return self._todos.get(todo_id)


STORE = TodoStore()


class TodoRequestHandler(BaseHTTPRequestHandler):
    server_version = "TodoServer/1.0"

    def do_DELETE(self) -> None:  # noqa: N802 - method name required by BaseHTTPRequestHandler
        todo_id = self._extract_todo_id()
        if todo_id is None:
            self._send_not_found("Resource not found.")
            return

        deleted = STORE.delete(todo_id)
        if deleted:
            # Successful deletion; return 204 No Content with an empty body.
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            # Idempotent behavior: state unchanged; returns 404 since the id does not exist.
            self._send_not_found(f"Todo with id {todo_id} not found.")

    # Optional: implement GET for simple visibility/debugging (not required by acceptance criteria)
    def do_GET(self) -> None:  # noqa: N802
        path, segments = self._parse_path()
        if len(segments) == 1 and segments[0] == "todos":
            todos = list(STORE.list_all().values())
            self._send_json(HTTPStatus.OK, todos)
            return
        if len(segments) == 2 and segments[0] == "todos":
            todo_id = self._parse_int(segments[1])
            if todo_id is None:
                self._send_not_found("Resource not found.")
                return
            todo = STORE.get(todo_id)
            if todo is None:
                self._send_not_found(f"Todo with id {todo_id} not found.")
                return
            self._send_json(HTTPStatus.OK, todo)
            return

        self._send_not_found("Resource not found.")

    def do_POST(self) -> None:  # noqa: N802
        # Minimal POST endpoint to create todos (not required but useful for testing)
        path, segments = self._parse_path()
        if len(segments) == 1 and segments[0] == "todos":
            length = self._content_length()
            try:
                body = self.rfile.read(length) if length > 0 else b"{}"
                data = json.loads(body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON"})
                return
            title = data.get("title", "")
            payload = {"title": title, "completed": bool(data.get("completed", False))}
            new_id = STORE.add(payload)
            location = f"/todos/{new_id}"
            self.send_response(HTTPStatus.CREATED)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Location", location)
            response = STORE.get(new_id) or {}
            raw = json.dumps(response).encode("utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return

        self._send_not_found("Resource not found.")

    def do_OPTIONS(self) -> None:  # noqa: N802
        # Provide basic CORS-friendly headers
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Allow", "GET,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _extract_todo_id(self) -> Optional[int]:
        path, segments = self._parse_path()
        if len(segments) == 2 and segments[0] == "todos":
            return self._parse_int(segments[1])
        return None

    def _parse_path(self) -> Tuple[str, Tuple[str, ...]]:
        parsed = urlparse(self.path)
        path = parsed.path or "/"
        # Normalize path: remove duplicate slashes and trailing slash unless root
        norm = "/" + "/".join([s for s in path.split("/") if s])
        if norm == "":
            norm = "/"
        segments = tuple(s for s in norm.strip("/").split("/") if s)
        return norm, segments

    @staticmethod
    def _parse_int(value: str) -> Optional[int]:
        try:
            if value.startswith("+"):
                value = value[1:]
            return int(value, 10)
        except Exception:
            return None

    def _content_length(self) -> int:
        try:
            return int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return 0

    def _send_json(self, status: HTTPStatus, payload) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_not_found(self, message: str) -> None:
        self._send_json(HTTPStatus.NOT_FOUND, {"error": message})

    def log_message(self, format: str, *args) -> None:  # noqa: A003 - method name from base class
        # Override to include client address in logs and reduce verbosity if desired
        super().log_message(format, *args)


def run_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    """
    Start the HTTP server on the given host and port.
    """
    httpd = ThreadingHTTPServer((host, port), TodoRequestHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    # Optionally pre-populate with example todos for testing convenience
    STORE.add({"title": "Sample task 1", "completed": False})
    STORE.add({"title": "Sample task 2", "completed": True})

    host_env = os.environ.get("HOST", "127.0.0.1")
    port_env = os.environ.get("PORT", "8080")
    try:
        port_val = int(port_env)
    except ValueError:
        port_val = 8080

    print(f"Starting Todo API server on http://{host_env}:{port_val}")
    print("Endpoints:")
    print("  POST   /todos           - create a todo (JSON: {title, completed})")
    print("  GET    /todos           - list todos")
    print("  GET    /todos/{id}      - get a single todo")
    print("  DELETE /todos/{id}      - delete a todo (204 on success, 404 if not found)")
    run_server(host_env, port_val)