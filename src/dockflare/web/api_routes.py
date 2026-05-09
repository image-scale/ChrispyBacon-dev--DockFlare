"""
API routes for the Flask application.

Provides REST API endpoints for rule management, tunnel status,
agent enrollment, and system health.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

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
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@api_blueprint.route("/health")
def api_health():
    """Health check endpoint."""
    health_info = {
        "status": "healthy",
        "version": current_app.config.get("APP_VERSION", "1.0.0"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {},
    }

    try:
        from ..state import get_state
        state = get_state()
        health_info["checks"]["state"] = {
            "status": "ok",
            "rules_count": len(state.list_rules()),
        }
    except Exception as e:
        health_info["checks"]["state"] = {"status": "error", "message": str(e)}

    try:
        from ..cache import get_cache
        cache = get_cache()
        health_info["checks"]["cache"] = {
            "status": "ok",
            "using_redis": cache.using_redis,
        }
    except Exception as e:
        health_info["checks"]["cache"] = {"status": "error", "message": str(e)}

    all_healthy = all(
        check.get("status") == "ok"
        for check in health_info["checks"].values()
    )
    health_info["status"] = "healthy" if all_healthy else "degraded"

    return jsonify(health_info)


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
        "start_time": info.get("start_time", 0),
        "completed_at": info.get("completed_at"),
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

        status_filter = request.args.get("status")
        source_filter = request.args.get("source")

        filtered_rules = []
        for key, rule in rules.items():
            if status_filter and rule.get("status") != status_filter:
                continue
            if source_filter and rule.get("source") != source_filter:
                continue

            filtered_rules.append({
                "key": key,
                "hostname": rule.get("hostname"),
                "path": rule.get("path"),
                "service": rule.get("service"),
                "status": rule.get("status"),
                "source": rule.get("source"),
                "container_name": rule.get("container_name"),
                "no_tls_verify": rule.get("no_tls_verify", False),
            })

        return jsonify({
            "status": "ok",
            "count": len(filtered_rules),
            "rules": filtered_rules,
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


@api_blueprint.route("/rules", methods=["POST"])
@login_required
@limiter.limit("20 per minute")
def create_rule():
    """Create a new manual rule."""
    try:
        from ..state import get_state, get_rule_key

        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Request body required"}), 400

        hostname = data.get("hostname")
        service = data.get("service")

        if not hostname or not service:
            return jsonify({
                "status": "error",
                "message": "hostname and service are required",
            }), 400

        path = data.get("path")
        rule_key = get_rule_key(hostname, path)

        state = get_state()
        existing = state.get_rule(rule_key)
        if existing:
            return jsonify({
                "status": "error",
                "message": f"Rule already exists: {rule_key}",
            }), 409

        rule_data = {
            "hostname": hostname,
            "service": service,
            "path": path,
            "status": "active",
            "source": "manual",
            "no_tls_verify": data.get("no_tls_verify", False),
            "origin_server_name": data.get("origin_server_name"),
            "http_host_header": data.get("http_host_header"),
            "zone_name": data.get("zone_name"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        state.set_rule(rule_key, rule_data)
        state.save_state()

        return jsonify({
            "status": "ok",
            "message": "Rule created",
            "rule_key": rule_key,
        }), 201

    except ImportError:
        return jsonify({"status": "error", "message": "State manager not available"}), 503


@api_blueprint.route("/rules/<path:rule_key>", methods=["PUT"])
@login_required
@limiter.limit("20 per minute")
def update_rule(rule_key):
    """Update an existing rule."""
    try:
        from ..state import get_state

        state = get_state()
        existing = state.get_rule(rule_key)

        if existing is None:
            return jsonify({"status": "error", "message": "Rule not found"}), 404

        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Request body required"}), 400

        updatable_fields = [
            "service", "status", "no_tls_verify", "origin_server_name",
            "http_host_header", "zone_name",
        ]

        for field in updatable_fields:
            if field in data:
                existing[field] = data[field]

        existing["updated_at"] = datetime.now(timezone.utc).isoformat()
        state.save_state()

        return jsonify({"status": "ok", "message": "Rule updated", "rule": existing})

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


@api_blueprint.route("/tunnel/status")
@login_required
def tunnel_status():
    """Get tunnel status information."""
    try:
        from ..tunnels import get_manager

        manager = get_manager()

        status_info = {
            "status": "ok",
            "tunnel_id": getattr(manager, "_tunnel_id", None),
            "tunnel_name": getattr(manager, "_tunnel_name", None),
            "connected": getattr(manager, "_connected", False),
        }

        return jsonify(status_info)

    except ImportError:
        return jsonify({
            "status": "ok",
            "tunnel_id": None,
            "tunnel_name": None,
            "connected": False,
            "message": "Tunnel manager not configured",
        })


@api_blueprint.route("/tunnel/config")
@login_required
def tunnel_config():
    """Get current tunnel configuration."""
    try:
        from ..tunnels import get_manager

        manager = get_manager()
        tunnel_id = getattr(manager, "_tunnel_id", None)

        if not tunnel_id:
            return jsonify({
                "status": "error",
                "message": "No tunnel configured",
            }), 404

        config = manager.get_config(tunnel_id)
        if config is None:
            return jsonify({
                "status": "error",
                "message": "Failed to retrieve tunnel config",
            }), 500

        return jsonify({
            "status": "ok",
            "tunnel_id": tunnel_id,
            "config": config,
        })

    except ImportError:
        return jsonify({"status": "error", "message": "Tunnel manager not available"}), 503


@api_blueprint.route("/agents")
@login_required
def list_agents():
    """List all registered agents."""
    try:
        from ..state import get_agents

        agents = get_agents()

        return jsonify({
            "status": "ok",
            "count": len(agents),
            "agents": [
                {
                    "id": agent_id,
                    "name": agent.get("name"),
                    "status": agent.get("status"),
                    "last_seen": agent.get("last_seen"),
                    "container_count": agent.get("container_count", 0),
                }
                for agent_id, agent in agents.items()
            ],
        })

    except ImportError:
        return jsonify({"status": "error", "message": "State manager not available"}), 503


@api_blueprint.route("/agents/<agent_id>")
@login_required
def get_agent(agent_id):
    """Get agent details."""
    try:
        from ..state import get_state

        state = get_state()
        agent = state.get_agent(agent_id)

        if agent is None:
            return jsonify({"status": "error", "message": "Agent not found"}), 404

        return jsonify({"status": "ok", "agent": agent})

    except ImportError:
        return jsonify({"status": "error", "message": "State manager not available"}), 503


@api_blueprint.route("/agents/enroll", methods=["POST"])
@limiter.limit("10 per minute")
def enroll_agent():
    """Enroll a new agent."""
    try:
        import secrets
        from ..state import get_state

        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Request body required"}), 400

        name = data.get("name")
        if not name:
            return jsonify({"status": "error", "message": "name is required"}), 400

        enrollment_key = request.headers.get("X-Enrollment-Key")
        expected_key = current_app.config.get("AGENT_ENROLLMENT_KEY")

        if expected_key and enrollment_key != expected_key:
            return jsonify({"status": "error", "message": "Invalid enrollment key"}), 401

        agent_id = secrets.token_hex(8)
        api_key = secrets.token_urlsafe(32)

        import hashlib
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        agent_data = {
            "id": agent_id,
            "name": name,
            "status": "pending",
            "api_key_hash": api_key_hash,
            "enrolled_at": datetime.now(timezone.utc).isoformat(),
            "last_seen": None,
            "container_count": 0,
        }

        state = get_state()
        state.set_agent(agent_id, agent_data)
        state.save_state()

        return jsonify({
            "status": "ok",
            "message": "Agent enrolled",
            "agent_id": agent_id,
            "api_key": api_key,
        }), 201

    except ImportError:
        return jsonify({"status": "error", "message": "State manager not available"}), 503


@api_blueprint.route("/agents/<agent_id>/heartbeat", methods=["POST"])
@limiter.limit("60 per minute")
def agent_heartbeat(agent_id):
    """Receive agent heartbeat."""
    try:
        from ..state import get_state

        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return jsonify({"status": "error", "message": "API key required"}), 401

        state = get_state()
        agent = state.get_agent(agent_id)

        if agent is None:
            return jsonify({"status": "error", "message": "Agent not found"}), 404

        import hashlib
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        if agent.get("api_key_hash") != api_key_hash:
            return jsonify({"status": "error", "message": "Invalid API key"}), 401

        data = request.get_json() or {}

        agent["status"] = "active"
        agent["last_seen"] = datetime.now(timezone.utc).isoformat()
        agent["container_count"] = data.get("container_count", agent.get("container_count", 0))

        if "containers" in data:
            agent["containers"] = data["containers"]

        state.save_state()

        return jsonify({
            "status": "ok",
            "message": "Heartbeat received",
            "timestamp": agent["last_seen"],
        })

    except ImportError:
        return jsonify({"status": "error", "message": "State manager not available"}), 503


@api_blueprint.route("/agents/<agent_id>", methods=["DELETE"])
@login_required
@limiter.limit("10 per minute")
def delete_agent(agent_id):
    """Delete an agent."""
    try:
        from ..state import get_state

        state = get_state()

        if state.delete_agent(agent_id):
            state.save_state()
            return jsonify({"status": "ok", "message": "Agent deleted"})

        return jsonify({"status": "error", "message": "Agent not found"}), 404

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


@api_blueprint.route("/cache/stats")
@login_required
def cache_stats():
    """Get cache statistics."""
    try:
        from ..cache import get_cache

        cache = get_cache()

        return jsonify({
            "status": "ok",
            "using_redis": cache.using_redis,
            "backend": "redis" if cache.using_redis else "memory",
        })

    except ImportError:
        return jsonify({"status": "error", "message": "Cache not available"}), 503


@api_blueprint.route("/access-groups")
@login_required
def list_access_groups():
    """List all access groups."""
    try:
        from ..state import get_access_groups

        groups = get_access_groups()

        return jsonify({
            "status": "ok",
            "count": len(groups),
            "groups": [
                {
                    "id": group_id,
                    "display_name": group.get("display_name"),
                    "session_duration": group.get("session_duration"),
                    "app_launcher_visible": group.get("app_launcher_visible"),
                }
                for group_id, group in groups.items()
            ],
        })

    except ImportError:
        return jsonify({"status": "error", "message": "State manager not available"}), 503


@api_blueprint.route("/access-groups/<group_id>")
@login_required
def get_access_group(group_id):
    """Get access group details."""
    try:
        from ..state import get_state

        state = get_state()
        group = state.get_access_group(group_id)

        if group is None:
            return jsonify({"status": "error", "message": "Access group not found"}), 404

        return jsonify({"status": "ok", "group": group})

    except ImportError:
        return jsonify({"status": "error", "message": "State manager not available"}), 503


@api_blueprint.route("/system/info")
@login_required
def system_info():
    """Get system information."""
    import sys
    import platform

    return jsonify({
        "status": "ok",
        "app_version": current_app.config.get("APP_VERSION", "1.0.0"),
        "python_version": sys.version,
        "platform": platform.platform(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
