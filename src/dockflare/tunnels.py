"""
Cloudflare Tunnel management.

Handles tunnel creation, configuration, and ingress rule management.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .cloudflare_api import CloudflareClient, CloudflareAPIError
from .labels import RouteConfig
from . import settings


@dataclass
class TunnelInfo:
    """Information about a Cloudflare Tunnel."""

    id: str
    name: str
    token: Optional[str] = None
    status: str = "unknown"


class TunnelManager:
    """Manager for Cloudflare Tunnel operations."""

    def __init__(self, client: CloudflareClient = None, account_id: str = None):
        """
        Initialize the tunnel manager.

        Args:
            client: CloudflareClient instance (creates one if not provided)
            account_id: Cloudflare account ID (defaults to settings)
        """
        self.client = client or CloudflareClient()
        self.account_id = account_id or settings.CF_ACCOUNT_ID

    def find_tunnel(self, name: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Find an existing tunnel by name.

        Args:
            name: Tunnel name to search for

        Returns:
            Tuple of (tunnel_id, token) or (None, None) if not found
        """
        logging.info(f"Finding tunnel '{name}' via API")

        try:
            response = self.client.request(
                "GET",
                f"/accounts/{self.account_id}/cfd_tunnel",
                params={"name": name, "is_deleted": "false"},
            )

            tunnels = response.get("result", [])
            if tunnels and isinstance(tunnels, list):
                for tunnel in tunnels:
                    if tunnel.get("name") == name:
                        tunnel_id = tunnel.get("id")
                        if tunnel_id:
                            logging.info(f"Found tunnel '{name}' with ID: {tunnel_id}")
                            token = self.get_tunnel_token(tunnel_id)
                            return tunnel_id, token

            logging.info(f"Tunnel '{name}' not found")
            return None, None

        except CloudflareAPIError as e:
            logging.error(f"API error finding tunnel '{name}': {e}")
            raise

    def create_tunnel(self, name: str) -> Tuple[str, str]:
        """
        Create a new tunnel.

        Args:
            name: Name for the new tunnel

        Returns:
            Tuple of (tunnel_id, token)

        Raises:
            CloudflareAPIError: If creation fails
            ValueError: If response is missing required data
        """
        logging.info(f"Creating tunnel '{name}'")

        try:
            response = self.client.request(
                "POST",
                f"/accounts/{self.account_id}/cfd_tunnel",
                json_data={"name": name, "config_src": "cloudflare"},
            )

            result = response.get("result", {})
            tunnel_id = result.get("id")
            token = result.get("token")

            if not tunnel_id or not token:
                raise ValueError("API response missing tunnel ID or token")

            logging.info(f"Created tunnel '{name}' with ID: {tunnel_id}")
            return tunnel_id, token

        except CloudflareAPIError as e:
            logging.error(f"API error creating tunnel '{name}': {e}")
            raise

    def get_tunnel_token(self, tunnel_id: str) -> Optional[str]:
        """
        Get the connection token for a tunnel.

        Args:
            tunnel_id: Tunnel ID

        Returns:
            Token string or None on error
        """
        logging.info(f"Getting token for tunnel {tunnel_id}")

        try:
            response = self.client.request(
                "GET",
                f"/accounts/{self.account_id}/cfd_tunnel/{tunnel_id}/token",
            )

            token = response.get("result")
            if token and len(token) >= 50:
                logging.info(f"Retrieved token for tunnel {tunnel_id}")
                return token
            else:
                logging.error(f"Token for tunnel {tunnel_id} appears invalid")
                return None

        except CloudflareAPIError as e:
            logging.error(f"API error getting tunnel token: {e}")
            return None

    def get_tunnel_config(self, tunnel_id: str) -> Optional[Dict]:
        """
        Get the current configuration for a tunnel.

        Args:
            tunnel_id: Tunnel ID

        Returns:
            Configuration dict with 'ingress' key, or None on error
        """
        logging.info(f"Getting config for tunnel {tunnel_id}")

        try:
            response = self.client.request(
                "GET",
                f"/accounts/{self.account_id}/cfd_tunnel/{tunnel_id}/configurations",
            )

            config = response.get("result", {}).get("config", {})
            return config

        except CloudflareAPIError as e:
            logging.error(f"API error getting tunnel config: {e}")
            return None

    def update_tunnel_config(self, tunnel_id: str, ingress: List[Dict]) -> bool:
        """
        Update the ingress configuration for a tunnel.

        Args:
            tunnel_id: Tunnel ID
            ingress: List of ingress rule dicts

        Returns:
            True on success, False on error
        """
        logging.info(f"Updating config for tunnel {tunnel_id} with {len(ingress)} ingress rules")

        if not any(_is_catch_all_rule(rule) for rule in ingress):
            ingress = list(ingress) + [{"service": "http_status:404"}]

        try:
            self.client.request(
                "PUT",
                f"/accounts/{self.account_id}/cfd_tunnel/{tunnel_id}/configurations",
                json_data={"config": {"ingress": ingress}},
            )
            logging.info(f"Updated tunnel {tunnel_id} config successfully")
            return True

        except CloudflareAPIError as e:
            logging.error(f"API error updating tunnel config: {e}")
            return False

    def delete_tunnel(self, tunnel_id: str) -> bool:
        """
        Delete a tunnel.

        Args:
            tunnel_id: Tunnel ID

        Returns:
            True on success, False on error
        """
        logging.info(f"Deleting tunnel {tunnel_id}")

        try:
            self.client.request(
                "DELETE",
                f"/accounts/{self.account_id}/cfd_tunnel/{tunnel_id}",
            )
            logging.info(f"Deleted tunnel {tunnel_id}")
            return True

        except CloudflareAPIError as e:
            logging.error(f"API error deleting tunnel: {e}")
            return False


def build_ingress_entry(route: RouteConfig) -> Dict[str, Any]:
    """
    Build an ingress rule dict from a route configuration.

    Args:
        route: RouteConfig object

    Returns:
        Ingress rule dict suitable for Cloudflare API
    """
    entry = {"service": route.service}

    if route.hostname:
        entry["hostname"] = route.hostname

    if route.path:
        path = route.path.strip()
        if path and path != "/":
            if not path.startswith("/"):
                path = "/" + path
            entry["path"] = path

    origin_request = {}
    if _service_supports_origin_request(route.service):
        if route.no_tls_verify:
            origin_request["noTLSVerify"] = True
        if route.origin_server_name:
            origin_request["originServerName"] = route.origin_server_name
        if route.http_host_header:
            origin_request["httpHostHeader"] = route.http_host_header
        if route.http2_origin:
            origin_request["http2Origin"] = True
        if route.disable_chunked_encoding:
            origin_request["disableChunkedEncoding"] = True

    if origin_request:
        entry["originRequest"] = origin_request

    return entry


def build_ingress_list(routes: List[RouteConfig]) -> List[Dict[str, Any]]:
    """
    Build a complete ingress list from route configurations.

    Includes a catch-all 404 rule at the end.

    Args:
        routes: List of RouteConfig objects

    Returns:
        List of ingress rule dicts
    """
    ingress = []
    seen = set()

    for route in routes:
        entry = build_ingress_entry(route)
        key = _ingress_to_comparable(entry)
        if key not in seen:
            ingress.append(entry)
            seen.add(key)

    ingress.append({"service": "http_status:404"})
    return ingress


def _service_supports_origin_request(service: str) -> bool:
    """Check if a service type supports originRequest settings."""
    if not isinstance(service, str):
        return False
    lower = service.lower()
    return lower.startswith("http://") or lower.startswith("https://")


def _is_catch_all_rule(rule: Dict) -> bool:
    """Check if a rule is a catch-all (no hostname)."""
    return not rule.get("hostname")


def _ingress_to_comparable(rule: Dict) -> Tuple:
    """Convert an ingress rule to a comparable tuple for deduplication."""
    hostname = rule.get("hostname") or ""
    service = rule.get("service") or ""
    path = rule.get("path") or ""
    return (hostname, service, path)


# Module-level convenience instance
_default_manager: TunnelManager = None


def get_manager() -> TunnelManager:
    """Get or create the default TunnelManager instance."""
    global _default_manager
    if _default_manager is None:
        _default_manager = TunnelManager()
    return _default_manager


def find_tunnel(name: str) -> Tuple[Optional[str], Optional[str]]:
    """Find a tunnel by name using the default manager."""
    return get_manager().find_tunnel(name)


def create_tunnel(name: str) -> Tuple[str, str]:
    """Create a tunnel using the default manager."""
    return get_manager().create_tunnel(name)


def get_tunnel_config(tunnel_id: str) -> Optional[Dict]:
    """Get tunnel config using the default manager."""
    return get_manager().get_tunnel_config(tunnel_id)


def update_tunnel_config(tunnel_id: str, ingress: List[Dict]) -> bool:
    """Update tunnel config using the default manager."""
    return get_manager().update_tunnel_config(tunnel_id, ingress)
