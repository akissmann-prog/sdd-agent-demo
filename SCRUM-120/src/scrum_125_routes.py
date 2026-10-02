from flask import Blueprint, request, jsonify, make_response
from config import DB_PATH
from scrum_125 import (
    list_applications,
    group_applications_by_status,
    get_application,
    create_application,
    update_application,
    delete_application,
    change_status,
    get_statuses,
    AppError,
)

bp = Blueprint('scrum_125', __name__)


@bp.errorhandler(AppError)
def handle_app_error(err: AppError):
    return jsonify({"error": err.message}), err.status_code


@bp.get("/")
def dashboard():
    """
    Serve the single-page dashboard HTML.
    """
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Job Applications Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 0; background: #fafafa; color: #222; }
  header { background: #2c3e50; color: white; padding: 1rem; }
  main { padding: 1rem; max-width: 1100px; margin: 0 auto; }
  .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; }
  .column { background: white; border: 1px solid #e3e3e3; border-radius: 8px; display: flex; flex-direction: column; min-height: 260px; }
  .column h2 { font-size: 1rem; margin: 0; padding: 0.75rem 0.75rem; border-bottom: 1px solid #eee; text-transform: capitalize; }
  .list { padding: 0.5rem; display: flex; flex-direction: column; gap: 0.5rem; }
  .empty { color: #777; font-size: 0.9rem; border: 1px dashed #ddd; border-radius: 6px; padding: 0.75rem; text-align: center; }
  .row { border: 1px solid #eee; border-radius: 6px; padding: 0.5rem; background: #fff; }
  .row-header { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }
  .row-title { font-weight: 600; }
  .meta { font-size: 0.85rem; color: #555; display: flex; gap: 0.75rem; margin: 0.25rem 0; flex-wrap: wrap; }
  .actions { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
  button, select, input, textarea { font: inherit; }
  button { cursor: pointer; border: 1px solid #ccc; background: #f8f8f8; border-radius: 4px; padding: 0.25rem 0.5rem; }
  button.primary { background: #2ecc71; color: white; border-color: #2ecc71; }
  button.danger { background: #e74c3c; color: white; border-color: #e74c3c; }
  .edit-form { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.5rem; margin-top: 0.5rem; }
  .edit-form .full { grid-column: 1 / -1; }
  .edit-form label { display: flex; flex-direction: column; font-size: 0.85rem; gap: 0.25rem; }
  .error { color: #b00020; background: #fde7eb; border: 1px solid #f5c4cd; padding: 0.5rem; border-radius: 6px; margin: 0.5rem 0; }
  .success { color: #155724; background: #d4edda; border: 1px solid #c3e6cb; padding: 0.5rem; border-radius: 6px; margin: 0.5rem 0; }
  .toolbar { background: white; border: 1px solid #e3e3e3; border-radius: 8px; padding: 0.75rem; margin-bottom: 1rem; }
  .toolbar h3 { margin-top: 0; }
  .small { font-size: 0.8rem; color: #666; }
  @media (max-width: 900px) { .grid { grid-template-columns: repeat(2, 1fr); } }
  @media (max-width: 600px) { .grid { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<header>
  <h1>Job Applications Dashboard</h1>
</header>
<main>
  <section class="toolbar" aria-labelledby="add-form-title">
    <h3 id="add-form-title">Add New Application</h3>
    <div id="add-error" class="error" role="alert" style="display:none;"></div>
    <form id="add-form" aria-describedby="add-help">
      <div class="edit-form">
        <label>
          Company<span class="small"> (required)</span>
          <input id="add-company" name="company" type="text" required aria-required="true" />
        </label>
        <label>
          Role<span class="small"> (required)</span>
          <input id="add-role" name="role" type="text" required aria-required="true" />
        </label>
        <label>
          Status
          <select id="add-status" name="status"></select>
        </label>
        <label>
          Applied Date
          <input id="add-date" name="applied_date" type="date" pattern="\\d{4}-\\d{2}-\\d{2}" />
        </label>
        <label class="full">
          Notes
          <textarea id="add-notes" name="notes" rows="2"></textarea>
        </label>
        <div class="full">
          <button type="submit" class="primary">Add Application</button>
        </div>
      </div>
      <div id="add-help" class="small">Status defaults to "applied" and date defaults to today if left empty.</div>
    </form>
  </section>

  <div id="global-error" class="error" role="alert" style="display:none;"></div>

  <section class="grid" id="grid" aria-live="polite"></section>
</main>

<script>
(function(){
  const state = {
    statuses: [],
    grouped: {},
  };

  const els = {
    grid: document.getElementById('grid'),
    globalError: document.getElementById('global-error'),
    addForm: document.getElementById('add-form'),
    addError: document.getElementById('add-error'),
    addCompany: document.getElementById('add-company'),
    addRole: document.getElementById('add-role'),
    addStatus: document.getElementById('add-status'),
    addDate: document.getElementById('add-date'),
    addNotes: document.getElementById('add-notes'),
  };

  function today() {
    const d = new Date();
    const m = String(d.getMonth()+1).padStart(2,'0');
    const day = String(d.getDate()).padStart(2,'0');
    return d.getFullYear() + '-' + m + '-' + day;
  }

  function showError(el, msg) {
    el.textContent = msg;
    el.style.display = 'block';
  }

  function clearError(el) {
    el.textContent = '';
    el.style.display = 'none';
  }

  async function api(path, options = {}) {
    const resp = await fetch(path, Object.assign({
      headers: { 'Content-Type': 'application/json' }
    }, options));
    let payload = null;
    const ct = resp.headers.get('content-type') || '';
    if (ct.includes('application/json')) {
      payload = await resp.json();
    } else {
      payload = await resp.text();
    }
    if (!resp.ok) {
      const msg = payload && payload.error ? payload.error : (typeof payload === 'string' ? payload : 'Request failed');
      throw new Error(msg);
    }
    return payload;
  }

  function createColumn(status) {
    const col = document.createElement('div');
    col.className = 'column';
    const h2 = document.createElement('h2');
    h2.textContent = status;
    col.appendChild(h2);
    const list = document.createElement('div');
    list.className = 'list';
    list.id = `list-${status}`;
    col.appendChild(list);
    return col;
  }

  function render() {
    els.grid.innerHTML = '';
    for (const status of state.statuses) {
      const col = createColumn(status);
      const list = col.querySelector('.list');
      const apps = state.grouped[status] || [];
      if (!apps.length) {
        const empty = document.createElement('div');
        empty.className = 'empty';
        empty.textContent = 'No applications in this status.';
        list.appendChild(empty);
      } else {
        for (const app of apps) list.appendChild(renderRow(app));
      }
      els.grid.appendChild(col);
    }
  }

  function renderRow(app) {
    const div = document.createElement('div');
    div.className = 'row';
    div.dataset.id = app.id;

    const header = document.createElement('div');
    header.className = 'row-header';
    const title = document.createElement('div');
    title.className = 'row-title';
    title.textContent = `${app.company} — ${app.role}`;
    header.appendChild(title);

    const actions = document.createElement('div');
    actions.className = 'actions';

    const statusSel = document.createElement('select');
    for (const s of state.statuses) {
      const opt = document.createElement('option');
      opt.value = s;
      opt.textContent = s;
      if (s === app.status) opt.selected = true;
      statusSel.appendChild(opt);
    }
    statusSel.addEventListener('change', async () => {
      try {
        await api(`applications/${app.id}`, { method: 'PUT', body: JSON.stringify({ status: statusSel.value }) });
        await refresh();
      } catch (e) {
        alert(e.message);
        statusSel.value = app.status;
      }
    });
    actions.appendChild(statusSel);

    const editBtn = document.createElement('button');
    editBtn.textContent = 'Edit';
    editBtn.addEventListener('click', () => toggleEdit(div, app));
    actions.appendChild(editBtn);

    const delBtn = document.createElement('button');
    delBtn.textContent = 'Delete';
    delBtn.className = 'danger';
    delBtn.addEventListener('click', async () => {
      if (!confirm('Delete this application?')) return;
      try {
        await api(`applications/${app.id}`, { method: 'DELETE' });
        await refresh();
      } catch (e) {
        alert(e.message);
      }
    });
    actions.appendChild(delBtn);

    header.appendChild(actions);
    div.appendChild(header);

    const meta = document.createElement('div');
    meta.className = 'meta';
    const statusSpan = document.createElement('span');
    statusSpan.textContent = `Status: ${app.status}`;
    const dateSpan = document.createElement('span');
    dateSpan.textContent = `Applied: ${app.applied_date}`;
    meta.appendChild(statusSpan);
    meta.appendChild(dateSpan);
    div.appendChild(meta);

    if (app.notes) {
      const notes = document.createElement('div');
      notes.className = 'small';
      notes.textContent = app.notes;
      div.appendChild(notes);
    }

    return div;
  }

  function toggleEdit(row, app) {
    const existing = row.querySelector('.edit-form');
    if (existing) {
      existing.remove();
      return;
    }

    const form = document.createElement('div');
    form.className = 'edit-form';
    form.innerHTML = `
      <div class="full error" role="alert" style="display:none;"></div>
      <label>Company<input type="text" name="company" value="${escapeHtml(app.company)}" required></label>
      <label>Role<input type="text" name="role" value="${escapeHtml(app.role)}" required></label>
      <label>Status>
        <select name="status">
          ${state.statuses.map(s => `<option value="${s}" ${s===app.status?'selected':''}>${s}</option>`).join('')}
        </select>
      </label>
      <label>Applied Date<input type="date" name="applied_date" value="${app.applied_date}" pattern="\\d{4}-\\d{2}-\\d{2}"></label>
      <label class="full">Notes<textarea name="notes" rows="2">${escapeHtml(app.notes || '')}</textarea></label>
      <div class="full actions">
        <button type="button" class="primary">Save</button>
        <button type="button">Cancel</button>
      </div>
    `;
    const err = form.querySelector('.error');
    const btns = form.querySelectorAll('button');
    const saveBtn = btns[0];
    const cancelBtn = btns[1];

    cancelBtn.addEventListener('click', () => form.remove());
    saveBtn.addEventListener('click', async () => {
      clearError(err);
      const patch = {
        company: form.querySelector('[name="company"]').value.trim(),
        role: form.querySelector('[name="role"]').value.trim(),
        status: form.querySelector('[name="status"]').value,
        applied_date: form.querySelector('[name="applied_date"]').value.trim(),
        notes: form.querySelector('[name="notes"]').value,
      };
      if (!patch.company) return showError(err, 'company is required');
      if (!patch.role) return showError(err, 'role is required');
      if (!/\\d{4}-\\d{2}-\\d{2}/.test(patch.applied_date)) return showError(err, 'applied_date must be YYYY-MM-DD');
      try {
        await api(`applications/${app.id}`, { method: 'PUT', body: JSON.stringify(patch) });
        await refresh();
      } catch (e) {
        showError(err, e.message);
      }
    });

    row.appendChild(form);
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  }

  async function refresh() {
    clearError(els.globalError);
    try {
      const grouped = await api('applications/grouped');
      state.grouped = grouped;
      render();
    } catch (e) {
      showError(els.globalError, e.message);
    }
  }

  async function init() {
    try {
      const statuses = await api('applications/statuses');
      state.statuses = statuses.statuses || [];
      // Populate add form statuses
      els.addStatus.innerHTML = state.statuses.map(s => `<option value="${s}">${s}</option>`).join('');
      // defaults
      els.addStatus.value = 'applied';
      els.addDate.value = today();
      await refresh();
    } catch (e) {
      showError(els.globalError, e.message);
    }
  }

  els.addForm.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    clearError(els.addError);
    const payload = {
      company: els.addCompany.value.trim(),
      role: els.addRole.value.trim(),
      status: els.addStatus.value || 'applied',
      applied_date: els.addDate.value.trim() || today(),
      notes: els.addNotes.value,
    };
    if (!payload.company) return showError(els.addError, 'company is required');
    if (!payload.role) return showError(els.addError, 'role is required');
    if (!/\\d{4}-\\d{2}-\\d{2}/.test(payload.applied_date)) return showError(els.addError, 'applied_date must be YYYY-MM-DD');
    try {
      await api('applications', { method: 'POST', body: JSON.stringify(payload) });
      els.addCompany.value = '';
      els.addRole.value = '';
      els.addStatus.value = 'applied';
      els.addDate.value = today();
      els.addNotes.value = '';
      await refresh();
    } catch (e) {
      showError(els.addError, e.message);
    }
  });

  init();
})();
</script>
</body>
</html>
    """
    resp = make_response(html, 200)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


@bp.get("/applications")
def list_all_applications():
    """
    List all applications as a flat list.
    """
    apps = list_applications(DB_PATH)
    return jsonify(apps), 200


@bp.get("/applications/grouped")
def list_applications_grouped():
    """
    List applications grouped by status.
    """
    grouped = group_applications_by_status(DB_PATH)
    return jsonify(grouped), 200


@bp.get("/applications/statuses")
def list_statuses():
    """
    Get the list of valid statuses.
    """
    statuses = list(get_statuses())
    return jsonify({"statuses": statuses}), 200


@bp.get("/applications/<app_id>")
def get_one_application(app_id: str):
    """
    Retrieve a single application by ID.
    """
    app = get_application(app_id, DB_PATH)
    return jsonify(app), 200


@bp.post("/applications")
def create_new_application():
    """
    Create a new application. Expects JSON body.
    """
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be JSON"}), 400
    app = create_application(data, DB_PATH)
    return jsonify(app), 201


@bp.put("/applications/<app_id>")
def update_one_application(app_id: str):
    """
    Update an existing application. Expects JSON body with fields to update.
    """
    patch = request.get_json(silent=True)
    if patch is None:
        return jsonify({"error": "Request body must be JSON"}), 400
    app = update_application(app_id, patch, DB_PATH)
    return jsonify(app), 200


@bp.put("/applications/<app_id>/status")
def update_application_status(app_id: str):
    """
    Change only the status of an application. Expects JSON body: {"status": "..."}.
    """
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({"error": "Request body must be JSON"}), 400
    status = body.get("status")
    if not isinstance(status, str):
        return jsonify({"error": "status must be a string"}), 422
    app = change_status(app_id, status, DB_PATH)
    return jsonify(app), 200


@bp.delete("/applications/<app_id>")
def delete_one_application(app_id: str):
    """
    Delete an application by ID.
    """
    delete_application(app_id, DB_PATH)
    return jsonify({"deleted": True}), 200