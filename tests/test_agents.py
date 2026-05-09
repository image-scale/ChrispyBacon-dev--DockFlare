"""Tests for multi-host agent support."""

import hashlib
import pytest
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from dockflare.agents import (
    AgentInfo,
    AgentRegistry,
    HeartbeatMonitor,
    ContainerDiscovery,
    get_agent_registry,
    get_heartbeat_monitor,
    get_container_discovery,
    enroll_agent,
    verify_agent_key,
    record_agent_heartbeat,
)


class TestAgentInfo:
    """Tests for AgentInfo dataclass."""

    def test_default_values(self):
        """AgentInfo has sensible defaults."""
        info = AgentInfo(id="abc123", name="test-agent")
        assert info.id == "abc123"
        assert info.name == "test-agent"
        assert info.status == "pending"
        assert info.api_key_hash == ""
        assert info.enrolled_at == ""
        assert info.last_seen is None
        assert info.hostname is None
        assert info.ip_address is None
        assert info.container_count == 0
        assert info.containers == []
        assert info.tunnel_id is None
        assert info.metadata == {}

    def test_with_all_fields(self):
        """AgentInfo accepts all fields."""
        info = AgentInfo(
            id="abc123",
            name="test-agent",
            status="active",
            api_key_hash="hash123",
            enrolled_at="2024-01-01T00:00:00Z",
            last_seen="2024-01-01T00:01:00Z",
            hostname="worker-1",
            ip_address="192.168.1.100",
            container_count=5,
            containers=[{"id": "c1", "name": "app"}],
            tunnel_id="tunnel-abc",
            metadata={"version": "1.0"},
        )
        assert info.status == "active"
        assert info.container_count == 5
        assert len(info.containers) == 1


class TestAgentRegistry:
    """Tests for AgentRegistry class."""

    @pytest.fixture
    def mock_state(self):
        """Create a mock state manager."""
        state = MagicMock()
        state._agents = {}

        def get_agent(agent_id):
            return state._agents.get(agent_id)

        def set_agent(agent_id, data):
            state._agents[agent_id] = data

        def list_agents():
            return dict(state._agents)

        def delete_agent(agent_id):
            if agent_id in state._agents:
                del state._agents[agent_id]
                return True
            return False

        state.get_agent = MagicMock(side_effect=get_agent)
        state.set_agent = MagicMock(side_effect=set_agent)
        state.list_agents = MagicMock(side_effect=list_agents)
        state.delete_agent = MagicMock(side_effect=delete_agent)
        state.save_state = MagicMock()
        return state

    @pytest.fixture
    def registry(self, mock_state):
        """Create a registry with mock state."""
        return AgentRegistry(state_manager=mock_state, heartbeat_timeout_seconds=60)

    def test_enroll_agent_returns_id_and_key(self, registry):
        """enroll_agent returns agent_id and api_key tuple."""
        agent_id, api_key = registry.enroll_agent(name="test-agent")
        assert agent_id is not None
        assert len(agent_id) == 16  # 8 bytes hex
        assert api_key is not None
        assert len(api_key) > 20  # URL-safe base64

    def test_enroll_agent_stores_data(self, registry, mock_state):
        """enroll_agent stores agent data in state."""
        agent_id, api_key = registry.enroll_agent(
            name="test-agent",
            hostname="worker-1",
            ip_address="192.168.1.100",
            tunnel_id="tunnel-abc",
            metadata={"version": "1.0"},
        )

        agent = mock_state._agents[agent_id]
        assert agent["name"] == "test-agent"
        assert agent["status"] == "pending"
        assert agent["hostname"] == "worker-1"
        assert agent["ip_address"] == "192.168.1.100"
        assert agent["tunnel_id"] == "tunnel-abc"
        assert agent["metadata"]["version"] == "1.0"
        assert agent["enrolled_at"] is not None

    def test_enroll_agent_hashes_api_key(self, registry, mock_state):
        """enroll_agent stores hashed API key, not plaintext."""
        agent_id, api_key = registry.enroll_agent(name="test-agent")

        agent = mock_state._agents[agent_id]
        expected_hash = hashlib.sha256(api_key.encode()).hexdigest()
        assert agent["api_key_hash"] == expected_hash

    def test_verify_api_key_valid(self, registry):
        """verify_api_key returns True for valid key."""
        agent_id, api_key = registry.enroll_agent(name="test-agent")
        assert registry.verify_api_key(agent_id, api_key) is True

    def test_verify_api_key_invalid(self, registry):
        """verify_api_key returns False for invalid key."""
        agent_id, api_key = registry.enroll_agent(name="test-agent")
        assert registry.verify_api_key(agent_id, "wrong-key") is False

    def test_verify_api_key_nonexistent_agent(self, registry):
        """verify_api_key returns False for non-existent agent."""
        assert registry.verify_api_key("nonexistent", "any-key") is False

    def test_record_heartbeat_updates_status(self, registry):
        """record_heartbeat sets agent status to active."""
        agent_id, _ = registry.enroll_agent(name="test-agent")

        result = registry.record_heartbeat(agent_id)

        assert result is True
        agent = registry.get_agent(agent_id)
        assert agent["status"] == "active"
        assert agent["last_seen"] is not None

    def test_record_heartbeat_updates_containers(self, registry):
        """record_heartbeat updates container information."""
        agent_id, _ = registry.enroll_agent(name="test-agent")

        containers = [{"id": "c1", "name": "app1"}, {"id": "c2", "name": "app2"}]
        registry.record_heartbeat(
            agent_id,
            container_count=2,
            containers=containers,
        )

        agent = registry.get_agent(agent_id)
        assert agent["container_count"] == 2
        assert len(agent["containers"]) == 2

    def test_record_heartbeat_updates_metadata(self, registry):
        """record_heartbeat updates metadata."""
        agent_id, _ = registry.enroll_agent(name="test-agent")

        registry.record_heartbeat(agent_id, metadata={"cpu": "50%"})

        agent = registry.get_agent(agent_id)
        assert agent["metadata"]["cpu"] == "50%"

    def test_record_heartbeat_nonexistent_agent(self, registry):
        """record_heartbeat returns False for non-existent agent."""
        result = registry.record_heartbeat("nonexistent")
        assert result is False

    def test_record_heartbeat_triggers_callbacks(self, registry):
        """record_heartbeat calls registered callbacks."""
        agent_id, _ = registry.enroll_agent(name="test-agent")

        callback_data = {}

        def callback(aid, agent):
            callback_data["agent_id"] = aid
            callback_data["status"] = agent["status"]

        registry.on_heartbeat(callback)
        registry.record_heartbeat(agent_id)

        assert callback_data["agent_id"] == agent_id
        assert callback_data["status"] == "active"

    def test_get_agent(self, registry):
        """get_agent returns agent data."""
        agent_id, _ = registry.enroll_agent(name="test-agent")
        agent = registry.get_agent(agent_id)
        assert agent["name"] == "test-agent"

    def test_get_agent_nonexistent(self, registry):
        """get_agent returns None for non-existent agent."""
        assert registry.get_agent("nonexistent") is None

    def test_list_agents(self, registry):
        """list_agents returns all registered agents."""
        registry.enroll_agent(name="agent-1")
        registry.enroll_agent(name="agent-2")

        agents = registry.list_agents()
        assert len(agents) == 2

    def test_list_agents_filter_by_status(self, registry):
        """list_agents can filter by status."""
        id1, _ = registry.enroll_agent(name="agent-1")
        id2, _ = registry.enroll_agent(name="agent-2")
        registry.record_heartbeat(id1)  # Makes agent-1 active

        active_agents = registry.list_agents(status="active")
        assert len(active_agents) == 1
        assert id1 in active_agents

        pending_agents = registry.list_agents(status="pending")
        assert len(pending_agents) == 1
        assert id2 in pending_agents

    def test_list_agents_exclude_inactive(self, registry, mock_state):
        """list_agents can exclude inactive agents."""
        id1, _ = registry.enroll_agent(name="agent-1")
        id2, _ = registry.enroll_agent(name="agent-2")
        mock_state._agents[id2]["status"] = "inactive"

        agents = registry.list_agents(include_inactive=False)
        assert len(agents) == 1
        assert id1 in agents

    def test_delete_agent(self, registry):
        """delete_agent removes agent from registry."""
        agent_id, _ = registry.enroll_agent(name="test-agent")
        assert registry.get_agent(agent_id) is not None

        result = registry.delete_agent(agent_id)

        assert result is True
        assert registry.get_agent(agent_id) is None

    def test_delete_agent_nonexistent(self, registry):
        """delete_agent returns False for non-existent agent."""
        result = registry.delete_agent("nonexistent")
        assert result is False

    def test_rotate_api_key(self, registry):
        """rotate_api_key generates new API key."""
        agent_id, old_key = registry.enroll_agent(name="test-agent")

        new_key = registry.rotate_api_key(agent_id)

        assert new_key is not None
        assert new_key != old_key
        assert registry.verify_api_key(agent_id, new_key) is True
        assert registry.verify_api_key(agent_id, old_key) is False

    def test_rotate_api_key_nonexistent(self, registry):
        """rotate_api_key returns None for non-existent agent."""
        result = registry.rotate_api_key("nonexistent")
        assert result is None

    def test_check_timeouts_marks_inactive(self, registry, mock_state):
        """check_timeouts marks timed-out agents as inactive."""
        agent_id, _ = registry.enroll_agent(name="test-agent")
        registry.record_heartbeat(agent_id)

        # Simulate old last_seen
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        mock_state._agents[agent_id]["last_seen"] = old_time

        timed_out = registry.check_timeouts()

        assert agent_id in timed_out
        assert mock_state._agents[agent_id]["status"] == "inactive"

    def test_check_timeouts_ignores_recent(self, registry):
        """check_timeouts does not mark recently active agents."""
        agent_id, _ = registry.enroll_agent(name="test-agent")
        registry.record_heartbeat(agent_id)

        timed_out = registry.check_timeouts()

        assert agent_id not in timed_out
        agent = registry.get_agent(agent_id)
        assert agent["status"] == "active"

    def test_check_timeouts_handles_z_suffix(self, registry, mock_state):
        """check_timeouts handles ISO timestamps with Z suffix."""
        agent_id, _ = registry.enroll_agent(name="test-agent")
        registry.record_heartbeat(agent_id)

        old_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        mock_state._agents[agent_id]["last_seen"] = old_time

        timed_out = registry.check_timeouts()
        assert agent_id in timed_out


class TestHeartbeatMonitor:
    """Tests for HeartbeatMonitor class."""

    @pytest.fixture
    def mock_registry(self):
        """Create a mock registry."""
        registry = MagicMock()
        registry.check_timeouts = MagicMock(return_value=[])
        return registry

    @pytest.fixture
    def monitor(self, mock_registry):
        """Create a heartbeat monitor."""
        return HeartbeatMonitor(mock_registry, check_interval_seconds=1)

    def test_start_and_stop(self, monitor):
        """Monitor can be started and stopped."""
        assert monitor.is_running is False

        monitor.start()
        assert monitor.is_running is True

        monitor.stop(timeout=2.0)
        assert monitor.is_running is False

    def test_start_twice_warns(self, monitor, caplog):
        """Starting monitor twice logs warning."""
        monitor.start()
        monitor.start()  # Second start should warn

        monitor.stop()
        assert "already running" in caplog.text

    def test_calls_check_timeouts(self, mock_registry):
        """Monitor periodically calls check_timeouts."""
        monitor = HeartbeatMonitor(mock_registry, check_interval_seconds=0.1)

        monitor.start()
        time.sleep(0.3)
        monitor.stop()

        assert mock_registry.check_timeouts.call_count >= 1

    def test_timeout_callback(self, mock_registry):
        """Monitor calls timeout callbacks when agents time out."""
        mock_registry.check_timeouts.return_value = ["agent-1", "agent-2"]
        monitor = HeartbeatMonitor(mock_registry, check_interval_seconds=0.1)

        timed_out_agents = []

        def callback(agents):
            timed_out_agents.extend(agents)

        monitor.on_timeout(callback)
        monitor.start()
        time.sleep(0.3)
        monitor.stop()

        assert "agent-1" in timed_out_agents
        assert "agent-2" in timed_out_agents


class TestContainerDiscovery:
    """Tests for ContainerDiscovery class."""

    @pytest.fixture
    def mock_registry(self):
        """Create a mock registry."""
        return MagicMock()

    @pytest.fixture
    def discovery(self, mock_registry):
        """Create a container discovery instance."""
        return ContainerDiscovery(mock_registry)

    def test_process_agent_containers(self, discovery):
        """process_agent_containers extracts routes from containers."""
        containers = [
            {
                "id": "container-1",
                "name": "app",
                "labels": {
                    "dockflare.enable": "true",
                    "dockflare.hostname": "app.example.com",
                    "dockflare.service": "http://app:8080",
                },
            }
        ]

        routes = discovery.process_agent_containers("agent-1", containers)

        assert len(routes) == 1
        assert routes[0].hostname == "app.example.com"
        assert routes[0].service == "http://app:8080"
        assert routes[0].container_id == "agent:agent-1:container-1"

    def test_process_agent_containers_multiple(self, discovery):
        """process_agent_containers handles multiple containers."""
        containers = [
            {
                "id": "c1",
                "name": "app1",
                "labels": {
                    "dockflare.enable": "true",
                    "dockflare.hostname": "app1.example.com",
                    "dockflare.service": "http://app1:8080",
                },
            },
            {
                "id": "c2",
                "name": "app2",
                "labels": {
                    "dockflare.enable": "true",
                    "dockflare.hostname": "app2.example.com",
                    "dockflare.service": "http://app2:8080",
                },
            },
        ]

        routes = discovery.process_agent_containers("agent-1", containers)
        assert len(routes) == 2

    def test_get_all_routes(self, discovery):
        """get_all_routes returns routes from all agents."""
        containers1 = [
            {
                "id": "c1",
                "name": "app1",
                "labels": {
                    "dockflare.enable": "true",
                    "dockflare.hostname": "app1.example.com",
                    "dockflare.service": "http://app1:8080",
                },
            }
        ]
        containers2 = [
            {
                "id": "c2",
                "name": "app2",
                "labels": {
                    "dockflare.enable": "true",
                    "dockflare.hostname": "app2.example.com",
                    "dockflare.service": "http://app2:8080",
                },
            }
        ]

        discovery.process_agent_containers("agent-1", containers1)
        discovery.process_agent_containers("agent-2", containers2)

        all_routes = discovery.get_all_routes()
        assert len(all_routes) == 2

    def test_get_agent_routes(self, discovery):
        """get_agent_routes returns routes for specific agent."""
        containers = [
            {
                "id": "c1",
                "name": "app",
                "labels": {
                    "dockflare.enable": "true",
                    "dockflare.hostname": "app.example.com",
                    "dockflare.service": "http://app:8080",
                },
            }
        ]

        discovery.process_agent_containers("agent-1", containers)

        routes = discovery.get_agent_routes("agent-1")
        assert len(routes) == 1

        routes = discovery.get_agent_routes("agent-2")
        assert len(routes) == 0

    def test_clear_agent_routes(self, discovery):
        """clear_agent_routes removes routes for an agent."""
        containers = [
            {
                "id": "c1",
                "name": "app",
                "labels": {
                    "dockflare.enable": "true",
                    "dockflare.hostname": "app.example.com",
                    "dockflare.service": "http://app:8080",
                },
            }
        ]

        discovery.process_agent_containers("agent-1", containers)
        assert len(discovery.get_agent_routes("agent-1")) == 1

        discovery.clear_agent_routes("agent-1")
        assert len(discovery.get_agent_routes("agent-1")) == 0


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_get_agent_registry_singleton(self):
        """get_agent_registry returns singleton instance."""
        import dockflare.agents as agents_module

        agents_module._agent_registry = None

        registry1 = get_agent_registry()
        registry2 = get_agent_registry()
        assert registry1 is registry2

    def test_get_heartbeat_monitor_singleton(self):
        """get_heartbeat_monitor returns singleton instance."""
        import dockflare.agents as agents_module

        agents_module._heartbeat_monitor = None
        agents_module._agent_registry = None

        monitor1 = get_heartbeat_monitor()
        monitor2 = get_heartbeat_monitor()
        assert monitor1 is monitor2

    def test_get_container_discovery_singleton(self):
        """get_container_discovery returns singleton instance."""
        import dockflare.agents as agents_module

        agents_module._container_discovery = None
        agents_module._agent_registry = None

        discovery1 = get_container_discovery()
        discovery2 = get_container_discovery()
        assert discovery1 is discovery2

    @patch("dockflare.agents.get_agent_registry")
    def test_enroll_agent_convenience(self, mock_get_registry):
        """enroll_agent convenience function delegates to registry."""
        mock_registry = MagicMock()
        mock_registry.enroll_agent.return_value = ("agent-id", "api-key")
        mock_get_registry.return_value = mock_registry

        agent_id, api_key = enroll_agent(
            name="test-agent",
            hostname="worker-1",
            tunnel_id="tunnel-abc",
        )

        assert agent_id == "agent-id"
        assert api_key == "api-key"
        mock_registry.enroll_agent.assert_called_once_with(
            name="test-agent",
            hostname="worker-1",
            tunnel_id="tunnel-abc",
        )

    @patch("dockflare.agents.get_agent_registry")
    def test_verify_agent_key_convenience(self, mock_get_registry):
        """verify_agent_key convenience function delegates to registry."""
        mock_registry = MagicMock()
        mock_registry.verify_api_key.return_value = True
        mock_get_registry.return_value = mock_registry

        result = verify_agent_key("agent-id", "api-key")

        assert result is True
        mock_registry.verify_api_key.assert_called_once_with("agent-id", "api-key")

    @patch("dockflare.agents.get_agent_registry")
    def test_record_agent_heartbeat_convenience(self, mock_get_registry):
        """record_agent_heartbeat convenience function delegates to registry."""
        mock_registry = MagicMock()
        mock_registry.record_heartbeat.return_value = True
        mock_get_registry.return_value = mock_registry

        containers = [{"id": "c1", "name": "app"}]
        result = record_agent_heartbeat(
            "agent-id",
            container_count=1,
            containers=containers,
        )

        assert result is True
        mock_registry.record_heartbeat.assert_called_once_with(
            "agent-id",
            container_count=1,
            containers=containers,
        )
