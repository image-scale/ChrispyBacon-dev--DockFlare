"""Tests for DNS record management."""

import pytest
from unittest.mock import Mock, patch

from dockflare.dns import (
    DNSManager,
    create_dns_record,
    find_dns_record,
    update_dns_record,
    delete_dns_record,
    get_manager,
)
from dockflare.cloudflare_api import CloudflareAPIError


class TestDNSManager:
    """Tests for DNSManager class."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock CloudflareClient."""
        return Mock()

    @pytest.fixture
    def manager(self, mock_client):
        """Create a DNSManager with mock client."""
        return DNSManager(client=mock_client)

    def test_get_tunnel_content(self, manager):
        """Should format tunnel content correctly."""
        content = manager._get_tunnel_content("tunnel-123")
        assert content == "tunnel-123.cfargotunnel.com"


class TestDNSManagerCreateRecord:
    """Tests for DNSManager.create_record method."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock CloudflareClient."""
        return Mock()

    @pytest.fixture
    def manager(self, mock_client):
        """Create a DNSManager with mock client."""
        return DNSManager(client=mock_client)

    def test_creates_new_record(self, manager, mock_client):
        """Should create CNAME record pointing to tunnel."""
        mock_client.request.side_effect = [
            {"success": True, "result": []},
            {"success": True, "result": {"id": "record-123"}},
        ]

        record_id = manager.create_record("zone-1", "app.example.com", "tunnel-123")

        assert record_id == "record-123"
        create_call = mock_client.request.call_args_list[-1]
        payload = create_call.kwargs["json_data"]
        assert payload["type"] == "CNAME"
        assert payload["name"] == "app.example.com"
        assert payload["content"] == "tunnel-123.cfargotunnel.com"
        assert payload["proxied"] is True
        assert payload["ttl"] == 1

    def test_returns_existing_record_id(self, manager, mock_client):
        """Should return existing record ID if already correct."""
        mock_client.request.return_value = {
            "success": True,
            "result": [
                {"id": "existing-123", "content": "tunnel-123.cfargotunnel.com"}
            ],
        }

        record_id = manager.create_record("zone-1", "app.example.com", "tunnel-123")

        assert record_id == "existing-123"
        assert mock_client.request.call_count == 1

    def test_updates_existing_wrong_record(self, manager, mock_client):
        """Should update existing record if pointing to wrong tunnel."""
        mock_client.request.side_effect = [
            {
                "success": True,
                "result": [
                    {"id": "existing-123", "content": "wrong-tunnel.cfargotunnel.com"}
                ],
            },
            {"success": True, "result": {"id": "existing-123"}},
        ]

        record_id = manager.create_record("zone-1", "app.example.com", "tunnel-123")

        assert record_id == "existing-123"
        assert mock_client.request.call_count == 2

    def test_returns_none_on_missing_args(self, manager):
        """Should return None for missing arguments."""
        assert manager.create_record("", "app.example.com", "tunnel-123") is None
        assert manager.create_record("zone-1", "", "tunnel-123") is None
        assert manager.create_record("zone-1", "app.example.com", "") is None

    def test_handles_already_exists_error(self, manager, mock_client):
        """Should handle 'already exists' API error."""
        mock_response = Mock()
        mock_response.text = "A record with that name already exists"
        error = CloudflareAPIError("Error", error_code=81057, response=mock_response)

        mock_client.request.side_effect = [
            {"success": True, "result": []},
            error,
            {"success": True, "result": [{"id": "existing-123", "content": "tunnel-123.cfargotunnel.com"}]},
        ]

        record_id = manager.create_record("zone-1", "app.example.com", "tunnel-123")

        assert record_id == "existing-123"


class TestDNSManagerFindRecord:
    """Tests for DNSManager.find_record method."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock CloudflareClient."""
        return Mock()

    @pytest.fixture
    def manager(self, mock_client):
        """Create a DNSManager with mock client."""
        return DNSManager(client=mock_client)

    def test_finds_exact_match(self, manager, mock_client):
        """Should find record with correct tunnel target."""
        mock_client.request.return_value = {
            "success": True,
            "result": [
                {"id": "record-123", "content": "tunnel-123.cfargotunnel.com"}
            ],
        }

        record_id, correct = manager.find_record("zone-1", "app.example.com", "tunnel-123")

        assert record_id == "record-123"
        assert correct is True

    def test_finds_wrong_target(self, manager, mock_client):
        """Should find record with wrong tunnel target."""
        mock_client.request.return_value = {
            "success": True,
            "result": [
                {"id": "record-123", "content": "other-tunnel.cfargotunnel.com"}
            ],
        }

        record_id, correct = manager.find_record("zone-1", "app.example.com", "tunnel-123")

        assert record_id == "record-123"
        assert correct is False

    def test_returns_none_when_not_found(self, manager, mock_client):
        """Should return (None, False) when no record found."""
        mock_client.request.return_value = {"success": True, "result": []}

        record_id, correct = manager.find_record("zone-1", "app.example.com", "tunnel-123")

        assert record_id is None
        assert correct is False

    def test_returns_none_on_error(self, manager, mock_client):
        """Should return (None, False) on API error."""
        mock_client.request.side_effect = CloudflareAPIError("API error")

        record_id, correct = manager.find_record("zone-1", "app.example.com", "tunnel-123")

        assert record_id is None
        assert correct is False


class TestDNSManagerUpdateRecord:
    """Tests for DNSManager.update_record method."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock CloudflareClient."""
        return Mock()

    @pytest.fixture
    def manager(self, mock_client):
        """Create a DNSManager with mock client."""
        return DNSManager(client=mock_client)

    def test_updates_record(self, manager, mock_client):
        """Should update record to point to correct tunnel."""
        mock_client.request.return_value = {
            "success": True,
            "result": {"id": "record-123"},
        }

        record_id = manager.update_record(
            "zone-1", "record-123", "app.example.com", "tunnel-123"
        )

        assert record_id == "record-123"
        call_kwargs = mock_client.request.call_args.kwargs
        assert call_kwargs["json_data"]["content"] == "tunnel-123.cfargotunnel.com"

    def test_returns_none_on_error(self, manager, mock_client):
        """Should return None on API error."""
        mock_client.request.side_effect = CloudflareAPIError("API error")

        record_id = manager.update_record(
            "zone-1", "record-123", "app.example.com", "tunnel-123"
        )

        assert record_id is None

    def test_returns_none_on_missing_args(self, manager):
        """Should return None for missing arguments."""
        assert manager.update_record("", "record-123", "app.example.com", "tunnel-123") is None
        assert manager.update_record("zone-1", "", "app.example.com", "tunnel-123") is None


class TestDNSManagerDeleteRecord:
    """Tests for DNSManager.delete_record method."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock CloudflareClient."""
        return Mock()

    @pytest.fixture
    def manager(self, mock_client):
        """Create a DNSManager with mock client."""
        return DNSManager(client=mock_client)

    def test_deletes_record(self, manager, mock_client):
        """Should delete DNS record by ID."""
        mock_client.request.return_value = {"success": True, "result": {"id": "record-123"}}

        result = manager.delete_record("zone-1", "record-123")

        assert result is True
        mock_client.request.assert_called_once()

    def test_returns_false_on_error(self, manager, mock_client):
        """Should return False on API error."""
        mock_client.request.side_effect = CloudflareAPIError("API error")

        result = manager.delete_record("zone-1", "record-123")

        assert result is False

    def test_returns_false_on_missing_args(self, manager):
        """Should return False for missing arguments."""
        assert manager.delete_record("", "record-123") is False
        assert manager.delete_record("zone-1", "") is False


class TestDNSManagerListRecords:
    """Tests for DNSManager.list_records method."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock CloudflareClient."""
        return Mock()

    @pytest.fixture
    def manager(self, mock_client):
        """Create a DNSManager with mock client."""
        return DNSManager(client=mock_client)

    def test_lists_records(self, manager, mock_client):
        """Should list DNS records in zone."""
        mock_client.request.return_value = {
            "success": True,
            "result": [
                {"id": "record-1", "name": "app.example.com"},
                {"id": "record-2", "name": "api.example.com"},
            ],
        }

        records = manager.list_records("zone-1")

        assert len(records) == 2
        assert records[0]["id"] == "record-1"

    def test_returns_empty_on_error(self, manager, mock_client):
        """Should return empty list on API error."""
        mock_client.request.side_effect = CloudflareAPIError("API error")

        records = manager.list_records("zone-1")

        assert records == []


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    @patch("dockflare.dns.get_manager")
    def test_create_dns_record_uses_manager(self, mock_get_manager):
        """create_dns_record should use the default manager."""
        mock_manager = Mock()
        mock_manager.create_record.return_value = "record-123"
        mock_get_manager.return_value = mock_manager

        result = create_dns_record("zone-1", "app.example.com", "tunnel-123")

        mock_manager.create_record.assert_called_once_with("zone-1", "app.example.com", "tunnel-123")
        assert result == "record-123"

    @patch("dockflare.dns.get_manager")
    def test_find_dns_record_uses_manager(self, mock_get_manager):
        """find_dns_record should use the default manager."""
        mock_manager = Mock()
        mock_manager.find_record.return_value = ("record-123", True)
        mock_get_manager.return_value = mock_manager

        result = find_dns_record("zone-1", "app.example.com", "tunnel-123")

        mock_manager.find_record.assert_called_once_with("zone-1", "app.example.com", "tunnel-123")
        assert result == ("record-123", True)

    @patch("dockflare.dns.get_manager")
    def test_update_dns_record_uses_manager(self, mock_get_manager):
        """update_dns_record should use the default manager."""
        mock_manager = Mock()
        mock_manager.update_record.return_value = "record-123"
        mock_get_manager.return_value = mock_manager

        result = update_dns_record("zone-1", "record-123", "app.example.com", "tunnel-123")

        mock_manager.update_record.assert_called_once()
        assert result == "record-123"

    @patch("dockflare.dns.get_manager")
    def test_delete_dns_record_uses_manager(self, mock_get_manager):
        """delete_dns_record should use the default manager."""
        mock_manager = Mock()
        mock_manager.delete_record.return_value = True
        mock_get_manager.return_value = mock_manager

        result = delete_dns_record("zone-1", "record-123")

        mock_manager.delete_record.assert_called_once_with("zone-1", "record-123")
        assert result is True
