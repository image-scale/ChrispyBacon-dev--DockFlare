"""
Configuration settings for the DockFlare application.

Loads settings from environment variables with sensible defaults.
"""

import os
import logging


def get_int_env(name: str, default: int, minimum: int = None) -> int:
    """
    Get an integer from environment variable with optional minimum validation.

    Args:
        name: Environment variable name
        default: Default value if not set or invalid
        minimum: Optional minimum allowed value

    Returns:
        The parsed integer or default value
    """
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        parsed = int(raw_value)
        if minimum is not None and parsed < minimum:
            logging.warning(
                f"Environment variable {name} must be >= {minimum}. Using default {default}."
            )
            return default
        return parsed
    except ValueError:
        logging.warning(
            f"Environment variable {name} must be an integer. Using default {default}."
        )
        return default


def get_bool_env(name: str, default: bool = False) -> bool:
    """
    Get a boolean from environment variable.

    Recognizes 'true', '1', 't', 'yes' as True (case-insensitive).
    """
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.lower() in ('true', '1', 't', 'yes')


def get_list_env(name: str, default: list = None) -> list:
    """
    Get a comma-separated list from environment variable.
    """
    raw_value = os.getenv(name)
    if raw_value is None:
        return default if default is not None else []
    return [item.strip() for item in raw_value.split(',') if item.strip()]


# Application version
APP_VERSION = "v1.0.0"

# Logging configuration
LOG_LEVEL = os.getenv('LOG_LEVEL', 'WARNING').upper()

# Cloudflare API settings
CF_API_BASE_URL = "https://api.cloudflare.com/client/v4"
CF_API_TOKEN = os.getenv('CF_API_TOKEN')
CF_ACCOUNT_ID = os.getenv('CF_ACCOUNT_ID')
CF_ZONE_ID = os.getenv('CF_ZONE_ID')

CF_HEADERS = {
    "Content-Type": "application/json",
}

# Retry configuration
MAX_CF_UPDATE_RETRIES = 3
CF_UPDATE_RETRY_DELAY = 2
CF_UPDATE_BACKOFF_FACTOR = 2

# Tunnel configuration
TUNNEL_NAME = os.getenv('TUNNEL_NAME', 'dockflare-tunnel')
USE_EXTERNAL_CLOUDFLARED = get_bool_env('USE_EXTERNAL_CLOUDFLARED', False)
EXTERNAL_TUNNEL_ID = os.getenv('EXTERNAL_TUNNEL_ID')
CLOUDFLARED_IMAGE = "cloudflare/cloudflared:latest"
CLOUDFLARED_NETWORK_NAME = os.getenv('CLOUDFLARED_NETWORK_NAME', 'cloudflare-net')

# Container label prefixes
PRIMARY_LABEL_PREFIX = 'dockflare.'
LEGACY_LABEL_PREFIX = 'cloudflare.tunnel.'
CUSTOM_LABEL_PREFIX = os.getenv('LABEL_PREFIX')
LABEL_PREFIX = CUSTOM_LABEL_PREFIX or PRIMARY_LABEL_PREFIX

# State and persistence
STATE_FILE_PATH = os.getenv('STATE_FILE_PATH', '/app/data/state.json')
GRACE_PERIOD_SECONDS = get_int_env('GRACE_PERIOD_SECONDS', 600, minimum=0)

# Intervals and timeouts
CLEANUP_INTERVAL_SECONDS = get_int_env('CLEANUP_INTERVAL_SECONDS', 60, minimum=1)
AGENT_STATUS_UPDATE_INTERVAL_SECONDS = get_int_env('AGENT_STATUS_UPDATE_INTERVAL_SECONDS', 30, minimum=1)
AGENT_HEARTBEAT_TIMEOUT = get_int_env('AGENT_HEARTBEAT_TIMEOUT', 60, minimum=1)
AGENT_COMMAND_POLL_INTERVAL = get_int_env('AGENT_COMMAND_POLL_INTERVAL', 10, minimum=1)

# Concurrency settings
MAX_CONCURRENT_DNS_OPS = get_int_env('MAX_CONCURRENT_DNS_OPS', 5, minimum=1)
RECONCILIATION_BATCH_SIZE = get_int_env('RECONCILIATION_BATCH_SIZE', 5, minimum=1)
MAX_LOG_QUEUE_SIZE = 200

# Cache settings
ACCOUNT_EMAIL_CACHE_TTL = 3600

# Redis configuration
REDIS_URL = os.getenv('REDIS_URL')
REDIS_DB_INDEX = get_int_env('REDIS_DB_INDEX', 0, minimum=0)

# Web server settings
WAITRESS_HOST = os.getenv('WAITRESS_HOST', '0.0.0.0')
WAITRESS_PORT = get_int_env('WAITRESS_PORT', 5000, minimum=1)
WAITRESS_THREADS = get_int_env('WAITRESS_THREADS', 128, minimum=1)
WAITRESS_CONNECTION_LIMIT = get_int_env('WAITRESS_CONNECTION_LIMIT', 256, minimum=1)
WAITRESS_BACKLOG = get_int_env('WAITRESS_BACKLOG', 2048, minimum=1)
WAITRESS_CHANNEL_TIMEOUT = get_int_env('WAITRESS_CHANNEL_TIMEOUT', 360, minimum=1)

# Agent settings
AGENT_API_PREFIX = os.getenv('AGENT_API_PREFIX', '/api/v2/agents')
AGENT_ENROLLMENT_REQUIRED = get_bool_env('AGENT_ENROLLMENT_REQUIRED', True)
AGENT_KEY_STORAGE_PATH = os.getenv('AGENT_KEY_STORAGE_PATH')
AUTO_RESTORE_AGENT_RULES = get_bool_env('AUTO_RESTORE_AGENT_RULES', True)
AUTO_RESTORE_COOLDOWN_SECONDS = get_int_env('AUTO_RESTORE_COOLDOWN_SECONDS', 60, minimum=0)

# Feature flags
USE_REUSABLE_POLICIES = get_bool_env('USE_REUSABLE_POLICIES', True)
SYNC_ALL_CLOUDFLARE_POLICIES = get_bool_env('SYNC_ALL_CLOUDFLARE_POLICIES', False)
PRESERVE_UNMANAGED_CF_INGRESS_FIELDS = False
SCAN_ALL_NETWORKS = get_bool_env('SCAN_ALL_NETWORKS', False)

# Public URL
DOCKFLARE_PUBLIC_URL = os.getenv('DOCKFLARE_PUBLIC_URL', '')

# Master API key
MASTER_API_KEY = os.getenv('DOCKFLARE_API_KEY')

# DNS zone scanning
TUNNEL_DNS_SCAN_ZONE_NAMES = get_list_env('TUNNEL_DNS_SCAN_ZONE_NAMES', [])

# Cloudflared metrics
CLOUDFLARED_METRICS_PORT = None
_metrics_port_env = os.getenv('CLOUDFLARED_METRICS_PORT')
if _metrics_port_env:
    try:
        _port = int(_metrics_port_env)
        if 1 <= _port <= 65535:
            CLOUDFLARED_METRICS_PORT = _port
        else:
            logging.warning(f"Metrics port {_port} outside valid range (1-65535). Disabling.")
    except ValueError:
        logging.warning(f"Invalid CLOUDFLARED_METRICS_PORT: '{_metrics_port_env}'. Must be a number.")

# Email settings (disabled by default)
EMAIL_ENABLED = False
EMAIL_CONFIG = {}
MAIL_MANAGER_INTERNAL_URL = os.getenv('MAIL_MANAGER_INTERNAL_URL', 'http://dockflare-mail-manager:8025')
EMAIL_JWT_ALGORITHM = 'EdDSA'
EMAIL_JWT_ISSUER = 'dockflare-master'
EMAIL_JWT_AUDIENCE = 'dockflare-mail'
EMAIL_JWT_EXPIRY_SECONDS = 3600


def build_cloudflared_container_name(tunnel_name: str) -> str:
    """Build a sanitized container name from tunnel name."""
    sanitized = tunnel_name.replace(' ', '-').replace('_', '-').lower()
    return f"cloudflared-{sanitized}"


# Set container name based on tunnel
if not USE_EXTERNAL_CLOUDFLARED:
    CLOUDFLARED_CONTAINER_NAME = os.getenv(
        'CLOUDFLARED_CONTAINER_NAME',
        build_cloudflared_container_name(TUNNEL_NAME)
    )
else:
    CLOUDFLARED_CONTAINER_NAME = None
