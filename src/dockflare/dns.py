"""
DNS record management for Cloudflare Tunnel endpoints.

Handles creating, finding, updating, and deleting CNAME records
that point to tunnel endpoints.
"""

import logging
import threading
from typing import Optional, Tuple

from .cloudflare_api import CloudflareClient, CloudflareAPIError
from . import settings


class DNSManager:
    """Manager for Cloudflare DNS record operations."""

    def __init__(self, client: CloudflareClient = None, max_concurrent: int = None):
        """
        Initialize the DNS manager.

        Args:
            client: CloudflareClient instance (creates one if not provided)
            max_concurrent: Maximum concurrent DNS operations
        """
        self.client = client or CloudflareClient()
        self._semaphore = threading.Semaphore(
            max_concurrent or settings.MAX_CONCURRENT_DNS_OPS
        )

    def _get_tunnel_content(self, tunnel_id: str) -> str:
        """Get the DNS content value for a tunnel endpoint."""
        return f"{tunnel_id}.cfargotunnel.com"

    def create_record(
        self,
        zone_id: str,
        hostname: str,
        tunnel_id: str,
        proxied: bool = True,
    ) -> Optional[str]:
        """
        Create a CNAME DNS record pointing to a tunnel.

        If a record already exists and points to the correct tunnel, returns its ID.
        If a record exists but points to a different tunnel, updates it.

        Args:
            zone_id: Cloudflare zone ID
            hostname: Full hostname (e.g., "app.example.com")
            tunnel_id: Tunnel ID to point to
            proxied: Whether to proxy through Cloudflare (default True)

        Returns:
            Record ID on success, None on error
        """
        if not zone_id or not hostname or not tunnel_id:
            logging.error("create_record: Missing required arguments")
            return None

        acquired = self._semaphore.acquire(timeout=30)
        if not acquired:
            logging.error(f"DNS semaphore timeout for {hostname}")
            return None

        try:
            existing_id, correct_target = self.find_record(zone_id, hostname, tunnel_id)

            if existing_id:
                if correct_target:
                    logging.info(f"DNS record for {hostname} already exists with correct tunnel")
                    return existing_id
                else:
                    logging.info(f"DNS record for {hostname} exists but wrong tunnel, updating")
                    return self.update_record(zone_id, existing_id, hostname, tunnel_id, proxied)

            content = self._get_tunnel_content(tunnel_id)
            payload = {
                "type": "CNAME",
                "name": hostname,
                "content": content,
                "ttl": 1,
                "proxied": proxied,
            }

            try:
                logging.info(f"Creating DNS CNAME: {hostname} -> {content}")
                response = self.client.request(
                    "POST",
                    f"/zones/{zone_id}/dns_records",
                    json_data=payload,
                )

                record_id = response.get("result", {}).get("id")
                if record_id:
                    logging.info(f"Created DNS record {record_id} for {hostname}")
                    return record_id
                else:
                    logging.error(f"DNS creation succeeded but no ID returned")
                    return None

            except CloudflareAPIError as e:
                if e.error_code == 81057 or (
                    e.response and "already exists" in str(e.response.text).lower()
                ):
                    logging.warning(f"DNS record for {hostname} already exists, fetching ID")
                    existing_id, _ = self.find_record(zone_id, hostname, tunnel_id)
                    return existing_id
                logging.error(f"API error creating DNS record: {e}")
                return None

        finally:
            self._semaphore.release()

    def find_record(
        self,
        zone_id: str,
        hostname: str,
        tunnel_id: str,
    ) -> Tuple[Optional[str], bool]:
        """
        Find an existing CNAME record for a hostname.

        Args:
            zone_id: Cloudflare zone ID
            hostname: Hostname to search for
            tunnel_id: Expected tunnel ID

        Returns:
            Tuple of (record_id, correct_target) where correct_target indicates
            if the record points to the expected tunnel. Returns (None, False)
            if no record found.
        """
        if not zone_id or not hostname or not tunnel_id:
            logging.error("find_record: Missing required arguments")
            return None, False

        expected_content = self._get_tunnel_content(tunnel_id)

        try:
            response = self.client.request(
                "GET",
                f"/zones/{zone_id}/dns_records",
                params={"type": "CNAME", "name": hostname},
            )

            results = response.get("result", [])
            if not results:
                logging.debug(f"No DNS record found for {hostname}")
                return None, False

            for record in results:
                record_id = record.get("id")
                if not record_id:
                    continue

                content = record.get("content", "")
                if content.lower() == expected_content.lower():
                    logging.info(f"Found exact DNS match for {hostname}: {record_id}")
                    return record_id, True

            first_record = results[0]
            record_id = first_record.get("id")
            if record_id:
                logging.info(f"Found DNS record for {hostname} but wrong target: {record_id}")
                return record_id, False

            return None, False

        except CloudflareAPIError as e:
            logging.error(f"API error finding DNS record: {e}")
            return None, False

    def update_record(
        self,
        zone_id: str,
        record_id: str,
        hostname: str,
        tunnel_id: str,
        proxied: bool = True,
    ) -> Optional[str]:
        """
        Update an existing DNS record to point to a tunnel.

        Args:
            zone_id: Cloudflare zone ID
            record_id: Existing record ID to update
            hostname: Hostname for the record
            tunnel_id: Tunnel ID to point to
            proxied: Whether to proxy through Cloudflare

        Returns:
            Record ID on success, None on error
        """
        if not zone_id or not record_id or not hostname or not tunnel_id:
            logging.error("update_record: Missing required arguments")
            return None

        content = self._get_tunnel_content(tunnel_id)
        payload = {
            "type": "CNAME",
            "name": hostname,
            "content": content,
            "ttl": 1,
            "proxied": proxied,
        }

        try:
            logging.info(f"Updating DNS record {record_id}: {hostname} -> {content}")
            response = self.client.request(
                "PUT",
                f"/zones/{zone_id}/dns_records/{record_id}",
                json_data=payload,
            )

            updated_id = response.get("result", {}).get("id")
            if updated_id:
                logging.info(f"Updated DNS record {updated_id} for {hostname}")
                return updated_id
            else:
                logging.warning(f"DNS update succeeded but no ID returned, using original")
                return record_id

        except CloudflareAPIError as e:
            logging.error(f"API error updating DNS record: {e}")
            return None

    def delete_record(self, zone_id: str, record_id: str) -> bool:
        """
        Delete a DNS record.

        Args:
            zone_id: Cloudflare zone ID
            record_id: Record ID to delete

        Returns:
            True on success, False on error
        """
        if not zone_id or not record_id:
            logging.error("delete_record: Missing required arguments")
            return False

        try:
            logging.info(f"Deleting DNS record {record_id} from zone {zone_id}")
            self.client.request(
                "DELETE",
                f"/zones/{zone_id}/dns_records/{record_id}",
            )
            logging.info(f"Deleted DNS record {record_id}")
            return True

        except CloudflareAPIError as e:
            logging.error(f"API error deleting DNS record: {e}")
            return False

    def list_records(
        self,
        zone_id: str,
        record_type: str = "CNAME",
        name: str = None,
    ) -> list:
        """
        List DNS records in a zone.

        Args:
            zone_id: Cloudflare zone ID
            record_type: DNS record type filter (default CNAME)
            name: Optional hostname filter

        Returns:
            List of record dicts
        """
        params = {"type": record_type}
        if name:
            params["name"] = name

        try:
            response = self.client.request(
                "GET",
                f"/zones/{zone_id}/dns_records",
                params=params,
            )
            return response.get("result", [])

        except CloudflareAPIError as e:
            logging.error(f"API error listing DNS records: {e}")
            return []


# Module-level convenience instance
_default_manager: DNSManager = None


def get_manager() -> DNSManager:
    """Get or create the default DNSManager instance."""
    global _default_manager
    if _default_manager is None:
        _default_manager = DNSManager()
    return _default_manager


def create_dns_record(zone_id: str, hostname: str, tunnel_id: str) -> Optional[str]:
    """Create a DNS record pointing to a tunnel."""
    return get_manager().create_record(zone_id, hostname, tunnel_id)


def find_dns_record(zone_id: str, hostname: str, tunnel_id: str) -> Tuple[Optional[str], bool]:
    """Find an existing DNS record for a hostname."""
    return get_manager().find_record(zone_id, hostname, tunnel_id)


def update_dns_record(
    zone_id: str, record_id: str, hostname: str, tunnel_id: str
) -> Optional[str]:
    """Update a DNS record to point to a tunnel."""
    return get_manager().update_record(zone_id, record_id, hostname, tunnel_id)


def delete_dns_record(zone_id: str, record_id: str) -> bool:
    """Delete a DNS record."""
    return get_manager().delete_record(zone_id, record_id)
