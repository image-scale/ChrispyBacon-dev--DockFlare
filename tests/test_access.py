"""Tests for Cloudflare Access management."""

import pytest
from unittest.mock import Mock, patch

from dockflare.access import (
    AccessManager,
    build_bypass_policy,
    build_allow_policy,
    find_access_application,
    create_access_application,
    delete_access_application,
    get_manager,
)
from dockflare.cloudflare_api import CloudflareAPIError


class TestAccessManager:
    """Tests for AccessManager class."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock CloudflareClient."""
        return Mock()

    @pytest.fixture
    def manager(self, mock_client):
        """Create an AccessManager with mock client."""
        return AccessManager(client=mock_client, account_id="test-account")


class TestAccessManagerFindApplication:
    """Tests for finding Access applications."""

    @pytest.fixture
    def mock_client(self):
        return Mock()

    @pytest.fixture
    def manager(self, mock_client):
        return AccessManager(client=mock_client, account_id="test-account")

    def test_finds_application_by_domain(self, manager, mock_client):
        """Should find application matching domain."""
        mock_client.request.return_value = {
            "success": True,
            "result": [
                {"id": "app-123", "domain": "app.example.com", "name": "My App"}
            ],
        }

        result = manager.find_application("app.example.com")

        assert result is not None
        assert result["id"] == "app-123"

    def test_finds_application_in_self_hosted_domains(self, manager, mock_client):
        """Should find application with domain in self_hosted_domains."""
        mock_client.request.side_effect = [
            {"success": True, "result": []},
            {
                "success": True,
                "result": [
                    {
                        "id": "app-123",
                        "domain": "main.example.com",
                        "self_hosted_domains": ["app.example.com", "main.example.com"],
                    }
                ],
            },
        ]

        result = manager.find_application("app.example.com")

        assert result is not None
        assert result["id"] == "app-123"

    def test_returns_none_when_not_found(self, manager, mock_client):
        """Should return None when application not found."""
        mock_client.request.side_effect = [
            {"success": True, "result": []},
            {"success": True, "result": []},
        ]

        result = manager.find_application("nonexistent.com")

        assert result is None

    def test_returns_none_on_error(self, manager, mock_client):
        """Should return None on API error."""
        mock_client.request.side_effect = CloudflareAPIError("API error")

        result = manager.find_application("app.example.com")

        assert result is None


class TestAccessManagerCreateApplication:
    """Tests for creating Access applications."""

    @pytest.fixture
    def mock_client(self):
        return Mock()

    @pytest.fixture
    def manager(self, mock_client):
        return AccessManager(client=mock_client, account_id="test-account")

    def test_creates_application(self, manager, mock_client):
        """Should create Access application with correct payload."""
        mock_client.request.return_value = {
            "success": True,
            "result": {"id": "app-123", "name": "My App"},
        }

        result = manager.create_application(
            domain="app.example.com",
            name="My App",
            session_duration="24h",
        )

        assert result is not None
        assert result["id"] == "app-123"

        call_kwargs = mock_client.request.call_args.kwargs
        payload = call_kwargs["json_data"]
        assert payload["name"] == "My App"
        assert payload["domain"] == "app.example.com"
        assert payload["type"] == "self_hosted"
        assert payload["session_duration"] == "24h"

    def test_creates_application_with_policies(self, manager, mock_client):
        """Should include policies in payload."""
        mock_client.request.return_value = {
            "success": True,
            "result": {"id": "app-123"},
        }

        policies = [{"decision": "bypass", "include": [{"everyone": {}}]}]
        manager.create_application(
            domain="app.example.com",
            name="My App",
            policies=policies,
        )

        call_kwargs = mock_client.request.call_args.kwargs
        payload = call_kwargs["json_data"]
        assert payload["policies"] == policies

    def test_returns_none_on_error(self, manager, mock_client):
        """Should return None on API error."""
        mock_client.request.side_effect = CloudflareAPIError("API error")

        result = manager.create_application(
            domain="app.example.com",
            name="My App",
        )

        assert result is None


class TestAccessManagerUpdateApplication:
    """Tests for updating Access applications."""

    @pytest.fixture
    def mock_client(self):
        return Mock()

    @pytest.fixture
    def manager(self, mock_client):
        return AccessManager(client=mock_client, account_id="test-account")

    def test_updates_application(self, manager, mock_client):
        """Should update Access application."""
        mock_client.request.return_value = {
            "success": True,
            "result": {"id": "app-123", "name": "Updated App"},
        }

        result = manager.update_application(
            app_id="app-123",
            domain="app.example.com",
            name="Updated App",
        )

        assert result is not None
        assert result["name"] == "Updated App"

    def test_returns_none_on_error(self, manager, mock_client):
        """Should return None on API error."""
        mock_client.request.side_effect = CloudflareAPIError("API error")

        result = manager.update_application(
            app_id="app-123",
            domain="app.example.com",
            name="Updated App",
        )

        assert result is None


class TestAccessManagerDeleteApplication:
    """Tests for deleting Access applications."""

    @pytest.fixture
    def mock_client(self):
        return Mock()

    @pytest.fixture
    def manager(self, mock_client):
        return AccessManager(client=mock_client, account_id="test-account")

    def test_deletes_application(self, manager, mock_client):
        """Should delete Access application."""
        mock_client.request.return_value = {"success": True, "result": {}}

        result = manager.delete_application("app-123")

        assert result is True
        mock_client.request.assert_called_once()

    def test_returns_false_on_error(self, manager, mock_client):
        """Should return False on API error."""
        mock_client.request.side_effect = CloudflareAPIError("API error")

        result = manager.delete_application("app-123")

        assert result is False


class TestAccessManagerListApplications:
    """Tests for listing Access applications."""

    @pytest.fixture
    def mock_client(self):
        return Mock()

    @pytest.fixture
    def manager(self, mock_client):
        return AccessManager(client=mock_client, account_id="test-account")

    def test_lists_all_applications(self, manager, mock_client):
        """Should list all Access applications."""
        mock_client.request.return_value = {
            "success": True,
            "result": [
                {"id": "app-1", "name": "App 1"},
                {"id": "app-2", "name": "App 2"},
            ],
            "result_info": {"total_pages": 1},
        }

        result = manager.list_applications()

        assert len(result) == 2
        assert result[0]["id"] == "app-1"


class TestAccessManagerPolicies:
    """Tests for Access policy operations."""

    @pytest.fixture
    def mock_client(self):
        return Mock()

    @pytest.fixture
    def manager(self, mock_client):
        return AccessManager(client=mock_client, account_id="test-account")

    def test_creates_policy(self, manager, mock_client):
        """Should create Access policy."""
        mock_client.request.return_value = {
            "success": True,
            "result": {"id": "policy-123", "name": "My Policy"},
        }

        result = manager.create_policy(
            name="My Policy",
            decision="allow",
            include=[{"email": {"email": "user@example.com"}}],
        )

        assert result is not None
        assert result["id"] == "policy-123"

    def test_finds_policy_by_name(self, manager, mock_client):
        """Should find policy by name."""
        mock_client.request.return_value = {
            "success": True,
            "result": [
                {"id": "policy-1", "name": "Other Policy"},
                {"id": "policy-2", "name": "My Policy"},
            ],
        }

        result = manager.find_policy("My Policy")

        assert result is not None
        assert result["id"] == "policy-2"

    def test_deletes_policy(self, manager, mock_client):
        """Should delete Access policy."""
        mock_client.request.return_value = {"success": True, "result": {}}

        result = manager.delete_policy("policy-123")

        assert result is True


class TestPolicyBuilders:
    """Tests for policy builder functions."""

    def test_build_bypass_policy(self):
        """Should build bypass policy with everyone rule."""
        policy = build_bypass_policy()

        assert policy["decision"] == "bypass"
        assert {"everyone": {}} in policy["include"]

    def test_build_allow_policy_with_emails(self):
        """Should build allow policy with email rules."""
        policy = build_allow_policy(emails=["user@example.com", "admin@example.com"])

        assert policy["decision"] == "allow"
        assert {"email": {"email": "user@example.com"}} in policy["include"]
        assert {"email": {"email": "admin@example.com"}} in policy["include"]

    def test_build_allow_policy_with_domains(self):
        """Should build allow policy with domain rules."""
        policy = build_allow_policy(email_domains=["example.com"])

        assert policy["decision"] == "allow"
        assert {"email_domain": {"domain": "example.com"}} in policy["include"]

    def test_build_allow_policy_empty(self):
        """Should build allow policy with everyone rule when no args."""
        policy = build_allow_policy()

        assert policy["decision"] == "allow"
        assert {"everyone": {}} in policy["include"]


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    @patch("dockflare.access.get_manager")
    def test_find_access_application_uses_manager(self, mock_get_manager):
        """find_access_application should use the default manager."""
        mock_manager = Mock()
        mock_manager.find_application.return_value = {"id": "app-123"}
        mock_get_manager.return_value = mock_manager

        result = find_access_application("app.example.com")

        mock_manager.find_application.assert_called_once_with("app.example.com")
        assert result["id"] == "app-123"

    @patch("dockflare.access.get_manager")
    def test_create_access_application_uses_manager(self, mock_get_manager):
        """create_access_application should use the default manager."""
        mock_manager = Mock()
        mock_manager.create_application.return_value = {"id": "app-123"}
        mock_get_manager.return_value = mock_manager

        result = create_access_application(
            domain="app.example.com",
            name="My App",
        )

        mock_manager.create_application.assert_called_once()
        assert result["id"] == "app-123"

    @patch("dockflare.access.get_manager")
    def test_delete_access_application_uses_manager(self, mock_get_manager):
        """delete_access_application should use the default manager."""
        mock_manager = Mock()
        mock_manager.delete_application.return_value = True
        mock_get_manager.return_value = mock_manager

        result = delete_access_application("app-123")

        mock_manager.delete_application.assert_called_once_with("app-123")
        assert result is True
