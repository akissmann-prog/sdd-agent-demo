from flask import Blueprint, jsonify, request, url_for, Response
from config import DB_PATH
from scrum_132 import (
    create_application,
    list_applications,
    get_application_by_id,
    update_application,
    delete_application as logic_delete_application,
    ensure_initialized,
    ValidationError,
    NotFoundError,
    ALLOWED_STATUSES,
)

bp = Blueprint('scrum_132', __name__)


@bp.record_once
def _init(state):
    # Initialize database schema when the blueprint is registered.
    try:
        ensure_initialized(DB_PATH)
    except Exception:
        # If initialization fails here, first actual request that touches the DB will still ensure schema.
        pass


@bp.get("/applications")
def list_applications_endpoint():
    """List all applications, optionally filtered by ?status=applied|interviewing|offer|rejected."""
    status = request.args.get("status", default=None, type=str)
    # Treat empty status as no filter to be forgiving.
    if status is not None and status.strip() == "":
        status = None
    try:
        apps = list_applications(status=status, db_path=DB_PATH)
        return jsonify(apps), 200
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@bp.get("/applications/<int:app_id>")
def get_application(app_id: int):
    """Fetch a single application by id."""
    try:
        app = get_application_by_id(app_id, db_path=DB_PATH)
        return jsonify(app), 200
    except NotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@bp.post("/applications")
def create_application_endpoint():
    """Create a new application. Defaults: status='applied', applied_date=today (UTC) if omitted."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body."}), 400
    try:
        created = create_application(data, db_path=DB_PATH)
        location = url_for("scrum_132.get_application", app_id=created["id"])
        return jsonify(created), 201, {"Location": location}
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@bp.put("/applications/<int:app_id>")
def update_application_endpoint(app_id: int):
    """Update an application by id with provided fields."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body."}), 400
    try:
        updated = update_application(app_id, data, db_path=DB_PATH)
        return jsonify(updated), 200
    except NotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@bp.delete("/applications/<int:app_id>")
def delete_application_endpoint(app_id: int):
    """Delete an application by id."""
    try:
        logic_delete_application(app_id, db_path=DB_PATH)
        return "", 204
    except NotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@bp.get("/applications/dashboard")
def applications_dashboard():
    """Serve the HTML dashboard for managing applications."""
    # Build a simple HTML page that uses fetch to call the REST API and updates UI dynamically.
    statuses_js_array = "[" + ",".join(f"'{s}'" for s in ALLOWED_STATUSES) + "]"
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Job Applications Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 20px; line-height: 1.4; }}
    h1 {{ margin-bottom: 0.2rem; }}
    .subtitle {{ color: #666; margin-top: 0; }}
    .groups {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }}
    .group {{ border: 1px solid #ddd; border-radius: 8px; padding: 12px; background: #fafafa; }}
    .group h2 {{ font-size: 1rem; margin: 0 0 8px; text-transform: capitalize; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 6px; border-bottom: 1px solid #eee; vertical-align: top; }}
    tr:last-child td {{ border-bottom: none; }}
    .row-actions button {{ margin-right: 4px; }}
    .status-select {{ width: 100%; }}
    .msg {{ margin: 10px 0; padding: 8px 10px; border-radius: 6px; display: none; }}
    .msg.show {{ display: block; }}
    .msg.error {{ background: #fdecea; color: #611a15; border: 1px solid #f5c2be; }}
    .msg.success {{ background: #edf7ed; color: #1e4620; border: 1px solid #cce6cc; }}
    form#create-form {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; align-items: end; margin-bottom: 20px; }}
    form#create-form input, form#create-form select {{ padding: 6px; }}
    form#create-form .notes {{ grid-column: span 2; }}
    form#create-form .company {{ grid-column: span 2; }}
    form#create-form .role {{ grid-column: span 2; }}
    form#create-form button {{ padding: 8px 10px; }}
    .muted {{ color: #777; font-size: 0.9em; }}
    .nowrap {{ white-space: nowrap; }}
  </style>
</head>
<body>
  <h1>Job Applications</h1>
  <p class="subtitle">Track, update status, edit, and delete your job applications.</p>

  <div id="msg" class="msg"></div>

  <form id="create-form" autocomplete="off">
    <div class="company">
      <label for="company">Company</label><br />
      <input type="text" id="company" name="company" placeholder="Acme Corp" required />
    </div>
    <div class="role">
      <label for="role">Role</label><br />
      <input type="text" id="role" name="role" placeholder="Software Engineer" required />
    </div>
    <div>
      <label for="status">Status</label><br />
      <select id="status" name="status">
        <option value="">(default: applied)</option>
      </select>
    </div>
    <div class="nowrap">
      <label for="applied_date">Applied date</label><br />
      <input type="date" id="applied_date" name="applied_date" />
    </div>
    <div class="notes">
      <label for="notes">Notes</label><br />
      <input type="text" id="notes" name="notes" placeholder="Notes (optional)" />
    </div>
    <div>
      <button type="submit">Add</button>
    </div>
  </form>

  <div class="groups">
    <div class="group" data-status="applied">
      <h2>Applied</h2>
      <table>
        <thead>
          <tr><th>Company</th><th>Role</th><th>Date</th><th>Notes</th><th>Status</th><th>Actions</th></tr>
        </thead>
        <tbody id="tbody-applied"></tbody>
      </table>
    </div>
    <div class="group" data-status="interviewing">
      <h2>Interviewing</h2>
      <table>
        <thead>
          <tr><th>Company</th><th>Role</th><th>Date</th><th>Notes</th><th>Status</th><th>Actions</th></tr>
        </thead>
        <tbody id="tbody-interviewing"></tbody>
      </table>
    </div>
    <div class="group" data-status="offer">
      <h2>Offer</h2>
      <table>
        <thead>
          <tr><th>Company</th><th>Role</th><th>Date</th><th>Notes</th><th>Status</th><th>Actions</th></tr>
        </thead>
        <tbody id="tbody-offer"></tbody>
      </table>
    </div>
    <div class="group" data-status="rejected">
      <h2>Rejected</h2>
      <table>
        <thead>
          <tr><th>Company</th><th>Role</th><th>Date</th><th>Notes</th><th>Status</th><th>Actions</th></tr>
        </thead>
        <tbody id="tbody-rejected"></tbody>
      </table>
    </div>
  </div>

<script>
  const ALLOWED_STATUSES = {statuses_js_array};
  function qs(sel, el=document) {{ return el.querySelector(sel); }}
  function qsa(sel, el=document) {{ return Array.from(el.querySelectorAll(sel)); }}

  function showMsg(text, type='success', ms=3000) {{
    const box = qs('#msg');
    box.textContent = text;
    box.className = 'msg show ' + (type === 'error' ? 'error' : 'success');
    if (ms > 0) {{
      setTimeout(() => {{
        box.className = 'msg';
        box.textContent = '';
      }}, ms);
    }}
  }}

  function api(url, options={{}}) {{
    const headers = options.headers || {{}};
    if (options.body && !(options.body instanceof FormData)) {{
      headers['Content-Type'] = 'application/json';
    }}
    return fetch(url, {{ ...options, headers }})
      .then(async (res) => {{
        if (res.status === 204) return {{ ok: res.ok, status: res.status }};
        const data = await res.json().catch(() => ({{}}));
        if (!res.ok) {{
          const errMsg = (data && data.error) ? data.error : 'Request failed';
          throw new Error(errMsg);
        }}
        return data;
      }});
  }}

  function statusOptions(selected='') {{
    return ['<option value="">--</option>'].concat(ALLOWED_STATUSES.map(s => {{
      return `<option value="${{s}}" ${{s===selected?'selected':''}}>${{s}}</option>`;
    }})).join('');
  }}

  function renderAppRow(app) {{
    const notes = app.notes != null ? escapeHtml(app.notes) : '';
    return `
      <tr data-id="${{app.id}}">
        <td class="company"><span class="view">${{escapeHtml(app.company)}}</span><input class="edit" type="text" value="${{escapeHtml(app.company)}}" style="display:none; width: 100%"></td>
        <td class="role"><span class="view">${{escapeHtml(app.role)}}</span><input class="edit" type="text" value="${{escapeHtml(app.role)}}" style="display:none; width: 100%"></td>
        <td class="applied_date nowrap"><span class="view">${{escapeHtml(app.applied_date)}}</span><input class="edit" type="date" value="${{escapeHtml(app.applied_date)}}" style="display:none"></td>
        <td class="notes"><span class="view">${{notes}}</span><input class="edit" type="text" value="${{notes}}" style="display:none; width: 100%"></td>
        <td class="status">
          <select class="status-select">${{statusOptions(app.status)}}</select>
        </td>
        <td class="row-actions nowrap">
          <button type="button" class="edit-btn">Edit</button>
          <button type="button" class="save-btn" style="display:none;">Save</button>
          <button type="button" class="cancel-btn" style="display:none;">Cancel</button>
          <button type="button" class="delete-btn">Delete</button>
        </td>
      </tr>
    `;
  }}

  function escapeHtml(str) {{
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }}

  function renderGroups(apps) {{
    // Clear all
    ALLOWED_STATUSES.forEach(s => {{
      const tbody = qs('#tbody-' + s);
      tbody.innerHTML = '';
    }});
    // Group and render
    apps.forEach(app => {{
      const tbody = qs('#tbody-' + app.status);
      if (tbody) {{
        tbody.insertAdjacentHTML('beforeend', renderAppRow(app));
      }}
    }});
  }}

  function fetchAndRender() {{
    api('/applications', {{ method: 'GET' }})
      .then(apps => {{
        renderGroups(apps);
      }})
      .catch(err => {{
        showMsg(err.message || 'Failed to load applications', 'error', 5000);
      }});
  }}

  function setCreateStatusOptions() {{
    const sel = qs('#status');
    sel.innerHTML = '<option value="">(default: applied)</option>' + ALLOWED_STATUSES.map(s => `<option value="${{s}}">${{s}}</option>`).join('');
  }}

  function onCreateSubmit(e) {{
    e.preventDefault();
    const form = e.currentTarget;
    const payload = {{
      company: form.company.value.trim(),
      role: form.role.value.trim(),
    }};
    if (form.status.value) payload.status = form.status.value;
    if (form.applied_date.value) payload.applied_date = form.applied_date.value;
    if (form.notes.value.trim() !== '') payload.notes = form.notes.value;

    api('/applications', {{
      method: 'POST',
      body: JSON.stringify(payload),
    }}).then(app => {{
      showMsg('Created application #' + app.id);
      form.reset();
      fetchAndRender();
    }}).catch(err => {{
      showMsg(err.message || 'Create failed', 'error', 5000);
    }});
  }}

  function toggleEdit(row, editing) {{
    qsa('.view', row).forEach(el => el.style.display = editing ? 'none' : '');
    qsa('.edit', row).forEach(el => el.style.display = editing ? '' : 'none');
    qs('.edit-btn', row).style.display = editing ? 'none' : '';
    qs('.save-btn', row).style.display = editing ? '' : 'none';
    qs('.cancel-btn', row).style.display = editing ? '' : 'none';
  }}

  function handleRowAction(e) {{
    const target = e.target;
    const row = target.closest('tr[data-id]');
    if (!row) return;
    const id = row.getAttribute('data-id');

    if (target.classList.contains('edit-btn')) {{
      toggleEdit(row, true);
    }} else if (target.classList.contains('cancel-btn')) {{
      // Reset inputs to current view values
      const companyView = qs('.company .view', row).textContent;
      const roleView = qs('.role .view', row).textContent;
      const dateView = qs('.applied_date .view', row).textContent;
      const notesView = qs('.notes .view', row).textContent;
      qs('.company .edit', row).value = companyView;
      qs('.role .edit', row).value = roleView;
      qs('.applied_date .edit', row).value = dateView;
      qs('.notes .edit', row).value = notesView === '' ? '' : notesView;
      toggleEdit(row, false);
    }} else if (target.classList.contains('save-btn')) {{
      const payload = {{
        company: qs('.company .edit', row).value.trim(),
        role: qs('.role .edit', row).value.trim(),
        applied_date: qs('.applied_date .edit', row).value,
        notes: (qs('.notes .edit', row).value.trim() === '' ? null : qs('.notes .edit', row).value),
        status: qs('.status-select', row).value || undefined,
      }};
      // Remove undefined so we don't send empty status
      Object.keys(payload).forEach(k => payload[k] === undefined && delete payload[k]);
      api(`/applications/${{id}}`, {{
        method: 'PUT',
        body: JSON.stringify(payload),
      }}).then(app => {{
        // Update row view
        qs('.company .view', row).textContent = app.company;
        qs('.role .view', row).textContent = app.role;
        qs('.applied_date .view', row).textContent = app.applied_date;
        qs('.notes .view', row).textContent = app.notes || '';
        // If status changed, re-render all to move row
        fetchAndRender();
        showMsg('Updated application #' + id);
      }}).catch(err => {{
        showMsg(err.message || 'Update failed', 'error', 5000);
      }}).finally(() => {{
        toggleEdit(row, false);
      }});
    }} else if (target.classList.contains('delete-btn')) {{
      if (!confirm('Delete application #' + id + '?')) return;
      api(`/applications/${{id}}`, {{ method: 'DELETE' }})
        .then(() => {{
          showMsg('Deleted application #' + id);
          // Remove row from DOM
          row.remove();
        }})
        .catch(err => {{
          showMsg(err.message || 'Delete failed', 'error', 5000);
        }});
    }}
  }}

  function handleStatusChange(e) {{
    const sel = e.target;
    if (!sel.classList.contains('status-select')) return;
    const row = sel.closest('tr[data-id]');
    const id = row.getAttribute('data-id');
    const newStatus = sel.value;
    if (!newStatus) return; // ignore empty selection
    api(`/applications/${{id}}`, {{
      method: 'PUT',
      body: JSON.stringify({{ status: newStatus }}),
    }}).then(app => {{
      showMsg('Status updated to ' + app.status + ' for #' + id);
      fetchAndRender();
    }}).catch(err => {{
      showMsg(err.message || 'Status update failed', 'error', 5000);
      // Revert selection if failed
      // Fetch current record to restore
      api(`/applications/${{id}}`, {{ method: 'GET' }})
        .then(app => {{
          sel.value = app.status;
        }})
        .catch(() => {{}});
    }});
  }}

  document.addEventListener('DOMContentLoaded', () => {{
    setCreateStatusOptions();
    qs('#create-form').addEventListener('submit', onCreateSubmit);
    document.body.addEventListener('click', handleRowAction);
    document.body.addEventListener('change', handleStatusChange);
    fetchAndRender();
  }});
</script>
</body>
</html>"""
    return Response(html, mimetype="text/html")