"""Tests for backup and restore functionality."""

import gzip
import json
import os
import tempfile
import pytest
from unittest.mock import Mock, patch

from dockflare.backup import (
    BackupManager,
    BackupMetadata,
    get_backup_manager,
    create_backup,
    restore_backup,
    export_backup,
    import_backup,
)


class TestBackupMetadata:
    """Tests for BackupMetadata class."""

    def test_creates_metadata(self):
        """Should create metadata with all fields."""
        metadata = BackupMetadata(
            version="1.0",
            created_at="2025-01-01T00:00:00Z",
            app_version="1.0.0",
            encrypted=True,
            compressed=True,
            rules_count=5,
            access_groups_count=2,
            agents_count=1,
        )

        assert metadata.version == "1.0"
        assert metadata.rules_count == 5


class TestBackupManager:
    """Tests for BackupManager class."""

    @pytest.fixture
    def mock_state(self):
        """Create a mock state manager."""
        state = Mock()
        state.list_rules.return_value = {
            "app.example.com|": {
                "hostname": "app.example.com",
                "service": "http://app:80",
            }
        }
        state.list_access_groups.return_value = {
            "admin": {"display_name": "Admins"}
        }
        state.list_agents.return_value = {
            "agent-1": {"name": "Server 1"}
        }
        return state

    @pytest.fixture
    def manager(self, mock_state):
        """Create a backup manager with mock state."""
        return BackupManager(state_manager=mock_state)


class TestBackupManagerCreate:
    """Tests for creating backups."""

    @pytest.fixture
    def mock_state(self):
        state = Mock()
        state.list_rules.return_value = {"app|": {"hostname": "app"}}
        state.list_access_groups.return_value = {}
        state.list_agents.return_value = {}
        return state

    @pytest.fixture
    def manager(self, mock_state):
        return BackupManager(state_manager=mock_state)

    def test_creates_unencrypted_backup(self, manager):
        """Should create unencrypted backup."""
        backup_bytes, metadata = manager.create_backup(compress=False)

        assert backup_bytes.startswith(BackupManager.MAGIC_HEADER)
        assert metadata.encrypted is False
        assert metadata.rules_count == 1

    def test_creates_compressed_backup(self, manager):
        """Should create compressed backup."""
        backup_bytes, metadata = manager.create_backup(compress=True)

        assert metadata.compressed is True

    def test_creates_encrypted_backup(self, manager):
        """Should create encrypted backup with password."""
        backup_bytes, metadata = manager.create_backup(
            password="secret123",
            compress=False,
        )

        assert metadata.encrypted is True

    def test_excludes_agents_when_requested(self, manager, mock_state):
        """Should exclude agents when include_agents=False."""
        mock_state.list_agents.return_value = {"agent-1": {"name": "Test"}}

        backup_bytes, metadata = manager.create_backup(include_agents=False)

        assert metadata.agents_count == 0

    def test_includes_checksum(self, manager):
        """Should include checksum in metadata."""
        backup_bytes, metadata = manager.create_backup()

        assert metadata.checksum != ""
        assert len(metadata.checksum) == 64


class TestBackupManagerRestore:
    """Tests for restoring backups."""

    @pytest.fixture
    def mock_state(self):
        state = Mock()
        state.list_rules.return_value = {"app|": {"hostname": "app"}}
        state.list_access_groups.return_value = {}
        state.list_agents.return_value = {}
        state.set_rule.return_value = None
        state.set_access_group.return_value = None
        state.set_agent.return_value = None
        state.save_state.return_value = True
        state.clear_state.return_value = None
        return state

    @pytest.fixture
    def manager(self, mock_state):
        return BackupManager(state_manager=mock_state)

    def test_restores_unencrypted_backup(self, manager, mock_state):
        """Should restore unencrypted backup."""
        backup_bytes, _ = manager.create_backup(compress=False)

        success, metadata, message = manager.restore_backup(backup_bytes)

        assert success is True
        assert "restored" in message.lower()
        mock_state.set_rule.assert_called()

    def test_restores_compressed_backup(self, manager, mock_state):
        """Should restore compressed backup."""
        backup_bytes, _ = manager.create_backup(compress=True)

        success, metadata, message = manager.restore_backup(backup_bytes)

        assert success is True

    def test_restores_encrypted_backup(self, manager, mock_state):
        """Should restore encrypted backup with correct password."""
        backup_bytes, _ = manager.create_backup(password="secret123")

        success, metadata, message = manager.restore_backup(
            backup_bytes,
            password="secret123",
        )

        assert success is True

    def test_fails_with_wrong_password(self, manager):
        """Should fail with wrong password."""
        backup_bytes, _ = manager.create_backup(password="secret123")

        success, metadata, message = manager.restore_backup(
            backup_bytes,
            password="wrongpassword",
        )

        assert success is False
        assert "invalid password" in message.lower()

    def test_fails_without_password_for_encrypted(self, manager):
        """Should fail when password not provided for encrypted backup."""
        backup_bytes, _ = manager.create_backup(password="secret123")

        success, metadata, message = manager.restore_backup(backup_bytes)

        assert success is False
        assert "encrypted" in message.lower()

    def test_merges_with_existing_state(self, manager, mock_state):
        """Should merge when merge=True."""
        backup_bytes, _ = manager.create_backup()

        success, metadata, message = manager.restore_backup(
            backup_bytes,
            merge=True,
        )

        assert success is True
        assert "merged" in message.lower()
        mock_state.clear_state.assert_not_called()

    def test_replaces_existing_state_by_default(self, manager, mock_state):
        """Should replace state when merge=False."""
        backup_bytes, _ = manager.create_backup()

        success, metadata, message = manager.restore_backup(backup_bytes)

        assert success is True
        assert "replaced" in message.lower()
        mock_state.clear_state.assert_called()

    def test_rejects_invalid_format(self, manager):
        """Should reject invalid backup format."""
        invalid_data = b"not a valid backup"

        success, metadata, message = manager.restore_backup(invalid_data)

        assert success is False
        assert "invalid" in message.lower()


class TestBackupManagerFile:
    """Tests for file operations."""

    @pytest.fixture
    def mock_state(self):
        state = Mock()
        state.list_rules.return_value = {"app|": {"hostname": "app"}}
        state.list_access_groups.return_value = {}
        state.list_agents.return_value = {}
        state.set_rule.return_value = None
        state.save_state.return_value = True
        state.clear_state.return_value = None
        return state

    @pytest.fixture
    def manager(self, mock_state):
        return BackupManager(state_manager=mock_state)

    def test_exports_to_file(self, manager):
        """Should export backup to file."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bak") as f:
            file_path = f.name

        try:
            success, message = manager.export_backup_to_file(file_path)

            assert success is True
            assert os.path.exists(file_path)
            assert os.path.getsize(file_path) > 0
        finally:
            if os.path.exists(file_path):
                os.unlink(file_path)

    def test_imports_from_file(self, manager, mock_state):
        """Should import backup from file."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bak") as f:
            file_path = f.name

        try:
            manager.export_backup_to_file(file_path)
            success, message = manager.import_backup_from_file(file_path)

            assert success is True
            assert "restored" in message.lower()
        finally:
            if os.path.exists(file_path):
                os.unlink(file_path)

    def test_handles_missing_file(self, manager):
        """Should handle missing file gracefully."""
        success, message = manager.import_backup_from_file("/nonexistent/path.bak")

        assert success is False
        assert "not found" in message.lower()

    def test_creates_directory_if_needed(self, manager):
        """Should create directory for backup file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "subdir", "backup.bak")
            success, message = manager.export_backup_to_file(file_path)

            assert success is True
            assert os.path.exists(file_path)


class TestBackupManagerVerify:
    """Tests for backup verification."""

    @pytest.fixture
    def mock_state(self):
        state = Mock()
        state.list_rules.return_value = {"app|": {"hostname": "app"}}
        state.list_access_groups.return_value = {}
        state.list_agents.return_value = {}
        return state

    @pytest.fixture
    def manager(self, mock_state):
        return BackupManager(state_manager=mock_state)

    def test_verifies_valid_backup(self, manager):
        """Should verify valid backup."""
        backup_bytes, _ = manager.create_backup()

        valid, metadata, message = manager.verify_backup(backup_bytes)

        assert valid is True
        assert metadata is not None

    def test_verifies_encrypted_without_password(self, manager):
        """Should indicate encrypted backup needs password."""
        backup_bytes, _ = manager.create_backup(password="secret")

        valid, metadata, message = manager.verify_backup(backup_bytes)

        assert valid is True
        assert "password required" in message.lower()

    def test_verifies_encrypted_with_password(self, manager):
        """Should verify encrypted backup with correct password."""
        backup_bytes, _ = manager.create_backup(password="secret")

        valid, metadata, message = manager.verify_backup(
            backup_bytes,
            password="secret",
        )

        assert valid is True
        assert metadata.encrypted is True

    def test_rejects_invalid_backup(self, manager):
        """Should reject invalid backup."""
        valid, metadata, message = manager.verify_backup(b"invalid")

        assert valid is False


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    @pytest.fixture(autouse=True)
    def reset_manager(self):
        """Reset the global manager."""
        import dockflare.backup as backup_module
        backup_module._backup_manager = None
        yield
        backup_module._backup_manager = None

    @patch("dockflare.backup.get_backup_manager")
    def test_create_backup_uses_manager(self, mock_get_manager):
        """create_backup should use default manager."""
        mock_manager = Mock()
        mock_manager.create_backup.return_value = (b"data", Mock())
        mock_get_manager.return_value = mock_manager

        create_backup(password="test")

        mock_manager.create_backup.assert_called_once()

    @patch("dockflare.backup.get_backup_manager")
    def test_restore_backup_uses_manager(self, mock_get_manager):
        """restore_backup should use default manager."""
        mock_manager = Mock()
        mock_manager.restore_backup.return_value = (True, Mock(), "OK")
        mock_get_manager.return_value = mock_manager

        restore_backup(b"data")

        mock_manager.restore_backup.assert_called_once()

    @patch("dockflare.backup.get_backup_manager")
    def test_export_backup_uses_manager(self, mock_get_manager):
        """export_backup should use default manager."""
        mock_manager = Mock()
        mock_manager.export_backup_to_file.return_value = (True, "OK")
        mock_get_manager.return_value = mock_manager

        export_backup("/path/to/file.bak")

        mock_manager.export_backup_to_file.assert_called_once()

    @patch("dockflare.backup.get_backup_manager")
    def test_import_backup_uses_manager(self, mock_get_manager):
        """import_backup should use default manager."""
        mock_manager = Mock()
        mock_manager.import_backup_from_file.return_value = (True, "OK")
        mock_get_manager.return_value = mock_manager

        import_backup("/path/to/file.bak")

        mock_manager.import_backup_from_file.assert_called_once()

    @patch("dockflare.backup._backup_manager", None)
    def test_get_backup_manager_creates_singleton(self):
        """get_backup_manager should create singleton."""
        import dockflare.backup as backup_module
        backup_module._backup_manager = None

        manager1 = get_backup_manager()
        manager2 = get_backup_manager()

        assert manager1 is manager2
