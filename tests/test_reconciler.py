"""Tests for reconciliation engine."""

import pytest
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock

from dockflare.reconciler import (
    ReconciliationResult,
    Reconciler,
    ReconciliationRunner,
    get_reconciler,
    get_runner,
    reconcile,
    cleanup_expired,
)
from dockflare.labels import RouteConfig
from dockflare.state import StateManager


class TestReconciliationResult:
    """Tests for ReconciliationResult class."""

    def test_empty_result_has_no_changes(self):
        """Empty result should report no changes."""
        result = ReconciliationResult()
        assert result.has_changes is False

    def test_created_counts_as_change(self):
        """Created rules should count as changes."""
        result = ReconciliationResult(created=["rule1"])
        assert result.has_changes is True

    def test_updated_counts_as_change(self):
        """Updated rules should count as changes."""
        result = ReconciliationResult(updated=["rule1"])
        assert result.has_changes is True

    def test_deleted_counts_as_change(self):
        """Deleted rules should count as changes."""
        result = ReconciliationResult(deleted=["rule1"])
        assert result.has_changes is True

    def test_restored_counts_as_change(self):
        """Restored rules should count as changes."""
        result = ReconciliationResult(restored=["rule1"])
        assert result.has_changes is True

    def test_tunnel_update_counts_as_change(self):
        """Tunnel config update should count as change."""
        result = ReconciliationResult(tunnel_config_updated=True)
        assert result.has_changes is True

    def test_dns_update_counts_as_change(self):
        """DNS record updates should count as changes."""
        result = ReconciliationResult(dns_records_updated=1)
        assert result.has_changes is True

    def test_repr_shows_counts(self):
        """Repr should show counts of each change type."""
        result = ReconciliationResult(
            created=["r1", "r2"],
            updated=["r3"],
        )
        repr_str = repr(result)
        assert "created=2" in repr_str
        assert "updated=1" in repr_str

    def test_repr_empty_shows_no_changes(self):
        """Empty result repr should indicate no changes."""
        result = ReconciliationResult()
        assert "no_changes" in repr(result)


class TestReconciler:
    """Tests for Reconciler class."""

    @pytest.fixture
    def mock_state_manager(self):
        """Create a mock StateManager."""
        manager = Mock(spec=StateManager)
        manager.list_rules.return_value = {}
        manager.get_rule.return_value = None
        manager.set_rule.return_value = None
        manager.delete_rule.return_value = True
        manager.save_state.return_value = True
        return manager

    @pytest.fixture
    def reconciler(self, mock_state_manager):
        """Create a Reconciler with mocks."""
        return Reconciler(
            state_manager=mock_state_manager,
            grace_period_seconds=3600,
        )


class TestReconcilerReconcile:
    """Tests for Reconciler.reconcile method."""

    @pytest.fixture
    def mock_state_manager(self):
        manager = Mock(spec=StateManager)
        manager.list_rules.return_value = {}
        manager.get_rule.return_value = None
        manager.set_rule.return_value = None
        manager.delete_rule.return_value = True
        manager.save_state.return_value = True
        return manager

    @pytest.fixture
    def reconciler(self, mock_state_manager):
        return Reconciler(
            state_manager=mock_state_manager,
            grace_period_seconds=3600,
        )

    def test_creates_new_rules(self, reconciler, mock_state_manager):
        """Should create rules for new routes."""
        routes = [
            RouteConfig(
                hostname="app.example.com",
                service="http://app:80",
            )
        ]

        result = reconciler.reconcile(routes)

        assert "app.example.com|" in result.created
        mock_state_manager.set_rule.assert_called()

    def test_updates_changed_rules(self, reconciler, mock_state_manager):
        """Should update rules when service changes."""
        existing_rule = {
            "hostname": "app.example.com",
            "service": "http://old:80",
            "status": "active",
            "source": "docker",
        }
        mock_state_manager.get_rule.return_value = existing_rule
        mock_state_manager.list_rules.return_value = {"app.example.com|": existing_rule}

        routes = [
            RouteConfig(
                hostname="app.example.com",
                service="http://new:80",
            )
        ]

        result = reconciler.reconcile(routes)

        assert "app.example.com|" in result.updated
        assert existing_rule["service"] == "http://new:80"

    def test_skips_manual_rules(self, reconciler, mock_state_manager):
        """Should skip manual rules."""
        existing_rule = {
            "hostname": "manual.example.com",
            "service": "http://manual:80",
            "status": "active",
            "source": "manual",
        }
        mock_state_manager.get_rule.return_value = existing_rule

        routes = [
            RouteConfig(
                hostname="manual.example.com",
                service="http://different:80",
            )
        ]

        result = reconciler.reconcile(routes)

        assert "manual.example.com|" not in result.updated
        assert existing_rule["service"] == "http://manual:80"

    def test_restores_pending_deletion_rules(self, reconciler, mock_state_manager):
        """Should restore rules marked for deletion."""
        existing_rule = {
            "hostname": "app.example.com",
            "service": "http://app:80",
            "status": "pending_deletion",
            "delete_at": "2025-01-01T00:00:00Z",
            "source": "docker",
        }
        mock_state_manager.get_rule.return_value = existing_rule
        mock_state_manager.list_rules.return_value = {"app.example.com|": existing_rule}

        routes = [
            RouteConfig(
                hostname="app.example.com",
                service="http://app:80",
            )
        ]

        result = reconciler.reconcile(routes)

        assert "app.example.com|" in result.restored
        assert existing_rule["status"] == "active"
        assert existing_rule["delete_at"] is None

    def test_marks_missing_rules_for_deletion(self, reconciler, mock_state_manager):
        """Should mark missing rules for deletion."""
        existing_rule = {
            "hostname": "old.example.com",
            "service": "http://old:80",
            "status": "active",
            "source": "docker",
        }
        mock_state_manager.get_rule.side_effect = lambda k: (
            existing_rule if k == "old.example.com|" else None
        )
        mock_state_manager.list_rules.return_value = {"old.example.com|": existing_rule}

        routes = [
            RouteConfig(
                hostname="new.example.com",
                service="http://new:80",
            )
        ]

        result = reconciler.reconcile(routes)

        assert "old.example.com|" in result.marked_for_deletion
        assert existing_rule["status"] == "pending_deletion"
        assert existing_rule["delete_at"] is not None

    def test_saves_state_after_changes(self, reconciler, mock_state_manager):
        """Should save state after making changes."""
        routes = [
            RouteConfig(
                hostname="app.example.com",
                service="http://app:80",
            )
        ]

        reconciler.reconcile(routes)

        mock_state_manager.save_state.assert_called()

    def test_handles_empty_routes(self, reconciler, mock_state_manager):
        """Should handle empty route list."""
        result = reconciler.reconcile([])

        assert result.created == []

    def test_includes_agent_id(self, reconciler, mock_state_manager):
        """Should include agent_id when provided."""
        routes = [
            RouteConfig(
                hostname="app.example.com",
                service="http://app:80",
            )
        ]

        reconciler.reconcile(routes, source="agent", agent_id="agent-123")

        call_args = mock_state_manager.set_rule.call_args
        rule_data = call_args[0][1]
        assert rule_data["source"] == "agent"
        assert rule_data["agent_id"] == "agent-123"


class TestReconcilerTunnelIntegration:
    """Tests for tunnel manager integration."""

    @pytest.fixture
    def mock_state_manager(self):
        manager = Mock(spec=StateManager)
        manager.list_rules.return_value = {}
        manager.get_rule.return_value = None
        manager.save_state.return_value = True
        return manager

    @pytest.fixture
    def mock_tunnel_manager(self):
        manager = Mock()
        manager.update_config.return_value = True
        return manager

    @pytest.fixture
    def reconciler(self, mock_state_manager, mock_tunnel_manager):
        return Reconciler(
            state_manager=mock_state_manager,
            tunnel_manager=mock_tunnel_manager,
        )

    def test_updates_tunnel_config_on_changes(
        self, reconciler, mock_tunnel_manager, mock_state_manager
    ):
        """Should update tunnel config when routes change."""
        routes = [
            RouteConfig(
                hostname="app.example.com",
                service="http://app:80",
            )
        ]

        result = reconciler.reconcile(routes)

        mock_tunnel_manager.update_config.assert_called()
        assert result.tunnel_config_updated is True


class TestReconcilerDNSIntegration:
    """Tests for DNS manager integration."""

    @pytest.fixture
    def mock_state_manager(self):
        manager = Mock(spec=StateManager)
        manager.list_rules.return_value = {}
        manager.get_rule.return_value = None
        manager.save_state.return_value = True
        return manager

    @pytest.fixture
    def mock_dns_manager(self):
        manager = Mock()
        manager.ensure_record.return_value = "record-123"
        return manager

    @pytest.fixture
    def reconciler(self, mock_state_manager, mock_dns_manager):
        return Reconciler(
            state_manager=mock_state_manager,
            dns_manager=mock_dns_manager,
            default_zone_id="zone-123",
            default_tunnel_id="tunnel-123",
        )

    def test_updates_dns_records_on_changes(
        self, reconciler, mock_dns_manager, mock_state_manager
    ):
        """Should update DNS records when routes change."""
        routes = [
            RouteConfig(
                hostname="app.example.com",
                service="http://app:80",
            )
        ]

        result = reconciler.reconcile(routes)

        mock_dns_manager.ensure_record.assert_called()
        assert result.dns_records_updated > 0


class TestReconcilerCleanup:
    """Tests for cleanup_expired_rules method."""

    @pytest.fixture
    def mock_state_manager(self):
        manager = Mock(spec=StateManager)
        manager.list_rules.return_value = {}
        manager.get_rule.return_value = None
        manager.delete_rule.return_value = True
        manager.save_state.return_value = True
        return manager

    @pytest.fixture
    def reconciler(self, mock_state_manager):
        return Reconciler(
            state_manager=mock_state_manager,
        )

    def test_deletes_expired_rules(self, reconciler, mock_state_manager):
        """Should delete rules past their deletion time."""
        expired_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        expired_rule = {
            "hostname": "old.example.com",
            "service": "http://old:80",
            "status": "pending_deletion",
            "delete_at": expired_time,
            "source": "docker",
        }
        mock_state_manager.list_rules.return_value = {"old.example.com|": expired_rule}
        mock_state_manager.get_rule.return_value = expired_rule

        result = reconciler.cleanup_expired_rules()

        assert "old.example.com|" in result.deleted
        mock_state_manager.delete_rule.assert_called_with("old.example.com|")

    def test_keeps_non_expired_rules(self, reconciler, mock_state_manager):
        """Should keep rules not yet expired."""
        future_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        pending_rule = {
            "hostname": "pending.example.com",
            "service": "http://pending:80",
            "status": "pending_deletion",
            "delete_at": future_time,
            "source": "docker",
        }
        mock_state_manager.list_rules.return_value = {
            "pending.example.com|": pending_rule
        }

        result = reconciler.cleanup_expired_rules()

        assert "pending.example.com|" not in result.deleted

    def test_handles_z_suffix_timestamp(self, reconciler, mock_state_manager):
        """Should handle timestamps with Z suffix."""
        expired_time = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        expired_rule = {
            "hostname": "old.example.com",
            "service": "http://old:80",
            "status": "pending_deletion",
            "delete_at": expired_time,
            "source": "docker",
        }
        mock_state_manager.list_rules.return_value = {"old.example.com|": expired_rule}
        mock_state_manager.get_rule.return_value = expired_rule

        result = reconciler.cleanup_expired_rules()

        assert "old.example.com|" in result.deleted

    def test_resets_manual_rules_to_active(self, reconciler, mock_state_manager):
        """Should reset manual rules to active if pending deletion."""
        manual_rule = {
            "hostname": "manual.example.com",
            "service": "http://manual:80",
            "status": "pending_deletion",
            "delete_at": datetime.now(timezone.utc).isoformat(),
            "source": "manual",
        }
        mock_state_manager.list_rules.return_value = {
            "manual.example.com|": manual_rule
        }
        mock_state_manager.get_rule.return_value = manual_rule

        result = reconciler.cleanup_expired_rules()

        assert "manual.example.com|" not in result.deleted
        assert manual_rule["status"] == "active"


class TestReconciliationRunner:
    """Tests for ReconciliationRunner class."""

    @pytest.fixture
    def mock_reconciler(self):
        reconciler = Mock(spec=Reconciler)
        reconciler.reconcile.return_value = ReconciliationResult()
        reconciler.cleanup_expired_rules.return_value = ReconciliationResult()
        return reconciler

    @pytest.fixture
    def runner(self, mock_reconciler):
        return ReconciliationRunner(
            reconciler=mock_reconciler,
            interval_seconds=1,
            cleanup_interval_seconds=1,
        )

    def test_starts_and_stops(self, runner):
        """Should start and stop cleanly."""
        runner.start()
        assert runner.is_running is True

        time.sleep(0.1)
        runner.stop(timeout=2)

        assert runner.is_running is False

    def test_runs_reconciliation(self, runner, mock_reconciler):
        """Should run reconciliation periodically."""
        routes = [RouteConfig(hostname="app.example.com", service="http://app:80")]
        runner._get_routes = lambda: routes

        runner.start()
        time.sleep(0.5)
        runner.stop(timeout=2)

        mock_reconciler.reconcile.assert_called()

    def test_runs_cleanup(self, runner, mock_reconciler):
        """Should run cleanup periodically."""
        runner._get_routes = lambda: []

        runner.start()
        time.sleep(0.5)
        runner.stop(timeout=2)

        mock_reconciler.cleanup_expired_rules.assert_called()

    def test_manual_trigger(self, runner, mock_reconciler):
        """Should allow manual trigger."""
        routes = [RouteConfig(hostname="app.example.com", service="http://app:80")]
        runner._get_routes = lambda: routes

        result = runner.trigger_reconcile()
        time.sleep(0.2)

        assert result is True
        mock_reconciler.reconcile.assert_called()

    def test_rejects_trigger_when_in_progress(self, runner, mock_reconciler):
        """Should reject trigger when already in progress."""
        runner._in_progress = True

        result = runner.trigger_reconcile()

        assert result is False

    def test_tracks_progress_info(self, runner, mock_reconciler):
        """Should track progress information."""
        routes = [RouteConfig(hostname="app.example.com", service="http://app:80")]
        runner._get_routes = lambda: routes

        runner.start()
        time.sleep(0.3)
        runner.stop(timeout=2)

        assert runner.last_result is not None

    def test_handles_no_callback(self, runner, mock_reconciler):
        """Should handle missing get_routes callback."""
        runner._get_routes = None

        runner.start()
        time.sleep(0.2)
        runner.stop(timeout=2)

        mock_reconciler.reconcile.assert_not_called()


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    @patch("dockflare.reconciler._default_reconciler", None)
    def test_get_reconciler_creates_singleton(self):
        """get_reconciler should create singleton."""
        import dockflare.reconciler as mod
        mod._default_reconciler = None

        r1 = get_reconciler()
        r2 = get_reconciler()

        assert r1 is r2
        assert isinstance(r1, Reconciler)

    @patch("dockflare.reconciler._default_runner", None)
    def test_get_runner_creates_singleton(self):
        """get_runner should create singleton."""
        import dockflare.reconciler as mod
        mod._default_runner = None

        runner1 = get_runner()
        runner2 = get_runner()

        assert runner1 is runner2
        assert isinstance(runner1, ReconciliationRunner)

    @patch("dockflare.reconciler.get_reconciler")
    def test_reconcile_uses_default(self, mock_get_reconciler):
        """reconcile should use default reconciler."""
        mock_reconciler = Mock()
        mock_reconciler.reconcile.return_value = ReconciliationResult()
        mock_get_reconciler.return_value = mock_reconciler

        routes = [RouteConfig(hostname="app.example.com", service="http://app:80")]
        result = reconcile(routes)

        mock_reconciler.reconcile.assert_called_once()
        assert isinstance(result, ReconciliationResult)

    @patch("dockflare.reconciler.get_reconciler")
    def test_cleanup_expired_uses_default(self, mock_get_reconciler):
        """cleanup_expired should use default reconciler."""
        mock_reconciler = Mock()
        mock_reconciler.cleanup_expired_rules.return_value = ReconciliationResult()
        mock_get_reconciler.return_value = mock_reconciler

        result = cleanup_expired()

        mock_reconciler.cleanup_expired_rules.assert_called_once()
        assert isinstance(result, ReconciliationResult)
