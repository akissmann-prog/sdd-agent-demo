from flask import Blueprint, jsonify, request
from config import DB_PATH
from scrum_136 import (
    create_application as _create_application,
    list_applications as _list_applications,
    get_application as _get_application,
    update_application as _update_application,
    delete_application as _delete_application,
)

bp = Blueprint("scrum_136", __name__)


def _json_error(status: int, error: str, details=None):
    body = {"error": error}
    if details is not None:
        body["details"] = details
    return jsonify(body), status


@bp.get("/applications")
def list_applications():
    """List all job applications, optionally filtered by status (?status=...)."""
    status = request.args.get("status")
    code, body = _list_applications(status=status, db_path=DB_PATH)
    return jsonify(body), code


@bp.get("/applications/<int:app_id>")
def get_application(app_id: int):
    """Retrieve a single job application by its ID."""
    code, body = _get_application(app_id, db_path=DB_PATH)
    return jsonify(body), code


@bp.post("/applications")
def create_application():
    """Create a new job application. Expects JSON with company, role, and optional fields."""
    payload = request.get_json(silent=True)
    if payload is None:
        return _json_error(400, "Bad Request", {"json": "Invalid or missing JSON body"})
    code, body = _create_application(payload, db_path=DB_PATH)
    return jsonify(body), code


@bp.put("/applications/<int:app_id>")
def update_application(app_id: int):
    """Update an existing job application by ID. Expects JSON with updatable fields."""
    payload = request.get_json(silent=True)
    if payload is None:
        return _json_error(400, "Bad Request", {"json": "Invalid or missing JSON body"})
    code, body = _update_application(app_id, payload, db_path=DB_PATH)
    return jsonify(body), code


@bp.delete("/applications/<int:app_id>")
def delete_application(app_id: int):
    """Delete a job application by its ID."""
    code, body = _delete_application(app_id, db_path=DB_PATH)
    if code == 204:
        return "", 204
    return jsonify(body), code