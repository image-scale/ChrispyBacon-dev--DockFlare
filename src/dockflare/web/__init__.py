"""
Web blueprints for Flask application.

Contains web routes for UI and API endpoints.
"""

from flask import Blueprint


web_blueprint = Blueprint("web", __name__)


api_blueprint = Blueprint("api", __name__)


from . import routes
from . import api_routes
