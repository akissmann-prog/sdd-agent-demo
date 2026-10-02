from flask import Blueprint, request, jsonify
from config import DB_PATH
from scrum_114 import (
    get_applications,
    get_application_by_id,
    create_application,
    update_application,
    delete_application,
    group_applications_by_status,
    get_allowed_statuses,
    ValidationError,
    NotFoundError,
)

bp = Blueprint('scrum_114', __name__)


@bp.errorhandler(ValidationError)
def handle_validation_error(err: ValidationError):
    response = {"error": err.message}
    if getattr(err, "field_errors", None):
        response["field_errors"] = err.field_errors
    return jsonify(response), 400


@bp.errorhandler(NotFoundError)
def handle_not_found_error(err: NotFoundError):
    return jsonify({"error": str(err)}), 404


@bp.errorhandler(Exception)
def handle_unexpected_error(err: Exception):
    return jsonify({"error": "Internal server error"}), 500


@bp.get("/applications")
def list_applications():
    """List all applications ordered by applied_date DESC then id DESC."""
    apps = get_applications(db_path=DB_PATH)
    return jsonify(apps), 200


@bp.get("/applications/grouped")
def list_applications_grouped():
    """List applications grouped by status."""
    grouped = group_applications_by_status(db_path=DB_PATH)
    return jsonify(grouped), 200


@bp.get("/applications/statuses")
def allowed_statuses():
    """Return allowed application statuses."""
    statuses = get_allowed_statuses()
    return jsonify({"statuses": list(statuses)}), 200


@bp.get("/applications/<int:app_id>")
def get_application(app_id: int):
    """Get a single application by id."""
    app = get_application_by_id(app_id, db_path=DB_PATH)
    return jsonify(app), 200


@bp.post("/applications")
def create_app():
    """Create a new application. JSON body required."""
    if not request.is_json:
        return jsonify({"error": "Request content-type must be application/json"}), 400
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON body"}), 400
    app = create_application(data, db_path=DB_PATH)
    return jsonify(app), 201


@bp.put("/applications/<int:app_id>")
def update_app(app_id: int):
    """Update an existing application by id. Partial updates allowed. JSON body required."""
    if not request.is_json:
        return jsonify({"error": "Request content-type must be application/json"}), 400
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON body"}), 400
    app = update_application(app_id, data, db_path=DB_PATH)
    return jsonify(app), 200


@bp.delete("/applications/<int:app_id>")
def delete_app(app_id: int):
    """Delete an application by id."""
    delete_application(app_id, db_path=DB_PATH)
    return jsonify({"status": "deleted", "id": app_id}), 200