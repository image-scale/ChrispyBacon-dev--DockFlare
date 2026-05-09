"""Tests for the settings module."""

import os
import pytest
from unittest.mock import patch


class TestGetIntEnv:
    """Tests for the get_int_env function."""

    def test_returns_default_when_not_set(self):
        """Should return default when environment variable is not set."""
        with patch.dict(os.environ, {}, clear=True):
            from dockflare.settings import get_int_env
            result = get_int_env("TEST_INT_NOTSET", 100)
            assert result == 100

    def test_returns_parsed_value_when_set(self):
        """Should return parsed integer when environment variable is set."""
        with patch.dict(os.environ, {"TEST_INT_SET": "50"}):
            from dockflare.settings import get_int_env
            result = get_int_env("TEST_INT_SET", 100)
            assert result == 50

    def test_returns_default_on_invalid_value(self, caplog):
        """Should return default and log warning when value is not an integer."""
        with patch.dict(os.environ, {"TEST_INT_INVALID": "invalid"}):
            from dockflare.settings import get_int_env
            import logging
            with caplog.at_level(logging.WARNING):
                result = get_int_env("TEST_INT_INVALID", 100)
            assert result == 100
            assert "must be an integer" in caplog.text

    def test_returns_default_when_below_minimum(self, caplog):
        """Should return default and log warning when value is below minimum."""
        with patch.dict(os.environ, {"TEST_INT_MIN": "5"}):
            from dockflare.settings import get_int_env
            import logging
            with caplog.at_level(logging.WARNING):
                result = get_int_env("TEST_INT_MIN", 100, minimum=10)
            assert result == 100
            assert "must be >=" in caplog.text

    def test_returns_value_when_at_minimum(self):
        """Should return parsed value when exactly at minimum."""
        with patch.dict(os.environ, {"TEST_INT_AT_MIN": "10"}):
            from dockflare.settings import get_int_env
            result = get_int_env("TEST_INT_AT_MIN", 100, minimum=10)
            assert result == 10

    def test_returns_value_when_above_minimum(self):
        """Should return parsed value when above minimum."""
        with patch.dict(os.environ, {"TEST_INT_ABOVE_MIN": "20"}):
            from dockflare.settings import get_int_env
            result = get_int_env("TEST_INT_ABOVE_MIN", 100, minimum=10)
            assert result == 20


class TestGetBoolEnv:
    """Tests for the get_bool_env function."""

    def test_returns_default_when_not_set(self):
        """Should return default when environment variable is not set."""
        with patch.dict(os.environ, {}, clear=True):
            from dockflare.settings import get_bool_env
            assert get_bool_env("BOOL_NOTSET", False) is False
            assert get_bool_env("BOOL_NOTSET", True) is True

    def test_recognizes_true_values(self):
        """Should recognize various true values."""
        from dockflare.settings import get_bool_env
        for val in ['true', 'True', 'TRUE', '1', 't', 'T', 'yes', 'YES']:
            with patch.dict(os.environ, {"BOOL_TRUE": val}):
                assert get_bool_env("BOOL_TRUE", False) is True

    def test_returns_false_for_other_values(self):
        """Should return False for non-true values."""
        from dockflare.settings import get_bool_env
        for val in ['false', '0', 'no', 'anything', '']:
            with patch.dict(os.environ, {"BOOL_FALSE": val}):
                assert get_bool_env("BOOL_FALSE", True) is False


class TestGetListEnv:
    """Tests for the get_list_env function."""

    def test_returns_default_when_not_set(self):
        """Should return default when environment variable is not set."""
        with patch.dict(os.environ, {}, clear=True):
            from dockflare.settings import get_list_env
            assert get_list_env("LIST_NOTSET") == []
            assert get_list_env("LIST_NOTSET", ["a"]) == ["a"]

    def test_splits_comma_separated_values(self):
        """Should split comma-separated values."""
        with patch.dict(os.environ, {"LIST_CSV": "one, two, three"}):
            from dockflare.settings import get_list_env
            result = get_list_env("LIST_CSV")
            assert result == ["one", "two", "three"]

    def test_filters_empty_values(self):
        """Should filter out empty values."""
        with patch.dict(os.environ, {"LIST_EMPTY": "one, , two, ,"}):
            from dockflare.settings import get_list_env
            result = get_list_env("LIST_EMPTY")
            assert result == ["one", "two"]


class TestDefaultValues:
    """Tests for default configuration values."""

    def test_app_version_format(self):
        """APP_VERSION should be a version string starting with 'v'."""
        from dockflare.settings import APP_VERSION
        assert isinstance(APP_VERSION, str)
        assert APP_VERSION.startswith('v')

    def test_log_level_default(self):
        """LOG_LEVEL should default to WARNING."""
        with patch.dict(os.environ, {}, clear=True):
            import importlib
            import dockflare.settings as settings
            importlib.reload(settings)
            assert settings.LOG_LEVEL == "WARNING"

    def test_cf_api_base_url(self):
        """CF_API_BASE_URL should be the Cloudflare API endpoint."""
        from dockflare.settings import CF_API_BASE_URL
        assert CF_API_BASE_URL == "https://api.cloudflare.com/client/v4"

    def test_label_prefix_default(self):
        """LABEL_PREFIX should default to 'dockflare.'."""
        with patch.dict(os.environ, {}, clear=True):
            import importlib
            import dockflare.settings as settings
            importlib.reload(settings)
            assert settings.LABEL_PREFIX == "dockflare."

    def test_external_cloudflared_default(self):
        """USE_EXTERNAL_CLOUDFLARED should be False by default."""
        with patch.dict(os.environ, {}, clear=True):
            import importlib
            import dockflare.settings as settings
            importlib.reload(settings)
            assert settings.USE_EXTERNAL_CLOUDFLARED is False

    def test_state_file_path_default(self):
        """STATE_FILE_PATH should have a sensible default."""
        with patch.dict(os.environ, {}, clear=True):
            import importlib
            import dockflare.settings as settings
            importlib.reload(settings)
            assert settings.STATE_FILE_PATH == "/app/data/state.json"

    def test_redis_db_index_default(self):
        """REDIS_DB_INDEX should default to 0."""
        with patch.dict(os.environ, {}, clear=True):
            import importlib
            import dockflare.settings as settings
            importlib.reload(settings)
            assert settings.REDIS_DB_INDEX == 0

    def test_cleanup_interval_default(self):
        """CLEANUP_INTERVAL_SECONDS should default to 60."""
        with patch.dict(os.environ, {}, clear=True):
            import importlib
            import dockflare.settings as settings
            importlib.reload(settings)
            assert settings.CLEANUP_INTERVAL_SECONDS == 60

    def test_agent_heartbeat_timeout_default(self):
        """AGENT_HEARTBEAT_TIMEOUT should default to 60."""
        with patch.dict(os.environ, {}, clear=True):
            import importlib
            import dockflare.settings as settings
            importlib.reload(settings)
            assert settings.AGENT_HEARTBEAT_TIMEOUT == 60


class TestBuildCloudflaredContainerName:
    """Tests for build_cloudflared_container_name function."""

    def test_basic_name(self):
        """Should prefix with cloudflared- and lowercase."""
        from dockflare.settings import build_cloudflared_container_name
        result = build_cloudflared_container_name("MyTunnel")
        assert result == "cloudflared-mytunnel"

    def test_replaces_spaces_with_dashes(self):
        """Should replace spaces with dashes."""
        from dockflare.settings import build_cloudflared_container_name
        result = build_cloudflared_container_name("my tunnel name")
        assert result == "cloudflared-my-tunnel-name"

    def test_replaces_underscores_with_dashes(self):
        """Should replace underscores with dashes."""
        from dockflare.settings import build_cloudflared_container_name
        result = build_cloudflared_container_name("my_tunnel_name")
        assert result == "cloudflared-my-tunnel-name"


class TestSettingsImport:
    """Tests for settings module import."""

    def test_module_imports_without_errors(self):
        """Settings module should import without errors."""
        import dockflare.settings
        assert dockflare.settings is not None

    def test_cf_headers_structure(self):
        """CF_HEADERS should have proper structure."""
        from dockflare.settings import CF_HEADERS
        assert isinstance(CF_HEADERS, dict)
        assert "Content-Type" in CF_HEADERS
        assert CF_HEADERS["Content-Type"] == "application/json"
