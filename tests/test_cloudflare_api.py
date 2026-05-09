"""Tests for the Cloudflare API client."""

import json
import time
import pytest
from unittest.mock import Mock, patch, MagicMock

from dockflare.cloudflare_api import (
    CloudflareClient,
    CloudflareAPIError,
    cf_request,
    get_zone_id,
    list_zones,
    get_client,
)


class TestCloudflareClient:
    """Tests for CloudflareClient class."""

    def test_init_with_defaults(self):
        """Should initialize with default settings."""
        with patch("dockflare.cloudflare_api.settings") as mock_settings:
            mock_settings.CF_API_TOKEN = "test-token"
            mock_settings.CF_ACCOUNT_ID = "test-account"
            mock_settings.CF_API_BASE_URL = "https://api.cloudflare.com/client/v4"
            mock_settings.CF_HEADERS = {"Content-Type": "application/json"}
            mock_settings.ACCOUNT_EMAIL_CACHE_TTL = 3600

            client = CloudflareClient()
            assert client.api_token == "test-token"
            assert client.account_id == "test-account"

    def test_init_with_custom_values(self):
        """Should initialize with custom values."""
        client = CloudflareClient(
            api_token="custom-token",
            account_id="custom-account",
            base_url="https://custom.api.com",
        )
        assert client.api_token == "custom-token"
        assert client.account_id == "custom-account"
        assert client.base_url == "https://custom.api.com"

    def test_get_headers_includes_auth(self):
        """Headers should include Authorization Bearer token."""
        client = CloudflareClient(api_token="my-token")
        headers = client._get_headers()
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer my-token"
        assert headers["Content-Type"] == "application/json"


class TestCloudflareClientRequest:
    """Tests for CloudflareClient.request method."""

    @pytest.fixture
    def client(self):
        """Create a client for testing."""
        return CloudflareClient(
            api_token="test-token",
            account_id="test-account",
            base_url="https://api.cloudflare.com/client/v4",
        )

    @patch("dockflare.cloudflare_api.requests.request")
    def test_successful_get_request(self, mock_request, client):
        """Should handle successful GET requests."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{"success": true, "result": {"id": "123"}}'
        mock_response.json.return_value = {"success": True, "result": {"id": "123"}}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        result = client.request("GET", "/zones")

        assert result["success"] is True
        assert result["result"]["id"] == "123"
        mock_request.assert_called_once()

    @patch("dockflare.cloudflare_api.requests.request")
    def test_request_with_json_data(self, mock_request, client):
        """Should send JSON payload in POST requests."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{"success": true, "result": {}}'
        mock_response.json.return_value = {"success": True, "result": {}}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        client.request("POST", "/zones", json_data={"name": "example.com"})

        call_kwargs = mock_request.call_args.kwargs
        assert call_kwargs["json"] == {"name": "example.com"}

    @patch("dockflare.cloudflare_api.requests.request")
    def test_request_with_params(self, mock_request, client):
        """Should include query parameters."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{"success": true, "result": []}'
        mock_response.json.return_value = {"success": True, "result": []}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        client.request("GET", "/zones", params={"status": "active"})

        call_kwargs = mock_request.call_args.kwargs
        assert call_kwargs["params"] == {"status": "active"}

    @patch("dockflare.cloudflare_api.requests.request")
    def test_handles_204_no_content(self, mock_request, client):
        """Should handle 204 No Content responses gracefully."""
        mock_response = Mock()
        mock_response.status_code = 204
        mock_response.content = b""
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        result = client.request("DELETE", "/zones/123")

        assert result["success"] is True
        assert result["result"] is None

    @patch("dockflare.cloudflare_api.requests.request")
    def test_raises_on_api_failure(self, mock_request, client):
        """Should raise CloudflareAPIError when success=false."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{"success": false, "errors": [{"code": 1001, "message": "Invalid zone"}]}'
        mock_response.json.return_value = {
            "success": False,
            "errors": [{"code": 1001, "message": "Invalid zone"}],
        }
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        with pytest.raises(CloudflareAPIError) as exc_info:
            client.request("GET", "/zones")

        assert "Invalid zone" in str(exc_info.value)
        assert exc_info.value.error_code == 1001

    @patch("dockflare.cloudflare_api.requests.request")
    def test_handles_http_error(self, mock_request, client):
        """Should handle HTTP errors and extract error details."""
        import requests as real_requests

        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.json.return_value = {
            "success": False,
            "errors": [{"code": 9103, "message": "Forbidden"}],
        }

        http_error = real_requests.exceptions.HTTPError(response=mock_response)
        mock_response.raise_for_status.side_effect = http_error
        mock_request.return_value = mock_response

        with pytest.raises(CloudflareAPIError) as exc_info:
            client.request("GET", "/zones")

        assert exc_info.value.error_code == 9103

    @patch("dockflare.cloudflare_api.requests.request")
    def test_logs_request_info(self, mock_request, client, caplog):
        """Should log request method, URL, and response status."""
        import logging

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{"success": true, "result": []}'
        mock_response.json.return_value = {"success": True, "result": []}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        with caplog.at_level(logging.INFO):
            client.request("GET", "/zones")

        assert "GET" in caplog.text
        assert "/zones" in caplog.text
        assert "200" in caplog.text


class TestCloudflareClientZoneLookup:
    """Tests for zone lookup with caching."""

    @pytest.fixture
    def client(self):
        """Create a client for testing."""
        client = CloudflareClient(
            api_token="test-token",
            account_id="test-account",
        )
        client._cache_ttl = 3600
        return client

    @patch.object(CloudflareClient, "request")
    def test_get_zone_id_returns_zone_id(self, mock_request, client):
        """Should return zone ID for valid zone name."""
        mock_request.return_value = {
            "success": True,
            "result": [{"id": "zone-123", "name": "example.com"}],
        }

        result = client.get_zone_id("example.com")

        assert result == "zone-123"
        mock_request.assert_called_once()

    @patch.object(CloudflareClient, "request")
    def test_get_zone_id_caches_result(self, mock_request, client):
        """Should cache zone ID and not call API on repeat."""
        mock_request.return_value = {
            "success": True,
            "result": [{"id": "zone-123", "name": "example.com"}],
        }

        result1 = client.get_zone_id("example.com")
        result2 = client.get_zone_id("example.com")

        assert result1 == result2 == "zone-123"
        assert mock_request.call_count == 1

    @patch.object(CloudflareClient, "request")
    def test_get_zone_id_returns_none_for_nonexistent(self, mock_request, client):
        """Should return None for non-existent zones."""
        mock_request.return_value = {"success": True, "result": []}

        result = client.get_zone_id("nonexistent.com")

        assert result is None

    @patch.object(CloudflareClient, "request")
    def test_get_zone_id_cache_expires(self, mock_request, client):
        """Zone cache should expire after TTL."""
        mock_request.return_value = {
            "success": True,
            "result": [{"id": "zone-123", "name": "example.com"}],
        }
        client._cache_ttl = 0.1

        client.get_zone_id("example.com")
        time.sleep(0.15)
        client.get_zone_id("example.com")

        assert mock_request.call_count == 2

    def test_get_zone_id_returns_none_for_empty_name(self, client):
        """Should return None for empty zone name."""
        result = client.get_zone_id("")
        assert result is None

        result = client.get_zone_id(None)
        assert result is None


class TestCloudflareClientListZones:
    """Tests for listing zones."""

    @pytest.fixture
    def client(self):
        """Create a client for testing."""
        return CloudflareClient(
            api_token="test-token",
            account_id="test-account",
        )

    @patch.object(CloudflareClient, "request")
    def test_list_zones_returns_all_zones(self, mock_request, client):
        """Should return list of active zones."""
        mock_request.return_value = {
            "success": True,
            "result": [
                {"id": "zone-1", "name": "example.com"},
                {"id": "zone-2", "name": "test.com"},
            ],
            "result_info": {"total_pages": 1},
        }

        result = client.list_zones()

        assert len(result) == 2
        assert result[0]["id"] == "zone-1"
        assert result[1]["name"] == "test.com"

    @patch.object(CloudflareClient, "request")
    def test_list_zones_handles_pagination(self, mock_request, client):
        """Should handle multi-page responses."""
        mock_request.side_effect = [
            {
                "success": True,
                "result": [{"id": "zone-1", "name": "example.com"}],
                "result_info": {"total_pages": 2},
            },
            {
                "success": True,
                "result": [{"id": "zone-2", "name": "test.com"}],
                "result_info": {"total_pages": 2},
            },
        ]

        result = client.list_zones()

        assert len(result) == 2
        assert mock_request.call_count == 2


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    @patch("dockflare.cloudflare_api._default_client", None)
    @patch("dockflare.cloudflare_api.CloudflareClient")
    def test_get_client_creates_singleton(self, mock_client_class):
        """get_client should create and reuse a singleton client."""
        mock_instance = Mock()
        mock_client_class.return_value = mock_instance

        from dockflare import cloudflare_api

        cloudflare_api._default_client = None

        client1 = cloudflare_api.get_client()
        cloudflare_api._default_client = client1
        client2 = cloudflare_api.get_client()

        assert client1 is client2

    @patch("dockflare.cloudflare_api.get_client")
    def test_cf_request_uses_default_client(self, mock_get_client):
        """cf_request should use the default client."""
        mock_client = Mock()
        mock_client.request.return_value = {"success": True, "result": []}
        mock_get_client.return_value = mock_client

        result = cf_request("GET", "/zones")

        mock_client.request.assert_called_once_with("GET", "/zones", None, None, True)
        assert result["success"] is True

    @patch("dockflare.cloudflare_api.get_client")
    def test_get_zone_id_uses_default_client(self, mock_get_client):
        """get_zone_id should use the default client."""
        mock_client = Mock()
        mock_client.get_zone_id.return_value = "zone-123"
        mock_get_client.return_value = mock_client

        result = get_zone_id("example.com")

        mock_client.get_zone_id.assert_called_once_with("example.com")
        assert result == "zone-123"

    @patch("dockflare.cloudflare_api.get_client")
    def test_list_zones_uses_default_client(self, mock_get_client):
        """list_zones should use the default client."""
        mock_client = Mock()
        mock_client.list_zones.return_value = [{"id": "zone-1"}]
        mock_get_client.return_value = mock_client

        result = list_zones()

        mock_client.list_zones.assert_called_once()
        assert len(result) == 1


class TestCloudflareAPIError:
    """Tests for CloudflareAPIError exception."""

    def test_error_with_message_only(self):
        """Should create error with just message."""
        error = CloudflareAPIError("Test error")
        assert str(error) == "Test error"
        assert error.error_code is None
        assert error.response is None

    def test_error_with_code_and_response(self):
        """Should store error code and response."""
        mock_response = Mock()
        error = CloudflareAPIError("Test error", error_code=1001, response=mock_response)
        assert error.error_code == 1001
        assert error.response is mock_response
