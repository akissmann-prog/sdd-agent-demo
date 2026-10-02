from flask import Blueprint, request, jsonify
from config import DB_PATH
from scrum_121 import (
    create_application as create_application_logic,
    list_applications as list_applications_logic,
    get_application_by_id as get_application_by_id_logic,
    update_application as update_application_logic,
    delete_application as delete_application_logic,
    validate_filter_status,
    ValidationError,
    NotFoundError,
)

bp = Blueprint('scrum_121', __name__)


@bp.get("/applications")
def list_applications_route():
    """List job applications, optionally filtered by status."""
    try:
        status = request.args.get("status")
        status_norm = validate_filter_status(status)
        apps = list_applications_logic(status=status_norm, db_path=DB_PATH)
        return jsonify(apps), 200
    except ValidationError as ve:
        return jsonify({"error": ve.message}), ve.status
    except Exception as exc:
        return jsonify({"error": "Internal server error"}), 500


@bp.get("/applications/<int:app_id>")
def get_application_route(app_id: int):
    """Retrieve a single job application by id."""
    try:
        app = get_application_by_id_logic(app_id, db_path=DB_PATH)
        if app is None:
            return jsonify({"error": f"Application with id {app_id} not found"}), 404
        return jsonify(app), 200
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@bp.post("/applications")
def create_application_route():
    """Create a new job application."""
    try:
        data = request.get_json(silent=True)
        if data is None:
            return jsonify({"error": "Request body must be JSON"}), 400

        app = create_application_logic(
            company=data.get("company"),
            role=data.get("role"),
            status=data.get("status"),
            applied_date=data.get("applied_date"),
            notes=data.get("notes"),
            db_path=DB_PATH,
        )
        return jsonify(app), 201
    except ValidationError as ve:
        return jsonify({"error": ve.message}), ve.status
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@bp.put("/applications/<int:app_id>")
def update_application_route(app_id: int):
    """Update an existing job application."""
    try:
        data = request.get_json(silent=True)
        if data is None:
            return jsonify({"error": "Request body must be JSON"}), 400

        app = update_application_logic(
            app_id=app_id,
            company=data.get("company"),
            role=data.get("role"),
            status=data.get("status"),
            applied_date=data.get("applied_date"),
            notes=data.get("notes"),
            db_path=DB_PATH,
        )
        return jsonify(app), 200
    except ValidationError as ve:
        return jsonify({"error": ve.message}), ve.status
    except NotFoundError as ne:
        return jsonify({"error": ne.message}), ne.status
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@bp.delete("/applications/<int:app_id>")
def delete_application_route(app_id: int):
    """Delete a job application by id."""
    try:
        deleted = delete_application_logic(app_id, db_path=DB_PATH)
        if not deleted:
            return jsonify({"error": f"Application with id {app_id} not found"}), 404
        return "", 204
    except Exception:
        return jsonify({"error": "Internal server error"}), 500