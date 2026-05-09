"""
Docker container label parser for extracting tunnel configuration.

Parses container labels to extract hostname, service, and access policy settings
with support for primary, legacy, and custom label prefixes.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import settings


@dataclass
class RouteConfig:
    """Configuration for a single tunnel route."""

    hostname: str
    service: str
    zone_name: Optional[str] = None
    path: Optional[str] = None
    no_tls_verify: bool = False
    origin_server_name: Optional[str] = None
    http_host_header: Optional[str] = None
    http2_origin: bool = False
    disable_chunked_encoding: bool = False
    access_groups: List[str] = field(default_factory=list)
    access_policy_type: Optional[str] = None
    access_app_name: Optional[str] = None
    access_session_duration: str = "24h"
    access_app_launcher_visible: bool = False
    container_id: Optional[str] = None
    container_name: Optional[str] = None


def extract_label(
    labels: Dict[str, str],
    key_suffix: str,
    default: Any = None,
    custom_prefix: str = None,
) -> Any:
    """
    Extract a label value using prefix hierarchy.

    Checks custom prefix first (if set), then primary prefix, then legacy prefix.

    Args:
        labels: Container labels dictionary
        key_suffix: Label key suffix (e.g., "enable", "hostname")
        default: Default value if label not found
        custom_prefix: Custom prefix override (or uses settings.CUSTOM_LABEL_PREFIX)

    Returns:
        Label value or default
    """
    custom = custom_prefix or settings.CUSTOM_LABEL_PREFIX

    if custom:
        custom_key = f"{custom.rstrip('.')}.{key_suffix}"
        if custom_key in labels:
            return labels[custom_key]

    primary_key = f"{settings.PRIMARY_LABEL_PREFIX}{key_suffix}"
    if primary_key in labels:
        return labels[primary_key]

    legacy_key = f"{settings.LEGACY_LABEL_PREFIX}{key_suffix}"
    if legacy_key in labels:
        return labels[legacy_key]

    return default


def extract_bool_label(
    labels: Dict[str, str],
    key_suffix: str,
    default: bool = False,
    custom_prefix: str = None,
) -> bool:
    """Extract a boolean label value."""
    value = extract_label(labels, key_suffix, str(default).lower(), custom_prefix)
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "t", "yes")


def validate_hostname(hostname: str) -> bool:
    """
    Validate a hostname string.

    Supports regular hostnames and wildcards (e.g., "*.example.com").

    Args:
        hostname: Hostname to validate

    Returns:
        True if valid, False otherwise
    """
    if not hostname:
        return False

    if hostname.startswith("*."):
        domain_part = hostname[2:]
        if not domain_part or len(domain_part) > 253:
            return False
        for label in domain_part.split("."):
            if not label or len(label) > 63:
                return False
            if not all(c.isalnum() or c == "-" for c in label):
                return False
            if label.startswith("-") or label.endswith("-"):
                return False
        return True

    if len(hostname) > 253:
        return False

    labels = hostname.split(".")
    for label in labels:
        if not label or len(label) > 63:
            return False
        if not all(c.isalnum() or c == "-" for c in label):
            return False
        if label.startswith("-") or label.endswith("-"):
            return False

    return True


def validate_service(service_str: str) -> bool:
    """
    Validate a service URL string.

    Supports HTTP, HTTPS, TCP, SSH, RDP, http_status, and bastion.

    Args:
        service_str: Service URL to validate

    Returns:
        True if valid, False otherwise
    """
    if not service_str or not isinstance(service_str, str):
        return False

    service_str = service_str.strip()

    if service_str == "bastion":
        return True

    host_ip_pattern = (
        r"([a-zA-Z0-9_](?:[a-zA-Z0-9\-_]{0,61}[a-zA-Z0-9_])?"
        r"(?:\.[a-zA-Z0-9_](?:[a-zA-Z0-9\-_]{0,61}[a-zA-Z0-9_])?)*"
        r"|[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}"
        r"|\[[0-9a-fA-F:]+\])"
    )
    port_pattern = r"[0-9]{1,5}"

    http_https_pattern = rf"^(?:https?)://{host_ip_pattern}(?::{port_pattern})?$"
    tcp_pattern = rf"^(?:tcp)://{host_ip_pattern}:{port_pattern}$"
    ssh_pattern = rf"^(?:ssh)://{host_ip_pattern}:{port_pattern}$"
    rdp_pattern = rf"^(?:rdp)://{host_ip_pattern}:{port_pattern}$"
    http_status_pattern = r"^http_status:([1-5][0-9]{2})$"

    if re.fullmatch(http_https_pattern, service_str):
        return True
    if re.fullmatch(tcp_pattern, service_str):
        return True
    if re.fullmatch(ssh_pattern, service_str):
        return True
    if re.fullmatch(rdp_pattern, service_str):
        return True
    if re.fullmatch(http_status_pattern, service_str):
        return True

    logging.warning(f"Invalid service format: '{service_str}'")
    return False


def normalize_path(value: Optional[str]) -> str:
    """Normalize a path value to ensure proper format."""
    if value is None:
        return ""

    path_str = str(value).strip()
    if not path_str:
        return ""

    if not path_str.startswith("/"):
        path_str = "/" + path_str

    if len(path_str) > 1 and path_str.endswith("/"):
        path_str = path_str.rstrip("/")

    return path_str


def normalize_access_groups(value: Any) -> List[str]:
    """Normalize access group value to a list of strings."""
    if value is None:
        return []

    if isinstance(value, list):
        return [str(item).strip() for item in value if item and str(item).strip()]

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if "," in stripped:
            return [g.strip() for g in stripped.split(",") if g.strip()]
        return [stripped]

    return [str(value)]


def parse_container_labels(
    labels: Dict[str, str],
    container_id: str = None,
    container_name: str = None,
) -> List[RouteConfig]:
    """
    Parse container labels to extract route configurations.

    Args:
        labels: Container labels dictionary
        container_id: Optional container ID for tracking
        container_name: Optional container name for tracking

    Returns:
        List of RouteConfig objects for each valid route
    """
    is_enabled = extract_bool_label(labels, "enable", False)
    if not is_enabled:
        logging.debug(f"Container {container_name or 'unknown'}: enable label not set to true")
        return []

    routes = []

    default_path = extract_label(labels, "path")
    default_origin_server_name = extract_label(labels, "originsrvname")
    default_http_host_header = extract_label(labels, "httpHostHeader")
    default_no_tls_verify = extract_bool_label(labels, "no_tls_verify", False)
    default_http2_origin = extract_bool_label(labels, "http2_origin", False)
    default_disable_chunked = extract_bool_label(labels, "disable_chunked_encoding", False)

    access_groups_str = extract_label(labels, "access.groups")
    access_group = extract_label(labels, "access.group")
    access_policy_type = extract_label(labels, "access.policy")
    access_app_name = extract_label(labels, "access.name")
    access_session_duration = extract_label(labels, "access.session_duration", "24h")
    access_app_launcher_visible = extract_bool_label(labels, "access.app_launcher_visible", False)

    if access_groups_str:
        default_access_groups = normalize_access_groups(access_groups_str)
    elif access_group:
        default_access_groups = normalize_access_groups(access_group)
    else:
        default_access_groups = []

    hostname = extract_label(labels, "hostname")
    service = extract_label(labels, "service")
    zone_name = extract_label(labels, "zonename")

    if hostname and service:
        if validate_hostname(hostname) and validate_service(service):
            routes.append(
                RouteConfig(
                    hostname=hostname,
                    service=service,
                    zone_name=zone_name,
                    path=normalize_path(default_path),
                    no_tls_verify=default_no_tls_verify,
                    origin_server_name=default_origin_server_name.strip() if default_origin_server_name else None,
                    http_host_header=default_http_host_header.strip() if default_http_host_header else None,
                    http2_origin=default_http2_origin,
                    disable_chunked_encoding=default_disable_chunked,
                    access_groups=default_access_groups,
                    access_policy_type=access_policy_type,
                    access_app_name=access_app_name,
                    access_session_duration=access_session_duration,
                    access_app_launcher_visible=access_app_launcher_visible,
                    container_id=container_id,
                    container_name=container_name,
                )
            )
        else:
            logging.warning(
                f"Invalid hostname '{hostname}' or service '{service}' "
                f"for container {container_name or 'unknown'}"
            )

    index = 0
    while True:
        indexed_hostname = extract_label(labels, f"{index}.hostname")
        if not indexed_hostname:
            break

        indexed_service = extract_label(labels, f"{index}.service", service)
        if not indexed_service:
            logging.warning(
                f"Indexed hostname {indexed_hostname} missing service at index {index}"
            )
            index += 1
            continue

        indexed_path = extract_label(labels, f"{index}.path", default_path)
        indexed_zone_name = extract_label(labels, f"{index}.zonename", zone_name)
        indexed_no_tls = extract_bool_label(labels, f"{index}.no_tls_verify", default_no_tls_verify)
        indexed_origin_name = extract_label(labels, f"{index}.originsrvname", default_origin_server_name)
        indexed_http_header = extract_label(labels, f"{index}.httpHostHeader", default_http_host_header)
        indexed_http2 = extract_bool_label(labels, f"{index}.http2_origin", default_http2_origin)
        indexed_disable_chunked = extract_bool_label(labels, f"{index}.disable_chunked_encoding", default_disable_chunked)

        indexed_groups_str = extract_label(labels, f"{index}.access.groups")
        indexed_group = extract_label(labels, f"{index}.access.group")

        if indexed_groups_str:
            indexed_access_groups = normalize_access_groups(indexed_groups_str)
        elif indexed_group:
            indexed_access_groups = normalize_access_groups(indexed_group)
        else:
            indexed_access_groups = default_access_groups

        indexed_policy_type = extract_label(labels, f"{index}.access.policy", access_policy_type)
        indexed_app_name = extract_label(labels, f"{index}.access.name", access_app_name)
        indexed_session = extract_label(labels, f"{index}.access.session_duration", access_session_duration)
        indexed_launcher_visible = extract_bool_label(labels, f"{index}.access.app_launcher_visible", access_app_launcher_visible)

        if validate_hostname(indexed_hostname) and validate_service(indexed_service):
            routes.append(
                RouteConfig(
                    hostname=indexed_hostname,
                    service=indexed_service,
                    zone_name=indexed_zone_name,
                    path=normalize_path(indexed_path),
                    no_tls_verify=indexed_no_tls,
                    origin_server_name=indexed_origin_name.strip() if indexed_origin_name else None,
                    http_host_header=indexed_http_header.strip() if indexed_http_header else None,
                    http2_origin=indexed_http2,
                    disable_chunked_encoding=indexed_disable_chunked,
                    access_groups=indexed_access_groups,
                    access_policy_type=indexed_policy_type,
                    access_app_name=indexed_app_name,
                    access_session_duration=indexed_session,
                    access_app_launcher_visible=indexed_launcher_visible,
                    container_id=container_id,
                    container_name=container_name,
                )
            )
        else:
            logging.warning(
                f"Invalid indexed hostname '{indexed_hostname}' or service '{indexed_service}' at index {index}"
            )

        index += 1

    return routes


def get_rule_key(hostname: str, path: Optional[str] = None) -> str:
    """Generate a unique key for a rule based on hostname and path."""
    path_str = str(path or "").strip()
    return f"{hostname}|{path_str}"
