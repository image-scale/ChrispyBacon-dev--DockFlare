"""Tests for state management."""

import json
import os
import pytest
import tempfile
import threading
from unittest.mock import patch, Mock

from dockflare.state import (
    StateManager,
    ManagedRule,
    AccessGroup,
    Agent,
    get_rule_key,
    load_state,
    save_state,
    get_managed_rules,
    get_access_groups,
    get_agents,
    get_state,
)


class TestStateManager:
    """Tests for StateManager class."""

    @pytest.fixture
    def temp_state_file(self):
        """Create a temporary state file."""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.unlink(path)

    @pytest.fixture
    def manager(self, temp_state_file):
        """Create a StateManager with temp file."""
        return StateManager(state_file=temp_state_file)

    def test_init_with_default_state(self, manager):
        """Should initialize with empty state."""
        assert manager.managed_rules == {}
        assert manager.access_groups == {}
        assert manager.agents == {}


class TestStateManagerRules:
    """Tests for rule operations."""

    @pytest.fixture
    def temp_state_file(self):
        """Create a temporary state file."""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.unlink(path)

    @pytest.fixture
    def manager(self, temp_state_file):
        """Create a StateManager with temp file."""
        return StateManager(state_file=temp_state_file)

    def test_set_and_get_rule(self, manager):
        """Should set and get rules."""
        rule = {"hostname": "app.example.com", "service": "http://app:80"}
        manager.set_rule("app.example.com|", rule)

        retrieved = manager.get_rule("app.example.com|")
        assert retrieved == rule

    def test_get_nonexistent_rule(self, manager):
        """Should return None for nonexistent rule."""
        assert manager.get_rule("nonexistent|") is None

    def test_delete_rule(self, manager):
        """Should delete rule and return True."""
        manager.set_rule("app.example.com|", {"hostname": "app.example.com"})

        result = manager.delete_rule("app.example.com|")
        assert result is True
        assert manager.get_rule("app.example.com|") is None

    def test_delete_nonexistent_rule(self, manager):
        """Should return False for nonexistent rule."""
        result = manager.delete_rule("nonexistent|")
        assert result is False

    def test_list_rules_returns_copy(self, manager):
        """Should return copy of rules."""
        manager.set_rule("app.example.com|", {"hostname": "app.example.com"})

        rules = manager.list_rules()
        rules["new_key"] = {"test": "data"}

        assert "new_key" not in manager.managed_rules


class TestStateManagerAccessGroups:
    """Tests for access group operations."""

    @pytest.fixture
    def temp_state_file(self):
        """Create a temporary state file."""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.unlink(path)

    @pytest.fixture
    def manager(self, temp_state_file):
        """Create a StateManager with temp file."""
        return StateManager(state_file=temp_state_file)

    def test_set_and_get_access_group(self, manager):
        """Should set and get access groups."""
        group = {"id": "admin-group", "display_name": "Admins"}
        manager.set_access_group("admin-group", group)

        retrieved = manager.get_access_group("admin-group")
        assert retrieved == group

    def test_delete_access_group(self, manager):
        """Should delete access group."""
        manager.set_access_group("admin-group", {"id": "admin-group"})

        result = manager.delete_access_group("admin-group")
        assert result is True
        assert manager.get_access_group("admin-group") is None

    def test_list_access_groups(self, manager):
        """Should list all access groups."""
        manager.set_access_group("group1", {"id": "group1"})
        manager.set_access_group("group2", {"id": "group2"})

        groups = manager.list_access_groups()
        assert len(groups) == 2
        assert "group1" in groups
        assert "group2" in groups


class TestStateManagerAgents:
    """Tests for agent operations."""

    @pytest.fixture
    def temp_state_file(self):
        """Create a temporary state file."""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.unlink(path)

    @pytest.fixture
    def manager(self, temp_state_file):
        """Create a StateManager with temp file."""
        return StateManager(state_file=temp_state_file)

    def test_set_and_get_agent(self, manager):
        """Should set and get agents."""
        agent = {"id": "agent-1", "name": "Server 1", "status": "active"}
        manager.set_agent("agent-1", agent)

        retrieved = manager.get_agent("agent-1")
        assert retrieved == agent

    def test_delete_agent(self, manager):
        """Should delete agent."""
        manager.set_agent("agent-1", {"id": "agent-1"})

        result = manager.delete_agent("agent-1")
        assert result is True
        assert manager.get_agent("agent-1") is None

    def test_list_agents(self, manager):
        """Should list all agents."""
        manager.set_agent("agent-1", {"id": "agent-1"})
        manager.set_agent("agent-2", {"id": "agent-2"})

        agents = manager.list_agents()
        assert len(agents) == 2


class TestStateManagerPersistence:
    """Tests for state persistence."""

    @pytest.fixture
    def temp_state_file(self):
        """Create a temporary state file."""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.unlink(path)

    def test_save_and_load_state(self, temp_state_file):
        """Should save and load state."""
        manager = StateManager(state_file=temp_state_file)
        manager.set_rule("app.example.com|", {"hostname": "app.example.com", "service": "http://app:80"})
        manager.set_access_group("admin", {"id": "admin", "display_name": "Admins"})
        manager.set_agent("agent-1", {"id": "agent-1", "name": "Server 1"})

        result = manager.save_state()
        assert result is True

        new_manager = StateManager(state_file=temp_state_file)
        result = new_manager.load_state()
        assert result is True

        assert len(new_manager.managed_rules) == 1
        assert len(new_manager.access_groups) == 1
        assert len(new_manager.agents) == 1

    def test_load_state_missing_file(self, temp_state_file):
        """Should handle missing state file gracefully."""
        os.unlink(temp_state_file)
        manager = StateManager(state_file=temp_state_file)

        result = manager.load_state()
        assert result is False
        assert manager.managed_rules == {}

    def test_load_state_invalid_json(self, temp_state_file):
        """Should handle invalid JSON gracefully."""
        with open(temp_state_file, "w") as f:
            f.write("not valid json{")

        manager = StateManager(state_file=temp_state_file)
        result = manager.load_state()

        assert result is False
        assert manager.managed_rules == {}

    def test_load_state_old_format(self, temp_state_file):
        """Should handle old format (rules only)."""
        old_data = {
            "app.example.com|": {"hostname": "app.example.com", "service": "http://app:80"}
        }
        with open(temp_state_file, "w") as f:
            json.dump(old_data, f)

        manager = StateManager(state_file=temp_state_file)
        result = manager.load_state()

        assert result is True
        assert len(manager.managed_rules) == 1

    def test_save_state_creates_directory(self):
        """Should create directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "subdir", "state.json")
            manager = StateManager(state_file=state_file)
            manager.set_rule("test|", {"hostname": "test"})

            result = manager.save_state()
            assert result is True
            assert os.path.exists(state_file)


class TestStateManagerThreadSafety:
    """Tests for thread safety."""

    @pytest.fixture
    def temp_state_file(self):
        """Create a temporary state file."""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.unlink(path)

    def test_concurrent_access(self, temp_state_file):
        """Should handle concurrent access safely."""
        manager = StateManager(state_file=temp_state_file)
        errors = []

        def worker(n):
            try:
                for i in range(100):
                    key = f"rule-{n}-{i}|"
                    manager.set_rule(key, {"hostname": f"host-{n}-{i}"})
                    manager.get_rule(key)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(manager.managed_rules) == 500


class TestGetRuleKey:
    """Tests for get_rule_key function."""

    def test_with_hostname_only(self):
        """Should create key with hostname and empty path."""
        key = get_rule_key("example.com")
        assert key == "example.com|"

    def test_with_hostname_and_path(self):
        """Should create key with hostname and path."""
        key = get_rule_key("example.com", "/api")
        assert key == "example.com|/api"

    def test_with_none_path(self):
        """Should handle None path."""
        key = get_rule_key("example.com", None)
        assert key == "example.com|"

    def test_strips_whitespace(self):
        """Should strip whitespace from path."""
        key = get_rule_key("example.com", "  /api  ")
        assert key == "example.com|/api"


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    @patch("dockflare.state._state", None)
    def test_get_state_creates_singleton(self):
        """get_state should create a singleton."""
        import dockflare.state as state_module
        state_module._state = None

        state1 = get_state()
        state2 = get_state()

        assert state1 is state2

    @patch("dockflare.state.get_state")
    def test_load_state_uses_global(self, mock_get_state):
        """load_state should use global state manager."""
        mock_manager = Mock()
        mock_manager.load_state.return_value = True
        mock_get_state.return_value = mock_manager

        result = load_state()

        mock_manager.load_state.assert_called_once()
        assert result is True

    @patch("dockflare.state.get_state")
    def test_save_state_uses_global(self, mock_get_state):
        """save_state should use global state manager."""
        mock_manager = Mock()
        mock_manager.save_state.return_value = True
        mock_get_state.return_value = mock_manager

        result = save_state()

        mock_manager.save_state.assert_called_once()
        assert result is True

    @patch("dockflare.state.get_state")
    def test_get_managed_rules_uses_global(self, mock_get_state):
        """get_managed_rules should use global state manager."""
        mock_manager = Mock()
        mock_manager.list_rules.return_value = {"key": {"data": "value"}}
        mock_get_state.return_value = mock_manager

        result = get_managed_rules()

        mock_manager.list_rules.assert_called_once()
        assert result == {"key": {"data": "value"}}


class TestDataclasses:
    """Tests for dataclasses."""

    def test_managed_rule_defaults(self):
        """ManagedRule should have sensible defaults."""
        rule = ManagedRule(hostname="example.com", service="http://app:80")
        assert rule.status == "active"
        assert rule.source == "docker"
        assert rule.path is None
        assert rule.no_tls_verify is False

    def test_access_group_defaults(self):
        """AccessGroup should have sensible defaults."""
        group = AccessGroup(id="group-1", display_name="Test Group")
        assert group.session_duration == "24h"
        assert group.app_launcher_visible is False
        assert group.deletable is True

    def test_agent_defaults(self):
        """Agent should have sensible defaults."""
        agent = Agent(id="agent-1", name="Server 1")
        assert agent.status == "pending"
        assert agent.api_key_hash is None
