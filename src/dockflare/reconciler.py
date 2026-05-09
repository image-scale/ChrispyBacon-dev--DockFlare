"""
Reconciliation engine for synchronizing container state with Cloudflare.

Compares desired state from Docker containers with current Cloudflare state
and applies changes to tunnel ingress rules, DNS records, and Access policies.
"""

import copy
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .labels import RouteConfig, get_rule_key
from .state import StateManager, get_state


@dataclass
class ReconciliationResult:
    """Result of a reconciliation run."""

    created: List[str] = field(default_factory=list)
    updated: List[str] = field(default_factory=list)
    marked_for_deletion: List[str] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)
    restored: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    tunnel_config_updated: bool = False
    dns_records_updated: int = 0

    @property
    def has_changes(self) -> bool:
        """Check if any changes were made."""
        return bool(
            self.created
            or self.updated
            or self.marked_for_deletion
            or self.deleted
            or self.restored
            or self.tunnel_config_updated
            or self.dns_records_updated > 0
        )

    def __repr__(self):
        parts = []
        if self.created:
            parts.append(f"created={len(self.created)}")
        if self.updated:
            parts.append(f"updated={len(self.updated)}")
        if self.marked_for_deletion:
            parts.append(f"pending_delete={len(self.marked_for_deletion)}")
        if self.deleted:
            parts.append(f"deleted={len(self.deleted)}")
        if self.restored:
            parts.append(f"restored={len(self.restored)}")
        if self.errors:
            parts.append(f"errors={len(self.errors)}")
        return f"ReconciliationResult({', '.join(parts) or 'no_changes'})"


class Reconciler:
    """
    Reconciliation engine for synchronizing state.

    Compares desired state from containers with current managed state
    and applies necessary changes.
    """

    def __init__(
        self,
        state_manager: StateManager = None,
        tunnel_manager=None,
        dns_manager=None,
        access_manager=None,
        grace_period_seconds: int = 28800,
        default_zone_id: str = None,
        default_tunnel_id: str = None,
    ):
        """
        Initialize the reconciler.

        Args:
            state_manager: State manager for rule persistence
            tunnel_manager: Tunnel manager for ingress updates
            dns_manager: DNS manager for CNAME records
            access_manager: Access manager for applications
            grace_period_seconds: Time before marking deleted rules for removal
            default_zone_id: Default Cloudflare zone ID
            default_tunnel_id: Default tunnel ID for DNS records
        """
        self._state = state_manager
        self._tunnel = tunnel_manager
        self._dns = dns_manager
        self._access = access_manager
        self._grace_period = grace_period_seconds
        self._default_zone_id = default_zone_id
        self._default_tunnel_id = default_tunnel_id
        self._lock = threading.Lock()

    @property
    def state_manager(self) -> StateManager:
        """Get state manager, using default if not set."""
        if self._state is None:
            self._state = get_state()
        return self._state

    def reconcile(
        self,
        desired_routes: List[RouteConfig],
        source: str = "docker",
        agent_id: str = None,
    ) -> ReconciliationResult:
        """
        Reconcile desired routes with current state.

        Args:
            desired_routes: List of desired route configurations
            source: Source of routes ("docker", "agent", "manual")
            agent_id: Agent ID if source is "agent"

        Returns:
            ReconciliationResult with details of changes made
        """
        result = ReconciliationResult()

        with self._lock:
            try:
                desired_keys = set()

                for route in desired_routes:
                    rule_key = get_rule_key(route.hostname, route.path)
                    desired_keys.add(rule_key)

                    existing = self.state_manager.get_rule(rule_key)
                    rule_data = self._route_to_rule_data(route, source, agent_id)

                    if existing is None:
                        self.state_manager.set_rule(rule_key, rule_data)
                        result.created.append(rule_key)
                        logging.info(f"Created rule: {rule_key}")

                    elif existing.get("source") == "manual":
                        logging.debug(f"Skipping manual rule: {rule_key}")
                        continue

                    else:
                        changes_made = self._update_rule_if_changed(
                            rule_key, existing, rule_data, result
                        )

                        if existing.get("status") == "pending_deletion":
                            existing["status"] = "active"
                            existing["delete_at"] = None
                            result.restored.append(rule_key)
                            logging.info(f"Restored rule: {rule_key}")

                self._mark_missing_for_deletion(desired_keys, source, result)

                self.state_manager.save_state()

                if result.has_changes and self._tunnel:
                    self._update_tunnel_config(result)

                if result.has_changes and self._dns:
                    self._update_dns_records(desired_routes, result)

            except Exception as e:
                error_msg = f"Reconciliation error: {e}"
                logging.error(error_msg)
                result.errors.append(error_msg)

        return result

    def _route_to_rule_data(
        self,
        route: RouteConfig,
        source: str,
        agent_id: str = None,
    ) -> Dict[str, Any]:
        """Convert RouteConfig to rule data dict."""
        data = {
            "hostname": route.hostname,
            "service": route.service,
            "path": route.path or None,
            "zone_name": route.zone_name,
            "no_tls_verify": route.no_tls_verify,
            "origin_server_name": route.origin_server_name,
            "http_host_header": route.http_host_header,
            "http2_origin": route.http2_origin,
            "disable_chunked_encoding": route.disable_chunked_encoding,
            "access_groups": route.access_groups,
            "access_policy_type": route.access_policy_type,
            "access_app_name": route.access_app_name,
            "access_session_duration": route.access_session_duration,
            "access_app_launcher_visible": route.access_app_launcher_visible,
            "container_id": route.container_id,
            "container_name": route.container_name,
            "status": "active",
            "delete_at": None,
            "source": source,
        }

        if agent_id:
            data["agent_id"] = agent_id

        return data

    def _update_rule_if_changed(
        self,
        rule_key: str,
        existing: Dict[str, Any],
        new_data: Dict[str, Any],
        result: ReconciliationResult,
    ) -> bool:
        """Update an existing rule if fields have changed."""
        changed = False

        fields_to_check = [
            "service",
            "path",
            "no_tls_verify",
            "origin_server_name",
            "http_host_header",
            "http2_origin",
            "disable_chunked_encoding",
            "access_groups",
            "access_policy_type",
            "container_id",
            "container_name",
        ]

        for field_name in fields_to_check:
            old_value = existing.get(field_name)
            new_value = new_data.get(field_name)

            if old_value != new_value:
                existing[field_name] = new_value
                changed = True

        if changed:
            existing["source"] = new_data.get("source", existing.get("source"))
            result.updated.append(rule_key)
            logging.info(f"Updated rule: {rule_key}")

        return changed

    def _mark_missing_for_deletion(
        self,
        desired_keys: Set[str],
        source: str,
        result: ReconciliationResult,
    ):
        """Mark rules not in desired set for deletion."""
        now = datetime.now(timezone.utc)
        delete_at = now + timedelta(seconds=self._grace_period)

        for rule_key, rule_data in self.state_manager.list_rules().items():
            if rule_key in desired_keys:
                continue

            if rule_data.get("source") != source:
                continue

            if rule_data.get("status") == "pending_deletion":
                continue

            if rule_data.get("source") == "manual":
                continue

            existing = self.state_manager.get_rule(rule_key)
            if existing:
                existing["status"] = "pending_deletion"
                existing["delete_at"] = delete_at.isoformat()
                result.marked_for_deletion.append(rule_key)
                logging.info(
                    f"Marked rule for deletion: {rule_key} "
                    f"(delete at {delete_at.isoformat()})"
                )

    def _update_tunnel_config(self, result: ReconciliationResult):
        """Update Cloudflare tunnel configuration."""
        try:
            from .tunnels import build_ingress_list

            active_rules = [
                rule
                for rule in self.state_manager.list_rules().values()
                if rule.get("status") == "active"
            ]

            ingress = build_ingress_list(active_rules)

            if hasattr(self._tunnel, "update_config"):
                success = self._tunnel.update_config(ingress)
            elif hasattr(self._tunnel, "update_tunnel_config"):
                success = self._tunnel.update_tunnel_config(ingress)
            else:
                logging.warning("Tunnel manager has no update method")
                return

            if success:
                result.tunnel_config_updated = True
                logging.info("Tunnel configuration updated")
            else:
                result.errors.append("Failed to update tunnel configuration")

        except Exception as e:
            logging.error(f"Error updating tunnel config: {e}")
            result.errors.append(f"Tunnel config error: {e}")

    def _update_dns_records(
        self,
        routes: List[RouteConfig],
        result: ReconciliationResult,
    ):
        """Update DNS records for routes."""
        if not self._dns:
            return

        try:
            unique_hostnames = set()
            for route in routes:
                unique_hostnames.add(route.hostname)

            for hostname in unique_hostnames:
                try:
                    zone_id = self._default_zone_id
                    tunnel_id = self._default_tunnel_id

                    if zone_id and tunnel_id:
                        if hasattr(self._dns, "ensure_record"):
                            self._dns.ensure_record(zone_id, hostname, tunnel_id)
                        elif hasattr(self._dns, "create_or_update"):
                            self._dns.create_or_update(zone_id, hostname, tunnel_id)

                        result.dns_records_updated += 1

                except Exception as e:
                    logging.error(f"Error updating DNS for {hostname}: {e}")
                    result.errors.append(f"DNS error for {hostname}: {e}")

        except Exception as e:
            logging.error(f"Error in DNS update phase: {e}")
            result.errors.append(f"DNS phase error: {e}")

    def cleanup_expired_rules(self) -> ReconciliationResult:
        """
        Remove rules that have passed their deletion time.

        Returns:
            ReconciliationResult with deleted rules
        """
        result = ReconciliationResult()
        now = datetime.now(timezone.utc)

        with self._lock:
            rules_to_delete = []

            for rule_key, rule_data in self.state_manager.list_rules().items():
                if rule_data.get("status") != "pending_deletion":
                    continue

                if rule_data.get("source") == "manual":
                    existing = self.state_manager.get_rule(rule_key)
                    if existing:
                        existing["status"] = "active"
                        existing["delete_at"] = None
                    continue

                delete_at_str = rule_data.get("delete_at")
                if not delete_at_str:
                    rules_to_delete.append(rule_key)
                    continue

                try:
                    if isinstance(delete_at_str, str):
                        if delete_at_str.endswith("Z"):
                            delete_at_str = delete_at_str.replace("Z", "+00:00")
                        delete_at = datetime.fromisoformat(delete_at_str)
                        if delete_at.tzinfo is None:
                            delete_at = delete_at.replace(tzinfo=timezone.utc)
                    elif isinstance(delete_at_str, datetime):
                        delete_at = delete_at_str
                        if delete_at.tzinfo is None:
                            delete_at = delete_at.replace(tzinfo=timezone.utc)
                    else:
                        rules_to_delete.append(rule_key)
                        continue

                    if delete_at <= now:
                        rules_to_delete.append(rule_key)

                except Exception as e:
                    logging.error(f"Error parsing delete_at for {rule_key}: {e}")
                    rules_to_delete.append(rule_key)

            for rule_key in rules_to_delete:
                rule_data = self.state_manager.get_rule(rule_key)

                if rule_data and self._dns:
                    try:
                        hostname = rule_data.get("hostname")
                        zone_id = self._default_zone_id

                        is_hostname_still_used = any(
                            k != rule_key
                            and r.get("hostname") == hostname
                            and r.get("status") == "active"
                            for k, r in self.state_manager.list_rules().items()
                        )

                        if hostname and zone_id and not is_hostname_still_used:
                            if hasattr(self._dns, "delete_record"):
                                self._dns.delete_record(zone_id, hostname)

                    except Exception as e:
                        logging.error(f"Error deleting DNS for {rule_key}: {e}")
                        result.errors.append(f"DNS delete error: {e}")

                if rule_data and self._access:
                    try:
                        access_app_id = rule_data.get("access_app_id")

                        is_app_still_used = any(
                            k != rule_key and r.get("access_app_id") == access_app_id
                            for k, r in self.state_manager.list_rules().items()
                        )

                        if access_app_id and not is_app_still_used:
                            if hasattr(self._access, "delete_application"):
                                self._access.delete_application(access_app_id)

                    except Exception as e:
                        logging.error(f"Error deleting Access app for {rule_key}: {e}")
                        result.errors.append(f"Access delete error: {e}")

                if self.state_manager.delete_rule(rule_key):
                    result.deleted.append(rule_key)
                    logging.info(f"Deleted expired rule: {rule_key}")

            if rules_to_delete:
                self.state_manager.save_state()

                if self._tunnel:
                    self._update_tunnel_config(result)

        return result


class ReconciliationRunner:
    """Background runner for periodic reconciliation."""

    def __init__(
        self,
        reconciler: Reconciler,
        interval_seconds: int = 300,
        cleanup_interval_seconds: int = 60,
        get_routes_callback: Callable[[], List[RouteConfig]] = None,
    ):
        """
        Initialize the reconciliation runner.

        Args:
            reconciler: Reconciler instance to use
            interval_seconds: Interval between full reconciliation runs
            cleanup_interval_seconds: Interval between cleanup runs
            get_routes_callback: Callback to get current desired routes
        """
        self._reconciler = reconciler
        self._interval = interval_seconds
        self._cleanup_interval = cleanup_interval_seconds
        self._get_routes = get_routes_callback
        self._stop_event = threading.Event()
        self._reconcile_thread: Optional[threading.Thread] = None
        self._cleanup_thread: Optional[threading.Thread] = None
        self._running = False
        self._last_result: Optional[ReconciliationResult] = None
        self._in_progress = False
        self._progress_info: Dict[str, Any] = {}

    @property
    def is_running(self) -> bool:
        """Check if the runner is active."""
        return self._running

    @property
    def in_progress(self) -> bool:
        """Check if reconciliation is currently in progress."""
        return self._in_progress

    @property
    def last_result(self) -> Optional[ReconciliationResult]:
        """Get the last reconciliation result."""
        return self._last_result

    @property
    def progress_info(self) -> Dict[str, Any]:
        """Get current progress information."""
        return copy.copy(self._progress_info)

    def start(self):
        """Start the background reconciliation threads."""
        if self._running:
            logging.warning("Reconciliation runner already running")
            return

        self._stop_event.clear()
        self._running = True

        self._reconcile_thread = threading.Thread(
            target=self._reconcile_loop,
            name="ReconcileThread",
            daemon=True,
        )
        self._reconcile_thread.start()

        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="CleanupThread",
            daemon=True,
        )
        self._cleanup_thread.start()

        logging.info("Reconciliation runner started")

    def stop(self, timeout: float = 10.0):
        """Stop the background threads."""
        if not self._running:
            return

        logging.info("Stopping reconciliation runner")
        self._stop_event.set()
        self._running = False

        if self._reconcile_thread:
            self._reconcile_thread.join(timeout=timeout)

        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=timeout)

        logging.info("Reconciliation runner stopped")

    def trigger_reconcile(self) -> bool:
        """
        Manually trigger a reconciliation run.

        Returns:
            True if triggered, False if already in progress
        """
        if self._in_progress:
            logging.info("Reconciliation already in progress")
            return False

        thread = threading.Thread(
            target=self._run_reconcile,
            name="ManualReconcileThread",
            daemon=True,
        )
        thread.start()
        return True

    def _reconcile_loop(self):
        """Main reconciliation loop."""
        logging.info("Reconciliation loop started")

        while not self._stop_event.is_set():
            try:
                self._run_reconcile()
            except Exception as e:
                logging.error(f"Error in reconciliation loop: {e}")

            self._stop_event.wait(self._interval)

        logging.info("Reconciliation loop stopped")

    def _cleanup_loop(self):
        """Cleanup loop for expired rules."""
        logging.info("Cleanup loop started")

        while not self._stop_event.is_set():
            try:
                result = self._reconciler.cleanup_expired_rules()
                if result.deleted:
                    logging.info(f"Cleanup: deleted {len(result.deleted)} expired rules")
            except Exception as e:
                logging.error(f"Error in cleanup loop: {e}")

            self._stop_event.wait(self._cleanup_interval)

        logging.info("Cleanup loop stopped")

    def _run_reconcile(self):
        """Execute a single reconciliation run."""
        if not self._get_routes:
            logging.warning("No get_routes callback set")
            return

        if self._in_progress:
            return

        self._in_progress = True
        self._progress_info = {
            "in_progress": True,
            "start_time": time.time(),
            "status": "Running reconciliation...",
        }

        try:
            routes = self._get_routes()
            self._progress_info["total_items"] = len(routes)
            self._progress_info["status"] = f"Reconciling {len(routes)} routes..."

            result = self._reconciler.reconcile(routes)
            self._last_result = result

            self._progress_info["status"] = f"Completed: {result}"
            logging.info(f"Reconciliation completed: {result}")

        except Exception as e:
            logging.error(f"Reconciliation error: {e}")
            self._progress_info["status"] = f"Error: {e}"

        finally:
            self._in_progress = False
            self._progress_info["in_progress"] = False
            self._progress_info["completed_at"] = time.time()


_default_reconciler: Optional[Reconciler] = None
_default_runner: Optional[ReconciliationRunner] = None


def get_reconciler() -> Reconciler:
    """Get or create the default Reconciler instance."""
    global _default_reconciler
    if _default_reconciler is None:
        _default_reconciler = Reconciler()
    return _default_reconciler


def get_runner() -> ReconciliationRunner:
    """Get or create the default ReconciliationRunner instance."""
    global _default_runner
    if _default_runner is None:
        _default_runner = ReconciliationRunner(
            reconciler=get_reconciler(),
        )
    return _default_runner


def reconcile(
    routes: List[RouteConfig],
    source: str = "docker",
) -> ReconciliationResult:
    """Convenience function to run reconciliation using default reconciler."""
    return get_reconciler().reconcile(routes, source=source)


def cleanup_expired() -> ReconciliationResult:
    """Convenience function to cleanup expired rules."""
    return get_reconciler().cleanup_expired_rules()
