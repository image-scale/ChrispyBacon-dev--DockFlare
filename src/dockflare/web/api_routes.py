"""
API routes for the Flask application.

Provides REST API endpoints for rule management and system status.
"""

from flask import jsonify, request, current_app
from flask_login import login_required, current_user

from . import api_blueprint
from ..app import limiter


@api_blueprint.route("/status")
def api_status():
    """Get API status."""
    return jsonify({
        "status": "ok",
        "version": current_app.config.get("APP_VERSION", "1.0.0"),
        "authenticated": current_user.is_authenticated if hasattr(current_user, "is_authenticated") else False,
    })


@api_blueprint.route("/health")
def api_health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "version": current_app.config.get("APP_VERSION", "1.0.0"),
    })


@api_blueprint.route("/reconciliation/status")
@login_required
def reconciliation_status():
    """Get reconciliation status."""
    info = current_app.reconciliation_info
    return jsonify({
        "in_progress": info.get("in_progress", False),
        "progress": info.get("progress", 0),
        "total_items": info.get("total_items", 0),
        "processed_items": info.get("processed_items", 0),
        "status": info.get("status", "Not started"),
    })


@api_blueprint.route("/reconciliation/trigger", methods=["POST"])
@login_required
@limiter.limit("5 per minute")
def trigger_reconciliation():
    """Trigger a manual reconciliation run."""
    info = current_app.reconciliation_info

    if info.get("in_progress"):
        return jsonify({
            "status": "error",
            "message": "Reconciliation already in progress",
        }), 409

    try:
        from ..reconciler import get_runner

        runner = get_runner()
        if runner.trigger_reconcile():
            return jsonify({"status": "ok", "message": "Reconciliation triggered"})
        else:
            return jsonify({
                "status": "error",
                "message": "Failed to trigger reconciliation",
            }), 500

    except ImportError:
        return jsonify({
            "status": "error",
            "message": "Reconciler not available",
        }), 503


@api_blueprint.route("/rules")
@login_required
def list_rules():
    """List all managed rules."""
    try:
        from ..state import get_managed_rules

        rules = get_managed_rules()
        return jsonify({
            "status": "ok",
            "rules": [
                {
                    "key": key,
                    "hostname": rule.get("hostname"),
                    "service": rule.get("service"),
                    "status": rule.get("status"),
                    "source": rule.get("source"),
                }
                for key, rule in rules.items()
            ],
        })

    except ImportError:
        return jsonify({"status": "error", "message": "State manager not available"}), 503


@api_blueprint.route("/rules/<path:rule_key>")
@login_required
def get_rule(rule_key):
    """Get a specific rule by key."""
    try:
        from ..state import get_state

        state = get_state()
        rule = state.get_rule(rule_key)

        if rule is None:
            return jsonify({"status": "error", "message": "Rule not found"}), 404

        return jsonify({"status": "ok", "rule": rule})

    except ImportError:
        return jsonify({"status": "error", "message": "State manager not available"}), 503


@api_blueprint.route("/rules/<path:rule_key>", methods=["DELETE"])
@login_required
@limiter.limit("20 per minute")
def delete_rule(rule_key):
    """Delete a rule by key."""
    try:
        from ..state import get_state

        state = get_state()

        if state.delete_rule(rule_key):
            state.save_state()
            return jsonify({"status": "ok", "message": "Rule deleted"})

        return jsonify({"status": "error", "message": "Rule not found"}), 404

    except ImportError:
        return jsonify({"status": "error", "message": "State manager not available"}), 503


@api_blueprint.route("/cache/clear", methods=["POST"])
@login_required
@limiter.limit("5 per minute")
def clear_cache():
    """Clear all caches."""
    try:
        from ..cache import clear_all_caches

        clear_all_caches()
        return jsonify({"status": "ok", "message": "Cache cleared"})

    except ImportError:
        return jsonify({"status": "error", "message": "Cache not available"}), 503
