"""Tests for Flask application factory."""

import pytest
from unittest.mock import Mock, patch

from dockflare.app import (
    User,
    create_app,
    get_app,
    verify_password,
    hash_password,
    csrf,
    limiter,
    login_manager,
)


class TestUser:
    """Tests for User class."""

    def test_creates_user_with_id(self):
        """Should create user with ID."""
        user = User("testuser")
        assert user.id == "testuser"
        assert user.get_id() == "testuser"

    def test_default_auth_method_is_password(self):
        """Should default to password auth method."""
        user = User("testuser")
        assert user.auth_method == "password"

    def test_supports_oauth_auth_method(self):
        """Should support OAuth auth method."""
        user = User("testuser", auth_method="oauth")
        assert user.auth_method == "oauth"

    def test_supports_api_auth_method(self):
        """Should support API auth method."""
        user = User("apiuser", auth_method="api")
        assert user.auth_method == "api"

    def test_is_authenticated(self):
        """User should be authenticated."""
        user = User("testuser")
        assert user.is_authenticated is True

    def test_is_active(self):
        """User should be active."""
        user = User("testuser")
        assert user.is_active is True

    def test_is_not_anonymous(self):
        """User should not be anonymous."""
        user = User("testuser")
        assert user.is_anonymous is False

    def test_display_name_defaults_to_id(self):
        """Display name should default to user ID."""
        user = User("testuser")
        assert user.display_name == "testuser"

    def test_custom_display_name(self):
        """Should support custom display name."""
        user = User("testuser", display_name="Test User")
        assert user.display_name == "Test User"


class TestCreateApp:
    """Tests for create_app function."""

    def test_creates_flask_app(self):
        """Should create a Flask application."""
        app = create_app()
        assert app is not None
        assert app.name == "dockflare.app"

    def test_has_secret_key(self):
        """Application should have a secret key."""
        app = create_app()
        assert app.secret_key is not None
        assert len(app.secret_key) > 0

    def test_configures_session_settings(self):
        """Should configure secure session settings."""
        app = create_app()
        assert app.config["SESSION_COOKIE_HTTPONLY"] is True
        assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"

    def test_accepts_config_override(self):
        """Should accept configuration overrides."""
        app = create_app({"CUSTOM_SETTING": "custom_value"})
        assert app.config["CUSTOM_SETTING"] == "custom_value"

    def test_has_version(self):
        """Should include app version."""
        app = create_app()
        assert "APP_VERSION" in app.config

    def test_has_reconciliation_info(self):
        """Should initialize reconciliation info."""
        app = create_app()
        assert app.reconciliation_info is not None
        assert app.reconciliation_info["in_progress"] is False

    def test_csrf_protection_enabled(self):
        """Should enable CSRF protection."""
        app = create_app()
        assert app.extensions.get("csrf") is not None

    def test_rate_limiting_enabled(self):
        """Should enable rate limiting."""
        app = create_app()
        assert app.extensions.get("limiter") is not None


class TestCreateAppAuth:
    """Tests for authentication configuration."""

    def test_configures_username(self):
        """Should configure username from env."""
        with patch.dict("os.environ", {"DOCKFLARE_USERNAME": "admin"}):
            app = create_app()
            assert app.config["DOCKFLARE_USERNAME"] == "admin"

    def test_configures_password_disabled(self):
        """Should configure password disabled flag."""
        with patch.dict("os.environ", {"DISABLE_PASSWORD_LOGIN": "true"}):
            app = create_app()
            assert app.config["DISABLE_PASSWORD_LOGIN"] is True

    def test_configures_oauth_providers(self):
        """Should configure OAuth providers when credentials present."""
        with patch.dict(
            "os.environ",
            {
                "OAUTH_CLIENT_ID": "client123",
                "OAUTH_CLIENT_SECRET": "secret123",
            },
        ):
            app = create_app()
            assert "cloudflare" in app.config["OAUTH_PROVIDERS"]

    def test_configures_authorized_oauth_users(self):
        """Should configure authorized OAuth users."""
        with patch.dict(
            "os.environ",
            {
                "OAUTH_CLIENT_ID": "client123",
                "OAUTH_CLIENT_SECRET": "secret123",
                "OAUTH_AUTHORIZED_USERS": "user1@example.com, user2@example.com",
            },
        ):
            app = create_app()
            assert "user1@example.com" in app.config["OAUTH_AUTHORIZED_USERS"]
            assert "user2@example.com" in app.config["OAUTH_AUTHORIZED_USERS"]


class TestCreateAppErrorHandlers:
    """Tests for error handlers."""

    @pytest.fixture
    def app(self):
        """Create test app."""
        return create_app({"TESTING": True})

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return app.test_client()

    def test_404_for_api_returns_json(self, client):
        """404 on API routes should return JSON."""
        response = client.get("/api/v1/nonexistent")
        assert response.status_code == 404
        assert response.is_json
        data = response.get_json()
        assert data["status"] == "error"

    def test_health_endpoint(self, client):
        """Health endpoint should return OK."""
        response = client.get("/health")
        assert response.status_code == 200


class TestPasswordFunctions:
    """Tests for password hashing functions."""

    def test_hash_password(self):
        """Should hash password."""
        hashed = hash_password("mypassword")
        assert hashed is not None
        assert len(hashed) == 64
        assert hashed != "mypassword"

    def test_verify_password_correct(self):
        """Should verify correct password."""
        hashed = hash_password("mypassword")
        assert verify_password(hashed, "mypassword") is True

    def test_verify_password_incorrect(self):
        """Should reject incorrect password."""
        hashed = hash_password("mypassword")
        assert verify_password(hashed, "wrongpassword") is False

    def test_hash_is_deterministic(self):
        """Same password should produce same hash."""
        hash1 = hash_password("mypassword")
        hash2 = hash_password("mypassword")
        assert hash1 == hash2


class TestGetApp:
    """Tests for get_app function."""

    @patch("dockflare.app._app", None)
    def test_creates_singleton(self):
        """Should create singleton application."""
        import dockflare.app as app_module

        app_module._app = None

        app1 = get_app()
        app2 = get_app()

        assert app1 is app2


class TestLoginFlow:
    """Tests for login flow."""

    @pytest.fixture
    def app(self):
        """Create test app with password."""
        password_hash = hash_password("testpass")
        return create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DOCKFLARE_USERNAME": "admin",
            "DOCKFLARE_PASSWORD_HASH": password_hash,
        })

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return app.test_client()

    def test_login_page_loads(self, client):
        """Login page should load."""
        response = client.get("/login")
        assert response.status_code == 200
        assert b"Login" in response.data

    def test_login_with_correct_credentials(self, client):
        """Should login with correct credentials."""
        response = client.post("/login", data={
            "username": "admin",
            "password": "testpass",
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b"Dashboard" in response.data

    def test_login_with_wrong_password(self, client):
        """Should reject wrong password."""
        response = client.post("/login", data={
            "username": "admin",
            "password": "wrongpass",
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b"Invalid" in response.data

    def test_logout_redirects_to_login(self, client):
        """Logout should redirect to login."""
        client.post("/login", data={
            "username": "admin",
            "password": "testpass",
        })
        response = client.get("/logout", follow_redirects=True)
        assert response.status_code == 200


class TestAPIRoutes:
    """Tests for API routes."""

    @pytest.fixture
    def app(self):
        """Create test app."""
        password_hash = hash_password("testpass")
        return create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DOCKFLARE_USERNAME": "admin",
            "DOCKFLARE_PASSWORD_HASH": password_hash,
        })

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return app.test_client()

    @pytest.fixture
    def authenticated_client(self, client):
        """Create authenticated test client."""
        client.post("/login", data={
            "username": "admin",
            "password": "testpass",
        })
        return client

    def test_api_status_returns_json(self, client):
        """API status should return JSON."""
        response = client.get("/api/v1/status")
        assert response.is_json
        data = response.get_json()
        assert data["status"] == "ok"

    def test_api_health_returns_healthy(self, client):
        """API health should return healthy."""
        response = client.get("/api/v1/health")
        assert response.is_json
        data = response.get_json()
        assert data["status"] == "healthy"

    def test_rules_requires_auth(self, client):
        """Rules endpoint should require authentication."""
        response = client.get("/api/v1/rules")
        assert response.status_code == 401

    def test_reconciliation_status_requires_auth(self, client):
        """Reconciliation status should require authentication."""
        response = client.get("/api/v1/reconciliation/status")
        assert response.status_code == 401


class TestDisabledPasswordLogin:
    """Tests for disabled password login mode."""

    @pytest.fixture
    def app(self):
        """Create test app with disabled password."""
        return create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DISABLE_PASSWORD_LOGIN": True,
        })

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return app.test_client()

    def test_auto_login_when_disabled(self, client):
        """Should auto-login when password disabled."""
        response = client.get("/login", follow_redirects=True)
        assert response.status_code == 200
        assert b"Dashboard" in response.data
