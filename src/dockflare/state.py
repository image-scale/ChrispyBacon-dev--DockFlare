"""
State management for DockFlare.

Handles persistence and loading of managed rules, access groups, and agents.
Provides thread-safe access to application state.
"""

import json
import logging
import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import settings


@dataclass
class ManagedRule:
    """A managed tunnel ingress rule."""

    hostname: str
    service: str
    status: str = "active"
    source: str = "docker"
    path: Optional[str] = None
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None
    tunnel_id: Optional[str] = None
    tunnel_name: Optional[str] = None
    dns_record_id: Optional[str] = None
    access_app_id: Optional[str] = None
    access_groups: List[str] = field(default_factory=list)
    no_tls_verify: bool = False
    origin_server_name: Optional[str] = None
    http_host_header: Optional[str] = None
    http2_origin: bool = False
    disable_chunked_encoding: bool = False
    container_id: Optional[str] = None
    container_name: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    delete_at: Optional[str] = None


@dataclass
class AccessGroup:
    """An access control group."""

    id: str
    display_name: str
    session_duration: str = "24h"
    app_launcher_visible: bool = False
    public_mode: bool = False
    cloudflare_policy_id: Optional[str] = None
    system_policy: bool = False
    deletable: bool = True


@dataclass
class Agent:
    """A remote agent."""

    id: str
    name: str
    status: str = "pending"
    api_key_hash: Optional[str] = None
    last_heartbeat: Optional[str] = None
    assigned_tunnel_id: Optional[str] = None
    enrolled_at: Optional[str] = None


class StateManager:
    """Thread-safe state manager for application state."""

    def __init__(self, state_file: str = None):
        """
        Initialize the state manager.

        Args:
            state_file: Path to state file (defaults to settings.STATE_FILE_PATH)
        """
        self.state_file = state_file or settings.STATE_FILE_PATH
        self._lock = threading.RLock()

        self._managed_rules: Dict[str, Dict] = {}
        self._access_groups: Dict[str, Dict] = {}
        self._agents: Dict[str, Dict] = {}

    @property
    def managed_rules(self) -> Dict[str, Dict]:
        """Get managed rules (not thread-safe for iteration)."""
        return self._managed_rules

    @property
    def access_groups(self) -> Dict[str, Dict]:
        """Get access groups (not thread-safe for iteration)."""
        return self._access_groups

    @property
    def agents(self) -> Dict[str, Dict]:
        """Get agents (not thread-safe for iteration)."""
        return self._agents

    def get_rule(self, key: str) -> Optional[Dict]:
        """Get a rule by key (thread-safe)."""
        with self._lock:
            return self._managed_rules.get(key)

    def set_rule(self, key: str, rule: Dict):
        """Set a rule by key (thread-safe)."""
        with self._lock:
            self._managed_rules[key] = rule

    def delete_rule(self, key: str) -> bool:
        """Delete a rule by key (thread-safe)."""
        with self._lock:
            if key in self._managed_rules:
                del self._managed_rules[key]
                return True
            return False

    def list_rules(self) -> Dict[str, Dict]:
        """Get a copy of all rules (thread-safe)."""
        with self._lock:
            return dict(self._managed_rules)

    def get_access_group(self, group_id: str) -> Optional[Dict]:
        """Get an access group by ID (thread-safe)."""
        with self._lock:
            return self._access_groups.get(group_id)

    def set_access_group(self, group_id: str, group: Dict):
        """Set an access group by ID (thread-safe)."""
        with self._lock:
            self._access_groups[group_id] = group

    def delete_access_group(self, group_id: str) -> bool:
        """Delete an access group by ID (thread-safe)."""
        with self._lock:
            if group_id in self._access_groups:
                del self._access_groups[group_id]
                return True
            return False

    def list_access_groups(self) -> Dict[str, Dict]:
        """Get a copy of all access groups (thread-safe)."""
        with self._lock:
            return dict(self._access_groups)

    def get_agent(self, agent_id: str) -> Optional[Dict]:
        """Get an agent by ID (thread-safe)."""
        with self._lock:
            return self._agents.get(agent_id)

    def set_agent(self, agent_id: str, agent: Dict):
        """Set an agent by ID (thread-safe)."""
        with self._lock:
            self._agents[agent_id] = agent

    def delete_agent(self, agent_id: str) -> bool:
        """Delete an agent by ID (thread-safe)."""
        with self._lock:
            if agent_id in self._agents:
                del self._agents[agent_id]
                return True
            return False

    def list_agents(self) -> Dict[str, Dict]:
        """Get a copy of all agents (thread-safe)."""
        with self._lock:
            return dict(self._agents)

    def load_state(self) -> bool:
        """
        Load state from the state file.

        Returns:
            True if state was loaded, False if file doesn't exist or error
        """
        logging.info(f"Loading state from {self.state_file}")

        with self._lock:
            self._managed_rules.clear()
            self._access_groups.clear()
            self._agents.clear()

            if not os.path.exists(self.state_file):
                logging.info(f"State file not found, starting with empty state")
                return False

            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)

                if isinstance(data, dict) and "managed_rules" in data:
                    self._managed_rules.update(data.get("managed_rules", {}))
                    self._access_groups.update(data.get("access_groups", {}))
                    self._agents.update(data.get("agents", {}))
                else:
                    self._managed_rules.update(data)

                logging.info(
                    f"Loaded state: {len(self._managed_rules)} rules, "
                    f"{len(self._access_groups)} access groups, "
                    f"{len(self._agents)} agents"
                )
                return True

            except json.JSONDecodeError as e:
                logging.error(f"Invalid JSON in state file: {e}")
                return False
            except IOError as e:
                logging.error(f"Error reading state file: {e}")
                return False

    def save_state(self) -> bool:
        """
        Save state to the state file.

        Returns:
            True on success, False on error
        """
        logging.info(f"Saving state to {self.state_file}")

        with self._lock:
            data = {
                "managed_rules": self._managed_rules,
                "access_groups": self._access_groups,
                "agents": self._agents,
            }

            state_dir = os.path.dirname(self.state_file)
            if state_dir and not os.path.exists(state_dir):
                try:
                    os.makedirs(state_dir, exist_ok=True)
                except OSError as e:
                    logging.error(f"Error creating state directory: {e}")
                    return False

            try:
                with open(self.state_file, "w") as f:
                    json.dump(data, f, indent=2, default=str)
                logging.info(f"Saved state successfully")
                return True

            except IOError as e:
                logging.error(f"Error writing state file: {e}")
                return False

    def clear_state(self):
        """Clear all state (thread-safe)."""
        with self._lock:
            self._managed_rules.clear()
            self._access_groups.clear()
            self._agents.clear()


def get_rule_key(hostname: str, path: Optional[str] = None) -> str:
    """Generate a unique key for a rule based on hostname and path."""
    path_str = str(path or "").strip()
    return f"{hostname}|{path_str}"


# Module-level state instance
_state: StateManager = None


def get_state() -> StateManager:
    """Get or create the global state manager."""
    global _state
    if _state is None:
        _state = StateManager()
    return _state


def load_state() -> bool:
    """Load state using the global state manager."""
    return get_state().load_state()


def save_state() -> bool:
    """Save state using the global state manager."""
    return get_state().save_state()


def get_managed_rules() -> Dict[str, Dict]:
    """Get all managed rules."""
    return get_state().list_rules()


def get_access_groups() -> Dict[str, Dict]:
    """Get all access groups."""
    return get_state().list_access_groups()


def get_agents() -> Dict[str, Dict]:
    """Get all agents."""
    return get_state().list_agents()
