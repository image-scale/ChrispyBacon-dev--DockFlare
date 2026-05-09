"""
Multi-host agent support.

Provides key management, heartbeat monitoring, and remote container discovery
for agents running on remote Docker hosts.
"""

import hashlib
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set

from . import settings
from .state import get_state, StateManager


@dataclass
class AgentInfo:
    """Information about a registered agent."""

    id: str
    name: str
    status: str = "pending"
    api_key_hash: str = ""
    enrolled_at: str = ""
    last_seen: Optional[str] = None
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    container_count: int = 0
    containers: List[Dict[str, Any]] = field(default_factory=list)
    tunnel_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgentRegistry:
    """
    Registry for managing remote agents.

    Handles agent enrollment, authentication, and status tracking.
    """

    def __init__(
        self,
        state_manager: StateManager = None,
        heartbeat_timeout_seconds: int = None,
    ):
        """
        Initialize the agent registry.

        Args:
            state_manager: State manager for persistence
            heartbeat_timeout_seconds: Timeout before marking agent inactive
        """
        self._state = state_manager
        self._heartbeat_timeout = heartbeat_timeout_seconds or getattr(
            settings, "AGENT_HEARTBEAT_TIMEOUT", 60
        )
        self._lock = threading.RLock()
        self._heartbeat_callbacks: List[Callable[[str, Dict], None]] = []

    @property
    def state_manager(self) -> StateManager:
        """Get state manager."""
        if self._state is None:
            self._state = get_state()
        return self._state

    def enroll_agent(
        self,
        name: str,
        hostname: str = None,
        ip_address: str = None,
        tunnel_id: str = None,
        metadata: Dict[str, Any] = None,
    ) -> tuple[str, str]:
        """
        Enroll a new agent.

        Args:
            name: Agent display name
            hostname: Agent hostname
            ip_address: Agent IP address
            tunnel_id: Assigned tunnel ID
            metadata: Additional metadata

        Returns:
            Tuple of (agent_id, api_key)
        """
        with self._lock:
            agent_id = secrets.token_hex(8)
            api_key = secrets.token_urlsafe(32)
            api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

            agent_data = {
                "id": agent_id,
                "name": name,
                "status": "pending",
                "api_key_hash": api_key_hash,
                "enrolled_at": datetime.now(timezone.utc).isoformat(),
                "last_seen": None,
                "hostname": hostname,
                "ip_address": ip_address,
                "container_count": 0,
                "containers": [],
                "tunnel_id": tunnel_id,
                "metadata": metadata or {},
            }

            self.state_manager.set_agent(agent_id, agent_data)
            self.state_manager.save_state()

            logging.info(f"Enrolled new agent: {name} ({agent_id})")

            return agent_id, api_key

    def verify_api_key(self, agent_id: str, api_key: str) -> bool:
        """
        Verify an agent's API key.

        Args:
            agent_id: Agent ID
            api_key: API key to verify

        Returns:
            True if valid, False otherwise
        """
        agent = self.state_manager.get_agent(agent_id)
        if not agent:
            return False

        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        return agent.get("api_key_hash") == api_key_hash

    def record_heartbeat(
        self,
        agent_id: str,
        container_count: int = None,
        containers: List[Dict] = None,
        metadata: Dict[str, Any] = None,
    ) -> bool:
        """
        Record a heartbeat from an agent.

        Args:
            agent_id: Agent ID
            container_count: Number of containers
            containers: Container information
            metadata: Additional metadata

        Returns:
            True if successful
        """
        with self._lock:
            agent = self.state_manager.get_agent(agent_id)
            if not agent:
                return False

            now = datetime.now(timezone.utc).isoformat()
            agent["status"] = "active"
            agent["last_seen"] = now

            if container_count is not None:
                agent["container_count"] = container_count

            if containers is not None:
                agent["containers"] = containers

            if metadata:
                agent["metadata"].update(metadata)

            self.state_manager.save_state()

            for callback in self._heartbeat_callbacks:
                try:
                    callback(agent_id, agent)
                except Exception as e:
                    logging.error(f"Error in heartbeat callback: {e}")

            return True

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get agent information."""
        return self.state_manager.get_agent(agent_id)

    def list_agents(
        self,
        status: str = None,
        include_inactive: bool = True,
    ) -> Dict[str, Dict[str, Any]]:
        """
        List registered agents.

        Args:
            status: Filter by status
            include_inactive: Include inactive agents

        Returns:
            Dictionary of agent_id -> agent_data
        """
        agents = self.state_manager.list_agents()

        if status:
            agents = {
                k: v for k, v in agents.items()
                if v.get("status") == status
            }

        if not include_inactive:
            agents = {
                k: v for k, v in agents.items()
                if v.get("status") != "inactive"
            }

        return agents

    def delete_agent(self, agent_id: str) -> bool:
        """
        Delete an agent.

        Args:
            agent_id: Agent ID to delete

        Returns:
            True if deleted
        """
        with self._lock:
            if self.state_manager.delete_agent(agent_id):
                self.state_manager.save_state()
                logging.info(f"Deleted agent: {agent_id}")
                return True
            return False

    def rotate_api_key(self, agent_id: str) -> Optional[str]:
        """
        Rotate an agent's API key.

        Args:
            agent_id: Agent ID

        Returns:
            New API key or None if agent not found
        """
        with self._lock:
            agent = self.state_manager.get_agent(agent_id)
            if not agent:
                return None

            new_api_key = secrets.token_urlsafe(32)
            api_key_hash = hashlib.sha256(new_api_key.encode()).hexdigest()
            agent["api_key_hash"] = api_key_hash
            self.state_manager.save_state()

            logging.info(f"Rotated API key for agent: {agent_id}")

            return new_api_key

    def on_heartbeat(self, callback: Callable[[str, Dict], None]):
        """Register a callback for heartbeat events."""
        self._heartbeat_callbacks.append(callback)

    def check_timeouts(self) -> List[str]:
        """
        Check for agents that have timed out.

        Returns:
            List of agent IDs that were marked inactive
        """
        marked_inactive = []
        now = datetime.now(timezone.utc)
        timeout_delta = timedelta(seconds=self._heartbeat_timeout)

        with self._lock:
            for agent_id, agent in self.state_manager.list_agents().items():
                if agent.get("status") != "active":
                    continue

                last_seen_str = agent.get("last_seen")
                if not last_seen_str:
                    continue

                try:
                    if last_seen_str.endswith("Z"):
                        last_seen_str = last_seen_str.replace("Z", "+00:00")
                    last_seen = datetime.fromisoformat(last_seen_str)
                    if last_seen.tzinfo is None:
                        last_seen = last_seen.replace(tzinfo=timezone.utc)

                    if now - last_seen > timeout_delta:
                        agent["status"] = "inactive"
                        marked_inactive.append(agent_id)
                        logging.warning(f"Agent {agent_id} marked inactive due to timeout")

                except Exception as e:
                    logging.error(f"Error checking timeout for agent {agent_id}: {e}")

            if marked_inactive:
                self.state_manager.save_state()

        return marked_inactive


class HeartbeatMonitor:
    """
    Background monitor for agent heartbeats.

    Periodically checks for timed-out agents and handles cleanup.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        check_interval_seconds: int = 30,
    ):
        """
        Initialize the heartbeat monitor.

        Args:
            registry: Agent registry to monitor
            check_interval_seconds: Interval between checks
        """
        self._registry = registry
        self._interval = check_interval_seconds
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._timeout_callbacks: List[Callable[[List[str]], None]] = []

    @property
    def is_running(self) -> bool:
        """Check if monitor is running."""
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        """Start the heartbeat monitor."""
        if self.is_running:
            logging.warning("Heartbeat monitor already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="HeartbeatMonitor",
            daemon=True,
        )
        self._thread.start()
        logging.info("Heartbeat monitor started")

    def stop(self, timeout: float = 5.0):
        """Stop the heartbeat monitor."""
        if not self.is_running:
            return

        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        logging.info("Heartbeat monitor stopped")

    def on_timeout(self, callback: Callable[[List[str]], None]):
        """Register a callback for timeout events."""
        self._timeout_callbacks.append(callback)

    def _monitor_loop(self):
        """Main monitoring loop."""
        while not self._stop_event.is_set():
            try:
                timed_out = self._registry.check_timeouts()
                if timed_out:
                    for callback in self._timeout_callbacks:
                        try:
                            callback(timed_out)
                        except Exception as e:
                            logging.error(f"Error in timeout callback: {e}")

            except Exception as e:
                logging.error(f"Error in heartbeat monitor: {e}")

            self._stop_event.wait(self._interval)


class ContainerDiscovery:
    """
    Discovers containers from remote agents.

    Processes container information from agent heartbeats and
    extracts route configurations.
    """

    def __init__(
        self,
        registry: AgentRegistry,
    ):
        """
        Initialize container discovery.

        Args:
            registry: Agent registry to use
        """
        self._registry = registry
        self._discovered_routes: Dict[str, List] = {}
        self._lock = threading.Lock()

    def process_agent_containers(
        self,
        agent_id: str,
        containers: List[Dict[str, Any]],
    ) -> List:
        """
        Process containers from an agent report.

        Args:
            agent_id: Agent ID
            containers: Container information from agent

        Returns:
            List of RouteConfig objects extracted
        """
        from .labels import parse_container_labels

        routes = []

        for container in containers:
            labels = container.get("labels", {})
            container_id = container.get("id", "")
            container_name = container.get("name", "")

            container_routes = parse_container_labels(
                labels,
                container_id=container_id,
                container_name=container_name,
            )

            for route in container_routes:
                route.container_id = f"agent:{agent_id}:{container_id}"

            routes.extend(container_routes)

        with self._lock:
            self._discovered_routes[agent_id] = routes

        return routes

    def get_all_routes(self) -> List:
        """
        Get all discovered routes from all agents.

        Returns:
            Combined list of routes from all agents
        """
        with self._lock:
            all_routes = []
            for agent_routes in self._discovered_routes.values():
                all_routes.extend(agent_routes)
            return all_routes

    def get_agent_routes(self, agent_id: str) -> List:
        """
        Get routes discovered from a specific agent.

        Args:
            agent_id: Agent ID

        Returns:
            List of routes from that agent
        """
        with self._lock:
            return list(self._discovered_routes.get(agent_id, []))

    def clear_agent_routes(self, agent_id: str):
        """Clear routes for an agent (e.g., when agent goes inactive)."""
        with self._lock:
            self._discovered_routes.pop(agent_id, None)


_agent_registry: Optional[AgentRegistry] = None
_heartbeat_monitor: Optional[HeartbeatMonitor] = None
_container_discovery: Optional[ContainerDiscovery] = None


def get_agent_registry() -> AgentRegistry:
    """Get or create the default agent registry."""
    global _agent_registry
    if _agent_registry is None:
        _agent_registry = AgentRegistry()
    return _agent_registry


def get_heartbeat_monitor() -> HeartbeatMonitor:
    """Get or create the default heartbeat monitor."""
    global _heartbeat_monitor
    if _heartbeat_monitor is None:
        _heartbeat_monitor = HeartbeatMonitor(get_agent_registry())
    return _heartbeat_monitor


def get_container_discovery() -> ContainerDiscovery:
    """Get or create the default container discovery."""
    global _container_discovery
    if _container_discovery is None:
        _container_discovery = ContainerDiscovery(get_agent_registry())
    return _container_discovery


def enroll_agent(
    name: str,
    hostname: str = None,
    tunnel_id: str = None,
) -> tuple[str, str]:
    """Convenience function to enroll an agent."""
    return get_agent_registry().enroll_agent(
        name=name,
        hostname=hostname,
        tunnel_id=tunnel_id,
    )


def verify_agent_key(agent_id: str, api_key: str) -> bool:
    """Convenience function to verify an agent's API key."""
    return get_agent_registry().verify_api_key(agent_id, api_key)


def record_agent_heartbeat(
    agent_id: str,
    container_count: int = None,
    containers: List[Dict] = None,
) -> bool:
    """Convenience function to record an agent heartbeat."""
    return get_agent_registry().record_heartbeat(
        agent_id,
        container_count=container_count,
        containers=containers,
    )
