from flask import Blueprint, request, jsonify
from config import DB_PATH
from scrum_103 import (
    list_applications,
    get_application,
    add_application,
    update_application,
    delete_application,
    set_application_status,
    group_applications_by_status,
    error_to_message,
    ValidationError,
    NotFoundError,
)

bp = Blueprint('scrum_103', __name__)


@bp.route('/applications', methods=['GET'])
def applications_list():
    """List all applications, optionally ordered by query params."""
    try:
        order_by = request.args.get('order_by', 'applied_date')
        desc_param = (request.args.get('descending', 'true') or 'true').lower()
        descending = not (desc_param in ('0', 'false', 'no', 'off', 'asc'))

        apps = list_applications(db_path=DB_PATH, order_by=order_by, descending=descending)
        return jsonify([a.to_dict() for a in apps]), 200
    except Exception as e:
        return jsonify({"error": error_to_message(e)}), 500


@bp.route('/applications/<int:app_id>', methods=['GET'])
def applications_get(app_id: int):
    """Get a single application by id."""
    try:
        app = get_application(app_id, db_path=DB_PATH)
        return jsonify(app.to_dict()), 200
    except NotFoundError as e:
        return jsonify({"error": error_to_message(e)}), 404
    except Exception as e:
        return jsonify({"error": error_to_message(e)}), 500


@bp.route('/applications', methods=['POST'])
def applications_create():
    """Create a new application."""
    try:
        if not request.is_json:
            return jsonify({"error": "Request body must be JSON."}), 400
        data = request.get_json() or {}

        created = add_application(
            company=data.get('company'),
            role=data.get('role'),
            status=data.get('status'),
            applied_date=data.get('applied_date'),
            notes=data.get('notes'),
            db_path=DB_PATH,
        )
        resp = jsonify(created.to_dict())
        resp.status_code = 201
        resp.headers['Location'] = f"/applications/{created.id}"
        return resp
    except ValidationError as e:
        return jsonify({"error": error_to_message(e)}), 400
    except Exception as e:
        return jsonify({"error": error_to_message(e)}), 500


@bp.route('/applications/<int:app_id>', methods=['PUT'])
def applications_update(app_id: int):
    """Update fields of an application by id."""
    try:
        if not request.is_json:
            return jsonify({"error": "Request body must be JSON."}), 400
        data = request.get_json() or {}

        updated = update_application(
            app_id=app_id,
            company=data.get('company', None),
            role=data.get('role', None),
            status=data.get('status', None),
            applied_date=data.get('applied_date', None),
            notes=data.get('notes', None),
            db_path=DB_PATH,
        )
        return jsonify(updated.to_dict()), 200
    except ValidationError as e:
        return jsonify({"error": error_to_message(e)}), 400
    except NotFoundError as e:
        return jsonify({"error": error_to_message(e)}), 404
    except Exception as e:
        return jsonify({"error": error_to_message(e)}), 500


@bp.route('/applications/<int:app_id>', methods=['DELETE'])
def applications_delete(app_id: int):
    """Delete an application by id."""
    try:
        delete_application(app_id, db_path=DB_PATH)
        return '', 204
    except NotFoundError as e:
        return jsonify({"error": error_to_message(e)}), 404
    except Exception as e:
        return jsonify({"error": error_to_message(e)}), 500


@bp.route('/applications/<int:app_id>/status', methods=['PUT'])
def applications_set_status(app_id: int):
    """Update only the status of an application."""
    try:
        if not request.is_json:
            return jsonify({"error": "Request body must be JSON."}), 400
        data = request.get_json() or {}
        status = data.get('status', None)

        updated = set_application_status(app_id, status, db_path=DB_PATH)
        return jsonify(updated.to_dict()), 200
    except ValidationError as e:
        return jsonify({"error": error_to_message(e)}), 400
    except NotFoundError as e:
        return jsonify({"error": error_to_message(e)}), 404
    except Exception as e:
        return jsonify({"error": error_to_message(e)}), 500


@bp.route('/applications/grouped', methods=['GET'])
def applications_grouped():
    """List applications grouped by status."""
    try:
        apps = list_applications(db_path=DB_PATH)
        grouped = group_applications_by_status(apps)
        result = {k: [a.to_dict() for a in v] for k, v in grouped.items()}
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": error_to_message(e)}), 500