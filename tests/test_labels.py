"""Tests for the Docker label parser."""

import pytest
from unittest.mock import patch

from dockflare.labels import (
    extract_label,
    extract_bool_label,
    validate_hostname,
    validate_service,
    normalize_path,
    normalize_access_groups,
    parse_container_labels,
    get_rule_key,
    RouteConfig,
)


class TestExtractLabel:
    """Tests for extract_label function."""

    def test_extracts_with_primary_prefix(self):
        """Should extract label using primary prefix 'dockflare.'."""
        labels = {"dockflare.enable": "true"}
        result = extract_label(labels, "enable")
        assert result == "true"

    def test_falls_back_to_legacy_prefix(self):
        """Should fall back to legacy prefix 'cloudflare.tunnel.'."""
        labels = {"cloudflare.tunnel.hostname": "app.example.com"}
        result = extract_label(labels, "hostname")
        assert result == "app.example.com"

    def test_prefers_primary_over_legacy(self):
        """Should prefer primary prefix over legacy."""
        labels = {
            "dockflare.hostname": "primary.com",
            "cloudflare.tunnel.hostname": "legacy.com",
        }
        result = extract_label(labels, "hostname")
        assert result == "primary.com"

    def test_custom_prefix_takes_precedence(self):
        """Should check custom prefix first."""
        labels = {
            "custom.hostname": "custom.com",
            "dockflare.hostname": "primary.com",
        }
        result = extract_label(labels, "hostname", custom_prefix="custom")
        assert result == "custom.com"

    def test_returns_default_when_not_found(self):
        """Should return default when label not found."""
        labels = {}
        result = extract_label(labels, "missing", default="default_value")
        assert result == "default_value"

    def test_returns_none_when_not_found_no_default(self):
        """Should return None when label not found and no default."""
        labels = {}
        result = extract_label(labels, "missing")
        assert result is None


class TestExtractBoolLabel:
    """Tests for extract_bool_label function."""

    def test_recognizes_true_values(self):
        """Should recognize various true values."""
        for val in ["true", "True", "TRUE", "1", "t", "yes", "YES"]:
            labels = {"dockflare.flag": val}
            assert extract_bool_label(labels, "flag") is True

    def test_returns_false_for_other_values(self):
        """Should return False for non-true values."""
        for val in ["false", "0", "no", "anything"]:
            labels = {"dockflare.flag": val}
            assert extract_bool_label(labels, "flag") is False

    def test_returns_default_when_not_found(self):
        """Should return default when not found."""
        labels = {}
        assert extract_bool_label(labels, "missing", default=True) is True
        assert extract_bool_label(labels, "missing", default=False) is False


class TestValidateHostname:
    """Tests for validate_hostname function."""

    def test_valid_hostname(self):
        """Should return True for valid hostnames."""
        assert validate_hostname("example.com") is True
        assert validate_hostname("api.example.com") is True
        assert validate_hostname("sub.api.example.com") is True

    def test_valid_wildcard_hostname(self):
        """Should return True for valid wildcard hostnames."""
        assert validate_hostname("*.example.com") is True
        assert validate_hostname("*.api.example.com") is True

    def test_invalid_hostname_starting_with_dash(self):
        """Should return False for hostname starting with dash."""
        assert validate_hostname("-invalid.com") is False

    def test_invalid_hostname_ending_with_dash(self):
        """Should return False for hostname ending with dash."""
        assert validate_hostname("invalid-.com") is False

    def test_invalid_hostname_with_special_chars(self):
        """Should return False for hostname with invalid characters."""
        assert validate_hostname("invalid_host.com") is False
        assert validate_hostname("invalid!host.com") is False

    def test_empty_hostname(self):
        """Should return False for empty hostname."""
        assert validate_hostname("") is False
        assert validate_hostname(None) is False

    def test_hostname_too_long(self):
        """Should return False for hostname exceeding 253 chars."""
        long_hostname = "a" * 64 + "." + "b" * 64 + "." + "c" * 64 + "." + "d" * 64
        assert validate_hostname(long_hostname) is False

    def test_label_too_long(self):
        """Should return False for label exceeding 63 chars."""
        long_label = "a" * 64 + ".com"
        assert validate_hostname(long_label) is False


class TestValidateService:
    """Tests for validate_service function."""

    def test_valid_http_service(self):
        """Should return True for valid HTTP service URLs."""
        assert validate_service("http://app:8080") is True
        assert validate_service("http://localhost:80") is True
        assert validate_service("http://192.168.1.1:3000") is True

    def test_valid_https_service(self):
        """Should return True for valid HTTPS service URLs."""
        assert validate_service("https://app:443") is True
        assert validate_service("https://secure.local:8443") is True

    def test_valid_tcp_service(self):
        """Should return True for valid TCP service URLs."""
        assert validate_service("tcp://app:22") is True
        assert validate_service("tcp://db:3306") is True

    def test_valid_ssh_service(self):
        """Should return True for valid SSH service URLs."""
        assert validate_service("ssh://server:22") is True

    def test_valid_rdp_service(self):
        """Should return True for valid RDP service URLs."""
        assert validate_service("rdp://desktop:3389") is True

    def test_valid_http_status_service(self):
        """Should return True for http_status codes."""
        assert validate_service("http_status:404") is True
        assert validate_service("http_status:503") is True

    def test_valid_bastion_service(self):
        """Should return True for bastion service."""
        assert validate_service("bastion") is True

    def test_invalid_service_format(self):
        """Should return False for invalid service format."""
        assert validate_service("invalid") is False
        assert validate_service("ftp://server:21") is False
        assert validate_service("") is False
        assert validate_service(None) is False


class TestNormalizePath:
    """Tests for normalize_path function."""

    def test_adds_leading_slash(self):
        """Should add leading slash if missing."""
        assert normalize_path("api") == "/api"
        assert normalize_path("path/to/resource") == "/path/to/resource"

    def test_removes_trailing_slash(self):
        """Should remove trailing slash."""
        assert normalize_path("/api/") == "/api"

    def test_preserves_root_path(self):
        """Should preserve root path."""
        assert normalize_path("/") == "/"

    def test_handles_empty_value(self):
        """Should return empty string for empty/None."""
        assert normalize_path("") == ""
        assert normalize_path(None) == ""
        assert normalize_path("  ") == ""


class TestNormalizeAccessGroups:
    """Tests for normalize_access_groups function."""

    def test_normalizes_comma_separated_string(self):
        """Should split comma-separated string."""
        result = normalize_access_groups("group1, group2, group3")
        assert result == ["group1", "group2", "group3"]

    def test_normalizes_single_string(self):
        """Should wrap single string in list."""
        result = normalize_access_groups("single-group")
        assert result == ["single-group"]

    def test_normalizes_list(self):
        """Should strip items in list."""
        result = normalize_access_groups([" group1 ", " group2 "])
        assert result == ["group1", "group2"]

    def test_returns_empty_for_none(self):
        """Should return empty list for None."""
        assert normalize_access_groups(None) == []

    def test_filters_empty_items(self):
        """Should filter out empty items."""
        result = normalize_access_groups(["group1", "", "group2"])
        assert result == ["group1", "group2"]


class TestParseContainerLabels:
    """Tests for parse_container_labels function."""

    def test_extracts_basic_route(self):
        """Should extract hostname, service, and access settings."""
        labels = {
            "dockflare.enable": "true",
            "dockflare.hostname": "app.example.com",
            "dockflare.service": "http://app:8080",
        }
        routes = parse_container_labels(labels)
        assert len(routes) == 1
        assert routes[0].hostname == "app.example.com"
        assert routes[0].service == "http://app:8080"

    def test_returns_empty_when_enable_false(self):
        """Should return empty list when enable=false."""
        labels = {
            "dockflare.enable": "false",
            "dockflare.hostname": "app.example.com",
            "dockflare.service": "http://app:8080",
        }
        routes = parse_container_labels(labels)
        assert routes == []

    def test_returns_empty_when_enable_missing(self):
        """Should return empty list when enable is missing."""
        labels = {
            "dockflare.hostname": "app.example.com",
            "dockflare.service": "http://app:8080",
        }
        routes = parse_container_labels(labels)
        assert routes == []

    def test_handles_indexed_labels(self):
        """Should handle indexed labels for multiple routes."""
        labels = {
            "dockflare.enable": "true",
            "dockflare.hostname": "main.example.com",
            "dockflare.service": "http://app:8080",
            "dockflare.0.hostname": "api.example.com",
            "dockflare.0.service": "http://api:3000",
            "dockflare.1.hostname": "admin.example.com",
            "dockflare.1.service": "http://admin:5000",
        }
        routes = parse_container_labels(labels)
        assert len(routes) == 3
        assert routes[0].hostname == "main.example.com"
        assert routes[1].hostname == "api.example.com"
        assert routes[2].hostname == "admin.example.com"

    def test_extracts_access_settings(self):
        """Should extract access group settings."""
        labels = {
            "dockflare.enable": "true",
            "dockflare.hostname": "app.example.com",
            "dockflare.service": "http://app:8080",
            "dockflare.access.groups": "admin, users",
            "dockflare.access.session_duration": "12h",
        }
        routes = parse_container_labels(labels)
        assert len(routes) == 1
        assert routes[0].access_groups == ["admin", "users"]
        assert routes[0].access_session_duration == "12h"

    def test_extracts_origin_settings(self):
        """Should extract origin server settings."""
        labels = {
            "dockflare.enable": "true",
            "dockflare.hostname": "app.example.com",
            "dockflare.service": "http://app:8080",
            "dockflare.no_tls_verify": "true",
            "dockflare.originsrvname": "origin.local",
            "dockflare.httpHostHeader": "custom-host",
        }
        routes = parse_container_labels(labels)
        assert len(routes) == 1
        assert routes[0].no_tls_verify is True
        assert routes[0].origin_server_name == "origin.local"
        assert routes[0].http_host_header == "custom-host"

    def test_stores_container_info(self):
        """Should store container ID and name."""
        labels = {
            "dockflare.enable": "true",
            "dockflare.hostname": "app.example.com",
            "dockflare.service": "http://app:8080",
        }
        routes = parse_container_labels(labels, container_id="abc123", container_name="my-app")
        assert routes[0].container_id == "abc123"
        assert routes[0].container_name == "my-app"

    def test_indexed_inherits_defaults(self):
        """Indexed routes should inherit default settings."""
        labels = {
            "dockflare.enable": "true",
            "dockflare.service": "http://default:8080",
            "dockflare.access.group": "default-group",
            "dockflare.0.hostname": "indexed.example.com",
        }
        routes = parse_container_labels(labels)
        assert len(routes) == 1
        assert routes[0].hostname == "indexed.example.com"
        assert routes[0].service == "http://default:8080"
        assert routes[0].access_groups == ["default-group"]


class TestGetRuleKey:
    """Tests for get_rule_key function."""

    def test_generates_key_with_path(self):
        """Should generate key with hostname and path."""
        key = get_rule_key("example.com", "/api")
        assert key == "example.com|/api"

    def test_generates_key_without_path(self):
        """Should generate key with empty path when None."""
        key = get_rule_key("example.com", None)
        assert key == "example.com|"

    def test_strips_path_whitespace(self):
        """Should strip whitespace from path."""
        key = get_rule_key("example.com", "  /api  ")
        assert key == "example.com|/api"


class TestRouteConfig:
    """Tests for RouteConfig dataclass."""

    def test_default_values(self):
        """Should have sensible defaults."""
        route = RouteConfig(hostname="example.com", service="http://app:80")
        assert route.zone_name is None
        assert route.path is None
        assert route.no_tls_verify is False
        assert route.access_groups == []
        assert route.access_session_duration == "24h"
        assert route.access_app_launcher_visible is False
