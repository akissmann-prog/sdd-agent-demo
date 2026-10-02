from flask import Blueprint, request, jsonify
from config import DB_PATH
from scrum_147 import (
    post_applications,
    get_applications,
    get_application_by_id,
    put_application,
    delete_application,
)

bp = Blueprint('scrum_147', __name__)


def _parse_json_body():
    """
    Parse JSON body; return dict, or (error_response, status) on invalid JSON.
    Empty body becomes {} to allow domain validation to handle required fields.
    """
    payload = request.get_json(silent=True)
    if payload is None:
        # If there is non-empty body but JSON couldn't be parsed, return 400
        data = request.get_data(cache=False, as_text=True)
        if data and data.strip():
            return {"message": "invalid JSON"}, 400
        payload = {}
    if not isinstance(payload, dict):
        return {"message": "invalid JSON"}, 400
    return payload


def _normalize_enums(payload: dict) -> dict:
    """
    Normalize enum-like fields to lowercase trimmed strings to avoid DB CHECK violations.
    """
    out = dict(payload)
    if "status" in out and out["status"] is not None:
        out["status"] = str(out["status"]).lower().strip()
    return out


@bp.get("/applications")
def list_applications():
    """List applications, optionally filtered by status via ?status=."""
    status = request.args.get("status")
    status_norm = None
    if status is not None:
        status_norm = str(status).lower().strip()
    code, body = get_applications(status=status_norm, db_path=DB_PATH)
    return jsonify(body), code


@bp.get("/applications/<app_id>")
def get_application(app_id: str):
    """Retrieve a single application by id."""
    code, body = get_application_by_id(app_id, db_path=DB_PATH)
    return jsonify(body), code


@bp.post("/applications")
def create_application():
    """Create a new application with required fields and sensible defaults."""
    parsed = _parse_json_body()
    if isinstance(parsed, tuple):
        body, code = parsed
        return jsonify(body), code
    payload = _normalize_enums(parsed)
    code, body = post_applications(payload, db_path=DB_PATH)
    return jsonify(body), code


@bp.put("/applications/<app_id>")
def update_application(app_id: str):
    """Update an existing application by id."""
    parsed = _parse_json_body()
    if isinstance(parsed, tuple):
        body, code = parsed
        return jsonify(body), code
    payload = _normalize_enums(parsed)
    code, body = put_application(app_id, payload, db_path=DB_PATH)
    return jsonify(body), code


@bp.delete("/applications/<app_id>")
def remove_application(app_id: str):
    """Delete an application by id."""
    code, body = delete_application(app_id, db_path=DB_PATH)
    if code == 204:
        return "", 204
    return jsonify(body), code


# Expose commonly expected blueprint variable name for the app loader
scrum_147_bp = bp