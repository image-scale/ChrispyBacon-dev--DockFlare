"""
Backup and restore functionality.

Provides encrypted backup and restore for configuration, state, and rule data.
"""

import base64
import gzip
import hashlib
import json
import logging
import os
import secrets
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from . import settings


@dataclass
class BackupMetadata:
    """Metadata for a backup file."""

    version: str
    created_at: str
    app_version: str
    encrypted: bool
    compressed: bool
    rules_count: int = 0
    access_groups_count: int = 0
    agents_count: int = 0
    checksum: str = ""


class BackupManager:
    """
    Manager for creating and restoring backups.

    Supports encryption with password-derived keys and optional compression.
    """

    BACKUP_VERSION = "1.0"
    MAGIC_HEADER = b"DOCKFLARE_BACKUP_V1"

    def __init__(
        self,
        state_manager=None,
        default_password: str = None,
        salt: bytes = None,
    ):
        """
        Initialize the backup manager.

        Args:
            state_manager: State manager to backup/restore
            default_password: Default encryption password
            salt: Salt for key derivation (random if not provided)
        """
        self._state = state_manager
        self._default_password = default_password
        self._salt = salt or secrets.token_bytes(16)

    @property
    def state_manager(self):
        """Get state manager, using default if not set."""
        if self._state is None:
            from .state import get_state
            self._state = get_state()
        return self._state

    def _derive_key(self, password: str, salt: bytes) -> bytes:
        """Derive an encryption key from password using PBKDF2."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode()))

    def create_backup(
        self,
        password: str = None,
        compress: bool = True,
        include_agents: bool = True,
    ) -> Tuple[bytes, BackupMetadata]:
        """
        Create a backup of the current state.

        Args:
            password: Encryption password (uses default if not provided)
            compress: Whether to compress the backup
            include_agents: Whether to include agent data

        Returns:
            Tuple of (backup bytes, metadata)
        """
        password = password or self._default_password

        rules = self.state_manager.list_rules()
        access_groups = self.state_manager.list_access_groups()
        agents = self.state_manager.list_agents() if include_agents else {}

        backup_data = {
            "rules": rules,
            "access_groups": access_groups,
            "agents": agents,
        }

        json_data = json.dumps(backup_data, indent=2, default=str)
        data_bytes = json_data.encode("utf-8")

        checksum = hashlib.sha256(data_bytes).hexdigest()

        if compress:
            data_bytes = gzip.compress(data_bytes)

        metadata = BackupMetadata(
            version=self.BACKUP_VERSION,
            created_at=datetime.now(timezone.utc).isoformat(),
            app_version=getattr(settings, "APP_VERSION", "1.0.0"),
            encrypted=bool(password),
            compressed=compress,
            rules_count=len(rules),
            access_groups_count=len(access_groups),
            agents_count=len(agents),
            checksum=checksum,
        )

        if password:
            salt = secrets.token_bytes(16)
            key = self._derive_key(password, salt)
            fernet = Fernet(key)
            data_bytes = salt + fernet.encrypt(data_bytes)

        header = self.MAGIC_HEADER + b"\x00"
        metadata_json = json.dumps(asdict(metadata)).encode("utf-8")
        metadata_length = len(metadata_json).to_bytes(4, "big")

        backup_bytes = header + metadata_length + metadata_json + data_bytes

        return backup_bytes, metadata

    def restore_backup(
        self,
        backup_data: bytes,
        password: str = None,
        merge: bool = False,
    ) -> Tuple[bool, BackupMetadata, str]:
        """
        Restore state from a backup.

        Args:
            backup_data: Backup bytes to restore
            password: Decryption password
            merge: Whether to merge with existing state (vs replace)

        Returns:
            Tuple of (success, metadata, message)
        """
        password = password or self._default_password

        try:
            if not backup_data.startswith(self.MAGIC_HEADER):
                return False, None, "Invalid backup format: missing header"

            header_end = len(self.MAGIC_HEADER) + 1
            metadata_length = int.from_bytes(backup_data[header_end:header_end + 4], "big")
            metadata_start = header_end + 4
            metadata_end = metadata_start + metadata_length

            metadata_json = backup_data[metadata_start:metadata_end].decode("utf-8")
            metadata_dict = json.loads(metadata_json)
            metadata = BackupMetadata(**metadata_dict)

            data_bytes = backup_data[metadata_end:]

            if metadata.encrypted:
                if not password:
                    return False, metadata, "Backup is encrypted but no password provided"

                salt = data_bytes[:16]
                encrypted_data = data_bytes[16:]

                key = self._derive_key(password, salt)
                fernet = Fernet(key)

                try:
                    data_bytes = fernet.decrypt(encrypted_data)
                except InvalidToken:
                    return False, metadata, "Invalid password or corrupted backup"

            if metadata.compressed:
                try:
                    data_bytes = gzip.decompress(data_bytes)
                except gzip.BadGzipFile:
                    return False, metadata, "Failed to decompress backup"

            checksum = hashlib.sha256(data_bytes).hexdigest()
            if metadata.checksum and checksum != metadata.checksum:
                return False, metadata, "Checksum mismatch: backup may be corrupted"

            backup_dict = json.loads(data_bytes.decode("utf-8"))

            if not merge:
                self.state_manager.clear_state()

            for rule_key, rule_data in backup_dict.get("rules", {}).items():
                self.state_manager.set_rule(rule_key, rule_data)

            for group_id, group_data in backup_dict.get("access_groups", {}).items():
                self.state_manager.set_access_group(group_id, group_data)

            for agent_id, agent_data in backup_dict.get("agents", {}).items():
                self.state_manager.set_agent(agent_id, agent_data)

            self.state_manager.save_state()

            mode = "merged with" if merge else "replaced"
            message = f"Backup restored ({mode} existing state): {metadata.rules_count} rules, {metadata.access_groups_count} access groups, {metadata.agents_count} agents"

            return True, metadata, message

        except json.JSONDecodeError as e:
            return False, None, f"Invalid backup data: {e}"
        except Exception as e:
            logging.exception("Error restoring backup")
            return False, None, f"Error restoring backup: {e}"

    def export_backup_to_file(
        self,
        file_path: str,
        password: str = None,
        compress: bool = True,
    ) -> Tuple[bool, str]:
        """
        Export backup to a file.

        Args:
            file_path: Path to write backup file
            password: Encryption password
            compress: Whether to compress

        Returns:
            Tuple of (success, message)
        """
        try:
            backup_bytes, metadata = self.create_backup(
                password=password,
                compress=compress,
            )

            dir_path = os.path.dirname(file_path)
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path)

            with open(file_path, "wb") as f:
                f.write(backup_bytes)

            size_kb = len(backup_bytes) / 1024
            return True, f"Backup exported to {file_path} ({size_kb:.1f} KB)"

        except IOError as e:
            return False, f"Failed to write backup file: {e}"
        except Exception as e:
            logging.exception("Error exporting backup")
            return False, f"Error exporting backup: {e}"

    def import_backup_from_file(
        self,
        file_path: str,
        password: str = None,
        merge: bool = False,
    ) -> Tuple[bool, str]:
        """
        Import backup from a file.

        Args:
            file_path: Path to backup file
            password: Decryption password
            merge: Whether to merge with existing state

        Returns:
            Tuple of (success, message)
        """
        try:
            if not os.path.exists(file_path):
                return False, f"Backup file not found: {file_path}"

            with open(file_path, "rb") as f:
                backup_bytes = f.read()

            success, metadata, message = self.restore_backup(
                backup_bytes,
                password=password,
                merge=merge,
            )

            return success, message

        except IOError as e:
            return False, f"Failed to read backup file: {e}"
        except Exception as e:
            logging.exception("Error importing backup")
            return False, f"Error importing backup: {e}"

    def verify_backup(
        self,
        backup_data: bytes,
        password: str = None,
    ) -> Tuple[bool, Optional[BackupMetadata], str]:
        """
        Verify a backup without restoring it.

        Args:
            backup_data: Backup bytes to verify
            password: Decryption password (if encrypted)

        Returns:
            Tuple of (valid, metadata, message)
        """
        password = password or self._default_password

        try:
            if not backup_data.startswith(self.MAGIC_HEADER):
                return False, None, "Invalid backup format"

            header_end = len(self.MAGIC_HEADER) + 1
            metadata_length = int.from_bytes(backup_data[header_end:header_end + 4], "big")
            metadata_start = header_end + 4
            metadata_end = metadata_start + metadata_length

            metadata_json = backup_data[metadata_start:metadata_end].decode("utf-8")
            metadata_dict = json.loads(metadata_json)
            metadata = BackupMetadata(**metadata_dict)

            data_bytes = backup_data[metadata_end:]

            if metadata.encrypted:
                if not password:
                    return True, metadata, "Backup is valid (encrypted, password required to verify contents)"

                salt = data_bytes[:16]
                encrypted_data = data_bytes[16:]
                key = self._derive_key(password, salt)
                fernet = Fernet(key)

                try:
                    data_bytes = fernet.decrypt(encrypted_data)
                except InvalidToken:
                    return False, metadata, "Invalid password"

            if metadata.compressed:
                data_bytes = gzip.decompress(data_bytes)

            checksum = hashlib.sha256(data_bytes).hexdigest()
            if metadata.checksum and checksum != metadata.checksum:
                return False, metadata, "Checksum mismatch"

            return True, metadata, f"Backup is valid: {metadata.rules_count} rules, {metadata.access_groups_count} access groups"

        except Exception as e:
            return False, None, f"Error verifying backup: {e}"


_backup_manager: Optional[BackupManager] = None


def get_backup_manager() -> BackupManager:
    """Get or create the default backup manager."""
    global _backup_manager
    if _backup_manager is None:
        _backup_manager = BackupManager()
    return _backup_manager


def create_backup(
    password: str = None,
    compress: bool = True,
) -> Tuple[bytes, BackupMetadata]:
    """Convenience function to create a backup."""
    return get_backup_manager().create_backup(password=password, compress=compress)


def restore_backup(
    backup_data: bytes,
    password: str = None,
    merge: bool = False,
) -> Tuple[bool, Optional[BackupMetadata], str]:
    """Convenience function to restore a backup."""
    return get_backup_manager().restore_backup(backup_data, password=password, merge=merge)


def export_backup(
    file_path: str,
    password: str = None,
) -> Tuple[bool, str]:
    """Convenience function to export backup to file."""
    return get_backup_manager().export_backup_to_file(file_path, password=password)


def import_backup(
    file_path: str,
    password: str = None,
    merge: bool = False,
) -> Tuple[bool, str]:
    """Convenience function to import backup from file."""
    return get_backup_manager().import_backup_from_file(file_path, password=password, merge=merge)
