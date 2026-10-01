"""
Business logic module for managing tasks with SQLite persistence and a generated HTML dashboard.

This module provides pure functions to create, list (with optional filtering), retrieve,
update, and delete tasks. It also includes a function to generate a minimal single-page
dashboard that interacts with expected REST API endpoints (not implemented here).

Key features:
- SQLite schema: tasks(id, title, description, status, created_date)
- Status validation: only 'todo', 'doing', 'done' are allowed
- Convenience HTML generator for a dashboard consuming REST endpoints

Note: No HTTP server is implemented here. These functions are intended to be used by a web
layer that exposes REST endpoints mapping to these operations and serves the HTML.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

ALLOWED_STATUSES = {"todo", "doing", "done"}


def _get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'doing', 'done')),
            created_date TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def _row_to_task(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "title": str(row["title"]),
        "description": None if row["description"] is None else str(row["description"]),
        "status": str(row["status"]),
        "created_date": str(row["created_date"]),
    }


def validate_status(status: str) -> None:
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Allowed: {sorted(ALLOWED_STATUSES)}")


def create_task(
    title: str,
    description: Optional[str] = None,
    status: str = "todo",
    db_path: str = "demo.db",
) -> Dict[str, Any]:
    if title is None or not str(title).strip():
        raise ValueError("Title is required")
    if status is None:
        status = "todo"
    validate_status(status)

    with _get_connection(db_path) as conn:
        _ensure_schema(conn)
        cur = conn.execute(
            "INSERT INTO tasks (title, description, status) VALUES (?, ?, ?)",
            (title.strip(), description, status),
        )
        task_id = cur.lastrowid
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise RuntimeError("Failed to retrieve newly created task")
        return _row_to_task(row)


def get_task(task_id: int, db_path: str = "demo.db") -> Optional[Dict[str, Any]]:
    with _get_connection(db_path) as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return None if row is None else _row_to_task(row)


def list_tasks(status: Optional[str] = None, db_path: str = "demo.db") -> List[Dict[str, Any]]:
    with _get_connection(db_path) as conn:
        _ensure_schema(conn)
        if status is not None:
            validate_status(status)
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY id ASC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM tasks ORDER BY id ASC").fetchall()
        return [_row_to_task(r) for r in rows]


def update_task(
    task_id: int,
    title: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
    db_path: str = "demo.db",
) -> Dict[str, Any]:
    if title is None and description is None and status is None:
        raise ValueError("At least one field (title, description, status) must be provided")

    updates: List[str] = []
    params: List[Any] = []

    if title is not None:
        if not str(title).strip():
            raise ValueError("Title cannot be empty")
        updates.append("title = ?")
        params.append(title.strip())

    if description is not None:
        updates.append("description = ?")
        params.append(description)

    if status is not None:
        validate_status(status)
        updates.append("status = ?")
        params.append(status)

    params.append(task_id)

    with _get_connection(db_path) as conn:
        _ensure_schema(conn)
        cur = conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", params)
        if cur.rowcount == 0:
            raise KeyError(f"Task with id {task_id} not found")
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise RuntimeError("Task updated but could not be reloaded")
        return _row_to_task(row)


def delete_task(task_id: int, db_path: str = "demo.db") -> bool:
    with _get_connection(db_path) as conn:
        _ensure_schema(conn)
        cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cur.rowcount > 0


def get_dashboard_html() -> str:
    """
    Returns a minimal single-page dashboard HTML that expects the following REST API:
    - POST /tasks
    - GET /tasks (optional ?status=)
    - GET /tasks/:id
    - PUT /tasks/:id
    - DELETE /tasks/:id

    The page groups tasks by status and allows adding, updating status, and deleting tasks.
    """
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Tasks Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { --gap: 12px; --bg: #f7f7f8; --card: #ffffff; --border: #e2e2e6; --text: #1f2328; --muted: #6b7280; --accent:#2563eb; }
  body { margin: 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Noto Sans, 'Helvetica Neue', Arial, 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol'; color: var(--text); background: var(--bg); }
  header { padding: 16px; background: #fff; border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 10; }
  h1 { margin: 0; font-size: 20px; }
  .container { padding: 16px; }
  .board { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--gap); }
  .column { background: #fff; border: 1px solid var(--border); border-radius: 8px; display: flex; flex-direction: column; min-height: 200px; }
  .column h2 { margin: 0; padding: 12px; border-bottom: 1px solid var(--border); font-size: 16px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
  .list { padding: 12px; display: flex; flex-direction: column; gap: 8px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 10px; display: flex; flex-direction: column; gap: 8px; }
  .card-title { font-weight: 600; }
  .card-desc { color: var(--muted); white-space: pre-wrap; }
  .card-actions { display: flex; gap: 8px; align-items: center; }
  .status-select { padding: 6px; border: 1px solid var(--border); border-radius: 6px; background: #fff; }
  .btn { padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; background: #fff; cursor: pointer; }
  .btn:hover { background: #f3f4f6; }
  .btn-danger { color: #b91c1c; border-color: #fecaca; }
  .add-form { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
  .input, .textarea { padding: 8px; border: 1px solid var(--border); border-radius: 6px; background: #fff; font: inherit; }
  .input { width: 240px; }
  .textarea { flex: 1 1 320px; min-height: 40px; }
  .btn-primary { background: var(--accent); color: white; border-color: #1d4ed8; }
  .btn-primary:hover { background: #1d4ed8; }
  .muted { color: var(--muted); font-size: 12px; }
  @media (max-width: 800px) {
    .board { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<header>
  <h1>Tasks</h1>
</header>
<div class="container">
  <form id="addForm" class="add-form">
    <input class="input" id="titleInput" placeholder="Task title" required />
    <textarea class="textarea" id="descInput" placeholder="Description (optional)"></textarea>
    <button class="btn btn-primary" type="submit">Add Task</button>
    <span id="formMsg" class="muted"></span>
  </form>

  <div class="board" style="margin-top:16px;">
    <div class="column" data-col="todo">
      <h2>Todo</h2>
      <div class="list" id="todoList"></div>
    </div>
    <div class="column" data-col="doing">
      <h2>Doing</h2>
      <div class="list" id="doingList"></div>
    </div>
    <div class="column" data-col="done">
      <h2>Done</h2>
      <div class="list" id="doneList"></div>
    </div>
  </div>
</div>

<script>
  const $ = (sel) => document.querySelector(sel);
  const lists = {
    'todo': $('#todoList'),
    'doing': $('#doingList'),
    'done': $('#doneList'),
  };

  const API = {
    async list(status) {
      const url = status ? '/tasks?status=' + encodeURIComponent(status) : '/tasks';
      const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
      if (!res.ok) throw new Error('Failed to load tasks');
      return res.json();
    },
    async create(payload) {
      const res = await fetch('/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const msg = await safeError(res);
        throw new Error(msg || 'Failed to create task');
      }
      return res.json();
    },
    async update(id, payload) {
      const res = await fetch('/tasks/' + encodeURIComponent(id), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const msg = await safeError(res);
        throw new Error(msg || 'Failed to update task');
      }
      return res.json();
    },
    async remove(id) {
      const res = await fetch('/tasks/' + encodeURIComponent(id), { method: 'DELETE' });
      if (!res.ok) {
        const msg = await safeError(res);
        throw new Error(msg || 'Failed to delete task');
      }
      return true;
    }
  };

  async function safeError(res) {
    try {
      const data = await res.json();
      return data && (data.error || data.message);
    } catch (_) {
      return res.status + ' ' + res.statusText;
    }
  }

  function clearLists() {
    for (const k of Object.keys(lists)) lists[k].innerHTML = '';
  }

  function renderTasks(grouped) {
    clearLists();
    const order = ['todo', 'doing', 'done'];
    for (const status of order) {
      for (const t of (grouped[status] || [])) {
        lists[status].appendChild(taskCard(t));
      }
    }
  }

  function escapeText(text) {
    const span = document.createElement('span');
    span.textContent = text == null ? '' : String(text);
    return span.textContent;
  }

  function taskCard(task) {
    const card = document.createElement('div');
    card.className = 'card';
    card.dataset.id = task.id;

    const title = document.createElement('div');
    title.className = 'card-title';
    title.textContent = escapeText(task.title);

    const desc = document.createElement('div');
    desc.className = 'card-desc';
    desc.textContent = escapeText(task.description || '');

    const actions = document.createElement('div');
    actions.className = 'card-actions';

    const select = document.createElement('select');
    select.className = 'status-select';
    for (const s of ['todo', 'doing', 'done']) {
      const opt = document.createElement('option');
      opt.value = s;
      opt.textContent = s;
      if (s === task.status) opt.selected = true;
      select.appendChild(opt);
    }
    select.addEventListener('change', async (e) => {
      const newStatus = e.target.value;
      select.disabled = true;
      try {
        await API.update(task.id, { status: newStatus });
        await loadAndRender();
      } catch (err) {
        alert(err.message || String(err));
        select.value = task.status;
      } finally {
        select.disabled = false;
      }
    });

    const del = document.createElement('button');
    del.className = 'btn btn-danger';
    del.textContent = 'Delete';
    del.addEventListener('click', async () => {
      if (!confirm('Delete this task?')) return;
      del.disabled = true;
      try {
        await API.remove(task.id);
        await loadAndRender();
      } catch (err) {
        alert(err.message || String(err));
      } finally {
        del.disabled = false;
      }
    });

    actions.appendChild(select);
    actions.appendChild(del);

    card.appendChild(title);
    if ((task.description || '').trim() !== '') card.appendChild(desc);
    card.appendChild(actions);
    return card;
  }

  async function loadAndRender() {
    const tasks = await API.list();
    const grouped = { todo: [], doing: [], done: [] };
    for (const t of tasks) {
      if (!grouped[t.status]) grouped[t.status] = [];
      grouped[t.status].push(t);
    }
    renderTasks(grouped);
  }

  const addForm = document.getElementById('addForm');
  const titleInput = document.getElementById('titleInput');
  const descInput = document.getElementById('descInput');
  const formMsg = document.getElementById('formMsg');

  addForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const title = titleInput.value.trim();
    const description = descInput.value;
    if (!title) {
      formMsg.textContent = 'Title is required';
      return;
    }
    formMsg.textContent = 'Creating...';
    try {
      await API.create({ title, description });
      titleInput.value = '';
      descInput.value = '';
      formMsg.textContent = 'Created';
      await loadAndRender();
    } catch (err) {
      formMsg.textContent = err.message || String(err);
    } finally {
      setTimeout(() => { formMsg.textContent = ''; }, 1500);
    }
  });

  loadAndRender().catch(err => {
    console.error(err);
    alert('Failed to load tasks');
  });
</script>
</body>
</html>
"""