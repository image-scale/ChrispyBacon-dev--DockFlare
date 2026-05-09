"""Tests for tunnel management."""

import pytest
from unittest.mock import Mock, patch, MagicMock

from dockflare.tunnels import (
    TunnelManager,
    TunnelInfo,
    build_ingress_entry,
    build_ingress_list,
    find_tunnel,
    create_tunnel,
    get_tunnel_config,
    update_tunnel_config,
    _service_supports_origin_request,
    _is_catch_all_rule,
    _ingress_to_comparable,
)
from dockflare.labels import RouteConfig
from dockflare.cloudflare_api import CloudflareAPIError


class TestTunnelManager:
    """Tests for TunnelManager class."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock CloudflareClient."""
        return Mock()

    @pytest.fixture
    def manager(self, mock_client):
        """Create a TunnelManager with mock client."""
        return TunnelManager(client=mock_client, account_id="test-account")

    def test_find_tunnel_returns_id_and_token(self, manager, mock_client):
        """Should return tunnel_id and token for existing tunnel."""
        mock_client.request.side_effect = [
            {"success": True, "result": [{"id": "tunnel-123", "name": "my-tunnel"}]},
            {"success": True, "result": "x" * 100},
        ]

        tunnel_id, token = manager.find_tunnel("my-tunnel")

        assert tunnel_id == "tunnel-123"
        assert token == "x" * 100

    def test_find_tunnel_returns_none_when_not_found(self, manager, mock_client):
        """Should return (None, None) for non-existent tunnel."""
        mock_client.request.return_value = {"success": True, "result": []}

        tunnel_id, token = manager.find_tunnel("non-existent")

        assert tunnel_id is None
        assert token is None

    def test_find_tunnel_raises_on_api_error(self, manager, mock_client):
        """Should raise CloudflareAPIError on API failure."""
        mock_client.request.side_effect = CloudflareAPIError("API error")

        with pytest.raises(CloudflareAPIError):
            manager.find_tunnel("my-tunnel")

    def test_create_tunnel_returns_id_and_token(self, manager, mock_client):
        """Should create tunnel and return id and token."""
        mock_client.request.return_value = {
            "success": True,
            "result": {"id": "new-tunnel-123", "token": "new-token-abc"},
        }

        tunnel_id, token = manager.create_tunnel("new-tunnel")

        assert tunnel_id == "new-tunnel-123"
        assert token == "new-token-abc"
        mock_client.request.assert_called_once()

    def test_create_tunnel_raises_on_missing_data(self, manager, mock_client):
        """Should raise ValueError if response missing id or token."""
        mock_client.request.return_value = {"success": True, "result": {}}

        with pytest.raises(ValueError):
            manager.create_tunnel("new-tunnel")

    def test_get_tunnel_token(self, manager, mock_client):
        """Should retrieve tunnel connection token."""
        mock_client.request.return_value = {"success": True, "result": "a" * 100}

        token = manager.get_tunnel_token("tunnel-123")

        assert token == "a" * 100

    def test_get_tunnel_token_returns_none_for_invalid(self, manager, mock_client):
        """Should return None for invalid/short token."""
        mock_client.request.return_value = {"success": True, "result": "short"}

        token = manager.get_tunnel_token("tunnel-123")

        assert token is None

    def test_get_tunnel_config(self, manager, mock_client):
        """Should retrieve tunnel configuration."""
        mock_client.request.return_value = {
            "success": True,
            "result": {
                "config": {
                    "ingress": [
                        {"hostname": "app.example.com", "service": "http://app:80"},
                        {"service": "http_status:404"},
                    ]
                }
            },
        }

        config = manager.get_tunnel_config("tunnel-123")

        assert config is not None
        assert "ingress" in config
        assert len(config["ingress"]) == 2

    def test_get_tunnel_config_returns_none_on_error(self, manager, mock_client):
        """Should return None on API error."""
        mock_client.request.side_effect = CloudflareAPIError("API error")

        config = manager.get_tunnel_config("tunnel-123")

        assert config is None

    def test_update_tunnel_config(self, manager, mock_client):
        """Should update tunnel ingress configuration."""
        mock_client.request.return_value = {"success": True, "result": {}}

        ingress = [
            {"hostname": "app.example.com", "service": "http://app:80"},
        ]
        result = manager.update_tunnel_config("tunnel-123", ingress)

        assert result is True
        call_args = mock_client.request.call_args
        config = call_args.kwargs["json_data"]["config"]["ingress"]
        assert any(r.get("service") == "http_status:404" for r in config)

    def test_update_tunnel_config_returns_false_on_error(self, manager, mock_client):
        """Should return False on API error."""
        mock_client.request.side_effect = CloudflareAPIError("API error")

        result = manager.update_tunnel_config("tunnel-123", [])

        assert result is False


class TestBuildIngressEntry:
    """Tests for build_ingress_entry function."""

    def test_basic_entry(self):
        """Should create basic ingress entry."""
        route = RouteConfig(hostname="app.example.com", service="http://app:8080")

        entry = build_ingress_entry(route)

        assert entry["hostname"] == "app.example.com"
        assert entry["service"] == "http://app:8080"

    def test_entry_with_path(self):
        """Should include path in entry."""
        route = RouteConfig(
            hostname="app.example.com",
            service="http://app:8080",
            path="/api",
        )

        entry = build_ingress_entry(route)

        assert entry["path"] == "/api"

    def test_entry_with_origin_request(self):
        """Should include originRequest settings for HTTP services."""
        route = RouteConfig(
            hostname="app.example.com",
            service="https://app:443",
            no_tls_verify=True,
            origin_server_name="origin.local",
            http_host_header="custom-host",
        )

        entry = build_ingress_entry(route)

        assert "originRequest" in entry
        assert entry["originRequest"]["noTLSVerify"] is True
        assert entry["originRequest"]["originServerName"] == "origin.local"
        assert entry["originRequest"]["httpHostHeader"] == "custom-host"

    def test_no_origin_request_for_tcp(self):
        """Should not include originRequest for TCP services."""
        route = RouteConfig(
            hostname="ssh.example.com",
            service="tcp://app:22",
            no_tls_verify=True,
        )

        entry = build_ingress_entry(route)

        assert "originRequest" not in entry

    def test_entry_with_http2_origin(self):
        """Should include http2Origin setting."""
        route = RouteConfig(
            hostname="app.example.com",
            service="https://app:443",
            http2_origin=True,
        )

        entry = build_ingress_entry(route)

        assert entry["originRequest"]["http2Origin"] is True


class TestBuildIngressList:
    """Tests for build_ingress_list function."""

    def test_creates_list_with_catch_all(self):
        """Should create list with catch-all 404 at end."""
        routes = [
            RouteConfig(hostname="app.example.com", service="http://app:80"),
        ]

        ingress = build_ingress_list(routes)

        assert len(ingress) == 2
        assert ingress[-1]["service"] == "http_status:404"

    def test_deduplicates_entries(self):
        """Should deduplicate identical entries."""
        routes = [
            RouteConfig(hostname="app.example.com", service="http://app:80"),
            RouteConfig(hostname="app.example.com", service="http://app:80"),
        ]

        ingress = build_ingress_list(routes)

        assert len(ingress) == 2

    def test_multiple_different_entries(self):
        """Should include all different entries."""
        routes = [
            RouteConfig(hostname="app.example.com", service="http://app:80"),
            RouteConfig(hostname="api.example.com", service="http://api:3000"),
        ]

        ingress = build_ingress_list(routes)

        assert len(ingress) == 3


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_service_supports_origin_request_http(self):
        """Should return True for HTTP/HTTPS services."""
        assert _service_supports_origin_request("http://app:80") is True
        assert _service_supports_origin_request("https://app:443") is True
        assert _service_supports_origin_request("HTTP://APP:80") is True

    def test_service_supports_origin_request_other(self):
        """Should return False for non-HTTP services."""
        assert _service_supports_origin_request("tcp://app:22") is False
        assert _service_supports_origin_request("ssh://app:22") is False
        assert _service_supports_origin_request("bastion") is False

    def test_is_catch_all_rule(self):
        """Should detect catch-all rules."""
        assert _is_catch_all_rule({"service": "http_status:404"}) is True
        assert _is_catch_all_rule({"hostname": "", "service": "http://app:80"}) is True
        assert _is_catch_all_rule({"hostname": "app.example.com", "service": "http://app:80"}) is False

    def test_ingress_to_comparable(self):
        """Should create comparable tuple."""
        rule = {"hostname": "app.example.com", "service": "http://app:80", "path": "/api"}
        result = _ingress_to_comparable(rule)
        assert result == ("app.example.com", "http://app:80", "/api")

    def test_ingress_to_comparable_with_missing_fields(self):
        """Should handle missing fields."""
        rule = {"service": "http://app:80"}
        result = _ingress_to_comparable(rule)
        assert result == ("", "http://app:80", "")


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    @patch("dockflare.tunnels.get_manager")
    def test_find_tunnel_uses_manager(self, mock_get_manager):
        """find_tunnel should use the default manager."""
        mock_manager = Mock()
        mock_manager.find_tunnel.return_value = ("tunnel-123", "token-abc")
        mock_get_manager.return_value = mock_manager

        result = find_tunnel("my-tunnel")

        mock_manager.find_tunnel.assert_called_once_with("my-tunnel")
        assert result == ("tunnel-123", "token-abc")

    @patch("dockflare.tunnels.get_manager")
    def test_create_tunnel_uses_manager(self, mock_get_manager):
        """create_tunnel should use the default manager."""
        mock_manager = Mock()
        mock_manager.create_tunnel.return_value = ("tunnel-123", "token-abc")
        mock_get_manager.return_value = mock_manager

        result = create_tunnel("my-tunnel")

        mock_manager.create_tunnel.assert_called_once_with("my-tunnel")
        assert result == ("tunnel-123", "token-abc")

    @patch("dockflare.tunnels.get_manager")
    def test_get_tunnel_config_uses_manager(self, mock_get_manager):
        """get_tunnel_config should use the default manager."""
        mock_manager = Mock()
        mock_manager.get_tunnel_config.return_value = {"ingress": []}
        mock_get_manager.return_value = mock_manager

        result = get_tunnel_config("tunnel-123")

        mock_manager.get_tunnel_config.assert_called_once_with("tunnel-123")
        assert result == {"ingress": []}

    @patch("dockflare.tunnels.get_manager")
    def test_update_tunnel_config_uses_manager(self, mock_get_manager):
        """update_tunnel_config should use the default manager."""
        mock_manager = Mock()
        mock_manager.update_tunnel_config.return_value = True
        mock_get_manager.return_value = mock_manager

        result = update_tunnel_config("tunnel-123", [])

        mock_manager.update_tunnel_config.assert_called_once_with("tunnel-123", [])
        assert result is True


class TestTunnelInfo:
    """Tests for TunnelInfo dataclass."""

    def test_default_values(self):
        """Should have sensible defaults."""
        info = TunnelInfo(id="tunnel-123", name="my-tunnel")
        assert info.token is None
        assert info.status == "unknown"

    def test_with_all_values(self):
        """Should accept all values."""
        info = TunnelInfo(
            id="tunnel-123",
            name="my-tunnel",
            token="token-abc",
            status="active",
        )
        assert info.id == "tunnel-123"
        assert info.name == "my-tunnel"
        assert info.token == "token-abc"
        assert info.status == "active"
