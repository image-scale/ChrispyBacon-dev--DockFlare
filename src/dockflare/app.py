"""
Flask application factory.

Creates and configures the Flask application with blueprints,
authentication, CSRF protection, and rate limiting.
"""

import logging
import os
import secrets
from typing import Any, Dict, Optional

from flask import Flask, jsonify, redirect, request, url_for
from flask_login import LoginManager, UserMixin, login_user
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from . import settings


class User(UserMixin):
    """
    User model for Flask-Login.

    Supports both password-based and OAuth authentication.
    """

    def __init__(
        self,
        user_id: str,
        auth_method: str = "password",
        email: str = None,
        display_name: str = None,
    ):
        """
        Initialize a user.

        Args:
            user_id: Unique user identifier (username)
            auth_method: Authentication method ("password", "oauth", "api", "disabled")
            email: User's email address
            display_name: User's display name
        """
        self.id = user_id
        self.auth_method = auth_method
        self.email = email
        self.display_name = display_name or user_id

    def get_id(self) -> str:
        """Return the user ID as a string."""
        return str(self.id)

    @property
    def is_authenticated(self) -> bool:
        """Check if user is authenticated."""
        return True

    @property
    def is_active(self) -> bool:
        """Check if user is active."""
        return True

    @property
    def is_anonymous(self) -> bool:
        """Check if user is anonymous."""
        return False


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)


csrf = CSRFProtect()


login_manager = LoginManager()


def create_app(config_override: Dict[str, Any] = None) -> Flask:
    """
    Create and configure the Flask application.

    Args:
        config_override: Optional configuration overrides

    Returns:
        Configured Flask application instance
    """
    app = Flask(__name__)

    app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

    app.config["APP_VERSION"] = getattr(settings, "APP_VERSION", "1.0.0")
    app.config["PREFERRED_URL_SCHEME"] = "http"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PERMANENT_SESSION_LIFETIME"] = 86400
    app.config["WTF_CSRF_TIME_LIMIT"] = 3600

    app.config["DOCKFLARE_USERNAME"] = os.environ.get("DOCKFLARE_USERNAME", "admin")
    app.config["DOCKFLARE_PASSWORD_HASH"] = os.environ.get("DOCKFLARE_PASSWORD_HASH")
    app.config["DISABLE_PASSWORD_LOGIN"] = os.environ.get(
        "DISABLE_PASSWORD_LOGIN", "false"
    ).lower() in ("true", "1", "yes")

    app.config["OAUTH_PROVIDERS"] = []
    app.config["OAUTH_AUTHORIZED_USERS"] = []

    oauth_client_id = os.environ.get("OAUTH_CLIENT_ID")
    oauth_client_secret = os.environ.get("OAUTH_CLIENT_SECRET")
    if oauth_client_id and oauth_client_secret:
        app.config["OAUTH_PROVIDERS"].append("cloudflare")
        authorized_users = os.environ.get("OAUTH_AUTHORIZED_USERS", "")
        if authorized_users:
            app.config["OAUTH_AUTHORIZED_USERS"] = [
                u.strip() for u in authorized_users.split(",") if u.strip()
            ]

    if config_override:
        app.config.update(config_override)

    csrf.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = "web.login"
    login_manager.login_message_category = "info"

    limiter.init_app(app)

    app.is_configured = bool(
        app.config.get("DOCKFLARE_PASSWORD_HASH")
        or app.config.get("OAUTH_PROVIDERS")
        or app.config.get("DISABLE_PASSWORD_LOGIN")
    )

    app.reconciliation_info = {
        "in_progress": False,
        "progress": 0,
        "total_items": 0,
        "processed_items": 0,
        "start_time": 0,
        "status": "Not started",
    }

    _configure_login_manager(app)

    _register_error_handlers(app)

    _register_blueprints(app)

    @app.context_processor
    def inject_version():
        """Inject app version into templates."""
        return {"app_version": app.config.get("APP_VERSION", "1.0.0")}

    return app


def _configure_login_manager(app: Flask):
    """Configure Flask-Login handlers."""

    @login_manager.unauthorized_handler
    def unauthorized():
        """Handle unauthorized access."""
        if app.config.get("DISABLE_PASSWORD_LOGIN"):
            user = User("anonymous", auth_method="disabled")
            login_user(user)
            return redirect(request.url)

        if request.path.startswith("/api/"):
            return jsonify({"status": "error", "message": "authentication_required"}), 401

        return redirect(url_for("web.login"))

    @login_manager.user_loader
    def load_user(user_id: str) -> Optional[User]:
        """Load user by ID."""
        if not app.is_configured:
            return None

        stored_username = app.config.get("DOCKFLARE_USERNAME")
        authorized_oauth_users = app.config.get("OAUTH_AUTHORIZED_USERS", [])

        if user_id == stored_username:
            return User(user_id, auth_method="password")
        elif user_id in authorized_oauth_users:
            return User(user_id, auth_method="oauth")

        return None

    @login_manager.request_loader
    def load_user_from_request(req) -> Optional[User]:
        """Load user from request headers for API authentication."""
        if req.path.startswith("/api/v2/auth/"):
            return None

        api_key = req.headers.get("X-API-Key") or req.args.get("api_key")
        master_key = os.environ.get("MASTER_API_KEY")

        if api_key and master_key and api_key == master_key:
            return User("api_user", auth_method="api")

        return None


def _register_error_handlers(app: Flask):
    """Register error handlers."""

    @app.errorhandler(400)
    def bad_request(error):
        """Handle bad request errors."""
        if request.path.startswith("/api/"):
            return jsonify({"status": "error", "message": "Bad request"}), 400
        return "Bad Request", 400

    @app.errorhandler(401)
    def unauthorized_error(error):
        """Handle unauthorized errors."""
        if request.path.startswith("/api/"):
            return jsonify({"status": "error", "message": "Unauthorized"}), 401
        return redirect(url_for("web.login"))

    @app.errorhandler(403)
    def forbidden(error):
        """Handle forbidden errors."""
        if request.path.startswith("/api/"):
            return jsonify({"status": "error", "message": "Forbidden"}), 403
        return "Forbidden", 403

    @app.errorhandler(404)
    def not_found(error):
        """Handle not found errors."""
        if request.path.startswith("/api/"):
            return jsonify({"status": "error", "message": "Not found"}), 404
        return "Not Found", 404

    @app.errorhandler(429)
    def rate_limited(error):
        """Handle rate limit errors."""
        if request.path.startswith("/api/"):
            return jsonify({"status": "error", "message": "Rate limit exceeded"}), 429
        return "Rate Limit Exceeded", 429

    @app.errorhandler(500)
    def internal_error(error):
        """Handle internal server errors."""
        logging.exception("Internal server error")
        if request.path.startswith("/api/"):
            return jsonify({"status": "error", "message": "Internal server error"}), 500
        return "Internal Server Error", 500


def _register_blueprints(app: Flask):
    """Register application blueprints."""
    try:
        from .web import api_blueprint, web_blueprint

        app.register_blueprint(web_blueprint)
        logging.info("Web blueprint registered")

        csrf.exempt(api_blueprint)
        app.register_blueprint(api_blueprint, url_prefix="/api/v1")
        logging.info("API v1 blueprint registered")

    except ImportError:
        logging.debug("Blueprints not yet available, skipping registration")


def get_current_user() -> Optional[User]:
    """Get the current logged-in user."""
    from flask_login import current_user

    if current_user.is_authenticated:
        return current_user
    return None


def verify_password(stored_hash: str, password: str) -> bool:
    """
    Verify a password against a stored hash.

    Args:
        stored_hash: The stored password hash
        password: The password to verify

    Returns:
        True if the password matches, False otherwise
    """
    import hashlib

    password_hash = hashlib.sha256(password.encode()).hexdigest()
    return password_hash == stored_hash


def hash_password(password: str) -> str:
    """
    Hash a password for storage.

    Args:
        password: The password to hash

    Returns:
        The hashed password
    """
    import hashlib

    return hashlib.sha256(password.encode()).hexdigest()


_app: Optional[Flask] = None


def get_app() -> Flask:
    """Get or create the Flask application."""
    global _app
    if _app is None:
        _app = create_app()
    return _app
