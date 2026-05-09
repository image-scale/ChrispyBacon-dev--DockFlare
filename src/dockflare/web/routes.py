"""
Web routes for the Flask application.

Provides UI routes for login, logout, and dashboard.
"""

from flask import (
    redirect,
    render_template_string,
    request,
    url_for,
    flash,
    current_app,
)
from flask_login import login_user, logout_user, login_required, current_user

from . import web_blueprint
from ..app import User, verify_password, limiter


LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Login - DockFlare</title>
    <style>
        body { font-family: sans-serif; max-width: 400px; margin: 100px auto; padding: 20px; }
        form { display: flex; flex-direction: column; gap: 10px; }
        input { padding: 10px; border: 1px solid #ccc; border-radius: 4px; }
        button { padding: 10px; background: #0066cc; color: white; border: none; border-radius: 4px; cursor: pointer; }
        button:hover { background: #0052a3; }
        .error { color: red; }
        .flash { padding: 10px; background: #f0f0f0; border-radius: 4px; margin-bottom: 10px; }
    </style>
</head>
<body>
    <h1>DockFlare Login</h1>
    {% for message in get_flashed_messages() %}
    <div class="flash">{{ message }}</div>
    {% endfor %}
    <form method="POST">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <input type="text" name="username" placeholder="Username" required>
        <input type="password" name="password" placeholder="Password" required>
        <button type="submit">Login</button>
    </form>
</body>
</html>
"""

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Dashboard - DockFlare</title>
    <style>
        body { font-family: sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
        header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        .logout { padding: 10px; background: #666; color: white; text-decoration: none; border-radius: 4px; }
    </style>
</head>
<body>
    <header>
        <h1>DockFlare Dashboard</h1>
        <a href="{{ url_for('web.logout') }}" class="logout">Logout</a>
    </header>
    <p>Welcome, {{ current_user.display_name }}!</p>
    <p>Version: {{ app_version }}</p>
</body>
</html>
"""


@web_blueprint.route("/")
def index():
    """Redirect to dashboard or login."""
    if current_user.is_authenticated:
        return redirect(url_for("web.dashboard"))
    return redirect(url_for("web.login"))


@web_blueprint.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    """Handle login page and form submission."""
    if current_user.is_authenticated:
        return redirect(url_for("web.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        stored_username = current_app.config.get("DOCKFLARE_USERNAME", "admin")
        stored_hash = current_app.config.get("DOCKFLARE_PASSWORD_HASH")

        if not stored_hash:
            flash("No password configured. Please set DOCKFLARE_PASSWORD_HASH.", "error")
            return render_template_string(LOGIN_TEMPLATE)

        if username == stored_username and verify_password(stored_hash, password):
            user = User(username, auth_method="password")
            login_user(user, remember=True)
            next_page = request.args.get("next")
            if next_page and next_page.startswith("/"):
                return redirect(next_page)
            return redirect(url_for("web.dashboard"))

        flash("Invalid username or password", "error")

    return render_template_string(LOGIN_TEMPLATE)


@web_blueprint.route("/logout")
@login_required
def logout():
    """Handle logout."""
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("web.login"))


@web_blueprint.route("/dashboard")
@login_required
def dashboard():
    """Display the main dashboard."""
    return render_template_string(DASHBOARD_TEMPLATE)


@web_blueprint.before_request
def auto_login_if_disabled():
    """Auto-login if password login is disabled."""
    if current_app.config.get("DISABLE_PASSWORD_LOGIN"):
        if not current_user.is_authenticated:
            user = User("anonymous", auth_method="disabled")
            login_user(user, remember=True)


@web_blueprint.route("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok", "version": current_app.config.get("APP_VERSION", "1.0.0")}
