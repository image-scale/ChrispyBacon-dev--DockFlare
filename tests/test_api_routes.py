"""Tests for API routes."""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock

from dockflare.app import create_app, hash_password


class TestAPIStatus:
    """Tests for API status endpoints."""

    @pytest.fixture
    def app(self):
        """Create test app."""
        return create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return app.test_client()

    def test_status_returns_ok(self, client):
        """Status endpoint should return OK."""
        response = client.get("/api/v1/status")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"

    def test_status_includes_version(self, client):
        """Status should include version."""
        response = client.get("/api/v1/status")
        data = response.get_json()
        assert "version" in data

    def test_status_includes_timestamp(self, client):
        """Status should include timestamp."""
        response = client.get("/api/v1/status")
        data = response.get_json()
        assert "timestamp" in data


class TestAPIHealth:
    """Tests for health check endpoint."""

    @pytest.fixture
    def app(self):
        return create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})

    @pytest.fixture
    def client(self, app):
        return app.test_client()

    def test_health_returns_healthy(self, client):
        """Health endpoint should return healthy."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] in ["healthy", "degraded"]

    def test_health_includes_checks(self, client):
        """Health should include component checks."""
        response = client.get("/api/v1/health")
        data = response.get_json()
        assert "checks" in data


class TestAPIRules:
    """Tests for rule management endpoints."""

    @pytest.fixture
    def app(self):
        password_hash = hash_password("testpass")
        return create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DOCKFLARE_USERNAME": "admin",
            "DOCKFLARE_PASSWORD_HASH": password_hash,
        })

    @pytest.fixture
    def client(self, app):
        return app.test_client()

    @pytest.fixture
    def authenticated_client(self, client):
        client.post("/login", data={"username": "admin", "password": "testpass"})
        return client

    def test_list_rules_requires_auth(self, client):
        """List rules should require authentication."""
        response = client.get("/api/v1/rules")
        assert response.status_code == 401

    @patch("dockflare.state.get_state")
    def test_list_rules_returns_rules(self, mock_get_state, authenticated_client):
        """Should list rules when authenticated."""
        mock_state = Mock()
        mock_state.list_rules.return_value = {
            "app.example.com|": {
                "hostname": "app.example.com",
                "service": "http://app:80",
                "status": "active",
                "source": "docker",
            }
        }
        mock_get_state.return_value = mock_state

        response = authenticated_client.get("/api/v1/rules")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"
        assert len(data["rules"]) == 1

    @patch("dockflare.state.get_state")
    def test_list_rules_filters_by_status(self, mock_get_state, authenticated_client):
        """Should filter rules by status."""
        mock_state = Mock()
        mock_state.list_rules.return_value = {
            "active.example.com|": {"hostname": "active.example.com", "status": "active", "source": "docker"},
            "pending.example.com|": {"hostname": "pending.example.com", "status": "pending_deletion", "source": "docker"},
        }
        mock_get_state.return_value = mock_state

        response = authenticated_client.get("/api/v1/rules?status=active")
        data = response.get_json()
        assert len(data["rules"]) == 1
        assert data["rules"][0]["hostname"] == "active.example.com"

    @patch("dockflare.state.get_state")
    def test_get_rule_not_found(self, mock_get_state, authenticated_client):
        """Should return 404 for missing rule."""
        mock_state = Mock()
        mock_state.get_rule.return_value = None
        mock_get_state.return_value = mock_state

        response = authenticated_client.get("/api/v1/rules/nonexistent|")
        assert response.status_code == 404

    @patch("dockflare.state.get_state")
    @patch("dockflare.labels.get_rule_key")
    def test_create_rule(self, mock_get_key, mock_get_state, authenticated_client):
        """Should create a new rule."""
        mock_get_key.return_value = "new.example.com|"
        mock_state = Mock()
        mock_state.get_rule.return_value = None
        mock_get_state.return_value = mock_state

        response = authenticated_client.post(
            "/api/v1/rules",
            json={"hostname": "new.example.com", "service": "http://new:80"},
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["status"] == "ok"

    @patch("dockflare.state.get_state")
    def test_create_rule_missing_fields(self, mock_get_state, authenticated_client):
        """Should reject rule with missing fields."""
        response = authenticated_client.post(
            "/api/v1/rules",
            json={"hostname": "new.example.com"},
        )
        assert response.status_code == 400

    @patch("dockflare.state.get_state")
    def test_delete_rule(self, mock_get_state, authenticated_client):
        """Should delete an existing rule."""
        mock_state = Mock()
        mock_state.delete_rule.return_value = True
        mock_get_state.return_value = mock_state

        response = authenticated_client.delete("/api/v1/rules/app.example.com|")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"


class TestAPITunnel:
    """Tests for tunnel status endpoints."""

    @pytest.fixture
    def app(self):
        password_hash = hash_password("testpass")
        return create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DOCKFLARE_USERNAME": "admin",
            "DOCKFLARE_PASSWORD_HASH": password_hash,
        })

    @pytest.fixture
    def authenticated_client(self, app):
        client = app.test_client()
        client.post("/login", data={"username": "admin", "password": "testpass"})
        return client

    def test_tunnel_status_requires_auth(self, app):
        """Tunnel status should require auth."""
        client = app.test_client()
        response = client.get("/api/v1/tunnel/status")
        assert response.status_code == 401

    def test_tunnel_status_returns_info(self, authenticated_client):
        """Should return tunnel status."""
        response = authenticated_client.get("/api/v1/tunnel/status")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"


class TestAPIAgents:
    """Tests for agent management endpoints."""

    @pytest.fixture
    def app(self):
        password_hash = hash_password("testpass")
        return create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DOCKFLARE_USERNAME": "admin",
            "DOCKFLARE_PASSWORD_HASH": password_hash,
        })

    @pytest.fixture
    def client(self, app):
        return app.test_client()

    @pytest.fixture
    def authenticated_client(self, app):
        client = app.test_client()
        client.post("/login", data={"username": "admin", "password": "testpass"})
        return client

    @patch("dockflare.state.get_state")
    def test_list_agents(self, mock_get_state, authenticated_client):
        """Should list agents."""
        mock_state = Mock()
        mock_state.list_agents.return_value = {
            "agent-1": {"id": "agent-1", "name": "Server 1", "status": "active"},
        }
        mock_get_state.return_value = mock_state

        response = authenticated_client.get("/api/v1/agents")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"
        assert len(data["agents"]) == 1

    @patch("dockflare.state.get_state")
    def test_enroll_agent(self, mock_get_state, client):
        """Should enroll a new agent."""
        mock_state = Mock()
        mock_get_state.return_value = mock_state

        response = client.post(
            "/api/v1/agents/enroll",
            json={"name": "New Server"},
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["status"] == "ok"
        assert "agent_id" in data
        assert "api_key" in data

    @patch("dockflare.state.get_state")
    def test_enroll_agent_with_key(self, mock_get_state, app, client):
        """Should require enrollment key if configured."""
        app.config["AGENT_ENROLLMENT_KEY"] = "secret-key"
        mock_state = Mock()
        mock_get_state.return_value = mock_state

        response = client.post(
            "/api/v1/agents/enroll",
            json={"name": "New Server"},
        )
        assert response.status_code == 401

        response = client.post(
            "/api/v1/agents/enroll",
            json={"name": "New Server"},
            headers={"X-Enrollment-Key": "secret-key"},
        )
        assert response.status_code == 201

    @patch("dockflare.state.get_state")
    def test_agent_heartbeat(self, mock_get_state, client):
        """Should handle agent heartbeat."""
        import hashlib
        api_key = "test-api-key"
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        mock_state = Mock()
        mock_state.get_agent.return_value = {
            "id": "agent-1",
            "api_key_hash": api_key_hash,
            "status": "pending",
        }
        mock_get_state.return_value = mock_state

        response = client.post(
            "/api/v1/agents/agent-1/heartbeat",
            json={"container_count": 5},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"

    @patch("dockflare.state.get_state")
    def test_agent_heartbeat_invalid_key(self, mock_get_state, client):
        """Should reject heartbeat with invalid API key."""
        mock_state = Mock()
        mock_state.get_agent.return_value = {
            "id": "agent-1",
            "api_key_hash": "different-hash",
        }
        mock_get_state.return_value = mock_state

        response = client.post(
            "/api/v1/agents/agent-1/heartbeat",
            json={},
            headers={"X-API-Key": "wrong-key"},
        )
        assert response.status_code == 401

    @patch("dockflare.state.get_state")
    def test_delete_agent(self, mock_get_state, authenticated_client):
        """Should delete an agent."""
        mock_state = Mock()
        mock_state.delete_agent.return_value = True
        mock_get_state.return_value = mock_state

        response = authenticated_client.delete("/api/v1/agents/agent-1")
        assert response.status_code == 200


class TestAPIReconciliation:
    """Tests for reconciliation endpoints."""

    @pytest.fixture
    def app(self):
        password_hash = hash_password("testpass")
        return create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DOCKFLARE_USERNAME": "admin",
            "DOCKFLARE_PASSWORD_HASH": password_hash,
        })

    @pytest.fixture
    def authenticated_client(self, app):
        client = app.test_client()
        client.post("/login", data={"username": "admin", "password": "testpass"})
        return client

    def test_reconciliation_status(self, authenticated_client):
        """Should return reconciliation status."""
        response = authenticated_client.get("/api/v1/reconciliation/status")
        assert response.status_code == 200
        data = response.get_json()
        assert "in_progress" in data
        assert "progress" in data


class TestAPICache:
    """Tests for cache endpoints."""

    @pytest.fixture
    def app(self):
        password_hash = hash_password("testpass")
        return create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DOCKFLARE_USERNAME": "admin",
            "DOCKFLARE_PASSWORD_HASH": password_hash,
        })

    @pytest.fixture
    def authenticated_client(self, app):
        client = app.test_client()
        client.post("/login", data={"username": "admin", "password": "testpass"})
        return client

    @patch("dockflare.cache.get_cache")
    def test_clear_cache(self, mock_get_cache, authenticated_client):
        """Should clear cache."""
        mock_cache = Mock()
        mock_cache.clear_all.return_value = True
        mock_get_cache.return_value = mock_cache

        response = authenticated_client.post("/api/v1/cache/clear")
        assert response.status_code == 200

    @patch("dockflare.cache.get_cache")
    def test_cache_stats(self, mock_get_cache, authenticated_client):
        """Should return cache stats."""
        mock_cache = Mock()
        mock_cache.using_redis = False
        mock_get_cache.return_value = mock_cache

        response = authenticated_client.get("/api/v1/cache/stats")
        assert response.status_code == 200
        data = response.get_json()
        assert data["backend"] == "memory"


class TestAPIAccessGroups:
    """Tests for access group endpoints."""

    @pytest.fixture
    def app(self):
        password_hash = hash_password("testpass")
        return create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DOCKFLARE_USERNAME": "admin",
            "DOCKFLARE_PASSWORD_HASH": password_hash,
        })

    @pytest.fixture
    def authenticated_client(self, app):
        client = app.test_client()
        client.post("/login", data={"username": "admin", "password": "testpass"})
        return client

    @patch("dockflare.state.get_state")
    def test_list_access_groups(self, mock_get_state, authenticated_client):
        """Should list access groups."""
        mock_state = Mock()
        mock_state.list_access_groups.return_value = {
            "admin": {"display_name": "Admins", "session_duration": "24h"},
        }
        mock_get_state.return_value = mock_state

        response = authenticated_client.get("/api/v1/access-groups")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["groups"]) == 1


class TestAPISystemInfo:
    """Tests for system info endpoint."""

    @pytest.fixture
    def app(self):
        password_hash = hash_password("testpass")
        return create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DOCKFLARE_USERNAME": "admin",
            "DOCKFLARE_PASSWORD_HASH": password_hash,
        })

    @pytest.fixture
    def authenticated_client(self, app):
        client = app.test_client()
        client.post("/login", data={"username": "admin", "password": "testpass"})
        return client

    def test_system_info(self, authenticated_client):
        """Should return system info."""
        response = authenticated_client.get("/api/v1/system/info")
        assert response.status_code == 200
        data = response.get_json()
        assert "app_version" in data
        assert "python_version" in data
        assert "platform" in data
