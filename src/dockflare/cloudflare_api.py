"""
Cloudflare API client for making authenticated requests.

Handles authentication, request/response processing, error handling,
zone lookups with caching, and retry logic.
"""

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from . import settings


class CloudflareAPIError(Exception):
    """Exception raised for Cloudflare API errors."""

    def __init__(self, message: str, error_code: int = None, response: requests.Response = None):
        super().__init__(message)
        self.error_code = error_code
        self.response = response


class CloudflareClient:
    """Client for interacting with the Cloudflare API."""

    def __init__(
        self,
        api_token: str = None,
        account_id: str = None,
        base_url: str = None,
    ):
        """
        Initialize the Cloudflare API client.

        Args:
            api_token: Cloudflare API token (defaults to settings.CF_API_TOKEN)
            account_id: Cloudflare account ID (defaults to settings.CF_ACCOUNT_ID)
            base_url: API base URL (defaults to settings.CF_API_BASE_URL)
        """
        self.api_token = api_token or settings.CF_API_TOKEN
        self.account_id = account_id or settings.CF_ACCOUNT_ID
        self.base_url = base_url or settings.CF_API_BASE_URL

        self._zone_cache: Dict[str, Tuple[str, float]] = {}
        self._zone_details_cache: Dict[str, Dict] = {}
        self._cache_lock = threading.Lock()
        self._cache_ttl = settings.ACCOUNT_EMAIL_CACHE_TTL

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication."""
        headers = dict(settings.CF_HEADERS)
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    def request(
        self,
        method: str,
        endpoint: str,
        json_data: Dict = None,
        params: Dict = None,
        log_errors: bool = True,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        Make an authenticated request to the Cloudflare API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: API endpoint path (starting with /)
            json_data: Optional JSON payload for request body
            params: Optional query parameters
            log_errors: Whether to log errors (default True)
            timeout: Request timeout in seconds

        Returns:
            Parsed JSON response dict with 'success' and 'result' keys

        Raises:
            CloudflareAPIError: On API errors or unsuccessful responses
        """
        url = f"{self.base_url}{endpoint}"
        logging.info(f"CF API Request: {method} {url} Params: {params}")

        if json_data:
            try:
                log_data = json.dumps(json_data)
                logging.debug(f"CF API Request Data: {log_data[:500]}")
            except TypeError:
                logging.debug(f"CF API Request Data: {str(json_data)[:500]}")

        try:
            response = requests.request(
                method,
                url,
                headers=self._get_headers(),
                json=json_data,
                params=params,
                timeout=timeout,
            )
            response.raise_for_status()
            logging.info(f"CF API Response Status: {response.status_code}")

            if response.status_code == 204 or not response.content:
                return {"success": True, "result": None}

            try:
                response_data = response.json()
                logging.debug(f"CF API Response Body (first 500 chars): {str(response_data)[:500]}")

                if isinstance(response_data, dict) and "success" in response_data:
                    if response_data["success"]:
                        return response_data
                    else:
                        cf_errors = response_data.get("errors", [])
                        error_code = None
                        if cf_errors and isinstance(cf_errors, list) and cf_errors:
                            error_msg = cf_errors[0].get("message", "Unknown error")
                            error_code = cf_errors[0].get("code")
                        else:
                            error_msg = f"API reported failure: {response_data}"

                        if log_errors:
                            logging.error(f"CF API Failed ({method} {url}): {error_msg}")

                        raise CloudflareAPIError(error_msg, error_code, response)
                else:
                    logging.warning(
                        f"CF API response missing 'success' field. Status: {response.status_code}"
                    )
                    raise CloudflareAPIError(
                        f"Unexpected response format. Status: {response.status_code}",
                        response=response,
                    )

            except json.JSONDecodeError:
                logging.error(f"CF API response not valid JSON. Status: {response.status_code}")
                raise CloudflareAPIError(
                    f"Invalid JSON response. Status: {response.status_code}",
                    response=response,
                )

        except requests.exceptions.RequestException as e:
            error_msg = f"CF API Request Failed: {method} {url}. Error: {e}"

            if hasattr(e, "response") and e.response is not None:
                try:
                    error_data = e.response.json()
                    cf_errors = error_data.get("errors", [])
                    if cf_errors and isinstance(cf_errors, list) and cf_errors:
                        error_msg = cf_errors[0].get("message", str(e))
                        if log_errors:
                            logging.error(f"CF API Error: {error_msg}")
                        raise CloudflareAPIError(
                            error_msg,
                            error_code=cf_errors[0].get("code"),
                            response=e.response,
                        )
                except (ValueError, json.JSONDecodeError):
                    pass

            if log_errors:
                logging.error(error_msg)
            raise CloudflareAPIError(error_msg)

    def get_zone_id(self, zone_name: str) -> Optional[str]:
        """
        Get zone ID by zone name with caching.

        Args:
            zone_name: The domain name (e.g., "example.com")

        Returns:
            Zone ID string or None if not found
        """
        if not zone_name:
            logging.warning("get_zone_id called with empty zone_name")
            return None

        current_time = time.time()

        with self._cache_lock:
            if zone_name in self._zone_cache:
                zone_id, timestamp = self._zone_cache[zone_name]
                if current_time - timestamp < self._cache_ttl:
                    logging.debug(f"Zone ID for '{zone_name}' found in cache: {zone_id}")
                    return zone_id
                else:
                    logging.debug(f"Zone ID cache for '{zone_name}' expired, refreshing")

        logging.info(f"Looking up zone ID for '{zone_name}' via API...")

        try:
            response_data = self.request(
                "GET",
                "/zones",
                params={
                    "name": zone_name,
                    "status": "active",
                    "account.id": self.account_id,
                },
            )

            results = response_data.get("result", [])

            if results and isinstance(results, list) and len(results) == 1:
                zone = results[0]
                zone_id = zone.get("id")
                zone_actual_name = zone.get("name")

                if zone_id and zone_actual_name == zone_name:
                    logging.info(f"Found zone ID for '{zone_name}': {zone_id}")
                    with self._cache_lock:
                        self._zone_cache[zone_name] = (zone_id, current_time)
                    return zone_id
                else:
                    logging.error(f"Zone name mismatch: expected '{zone_name}', got '{zone_actual_name}'")
                    return None

            elif results and len(results) > 1:
                logging.error(f"Multiple zones ({len(results)}) found for '{zone_name}'")
                return None
            else:
                logging.warning(f"No active zone found for '{zone_name}'")
                return None

        except CloudflareAPIError as e:
            logging.error(f"API error looking up zone '{zone_name}': {e}")
            return None
        except Exception as e:
            logging.error(f"Unexpected error looking up zone '{zone_name}': {e}")
            return None

    def get_zone_details(self, zone_id: str) -> Optional[Dict]:
        """
        Get zone details by zone ID with caching.

        Args:
            zone_id: The zone ID

        Returns:
            Zone details dict or None if not found
        """
        if not zone_id:
            logging.warning("get_zone_details called with empty zone_id")
            return None

        with self._cache_lock:
            if zone_id in self._zone_details_cache:
                logging.debug(f"Zone details for ID '{zone_id}' found in cache")
                return self._zone_details_cache[zone_id]

        logging.info(f"Looking up zone details for ID '{zone_id}' via API...")

        try:
            response_data = self.request("GET", f"/zones/{zone_id}")
            zone_data = response_data.get("result")

            if zone_data and isinstance(zone_data, dict) and zone_data.get("name"):
                logging.info(f"Found zone details for ID '{zone_id}': {zone_data['name']}")
                with self._cache_lock:
                    self._zone_details_cache[zone_id] = zone_data
                return zone_data
            else:
                logging.error(f"Zone details response malformed for ID '{zone_id}'")
                return None

        except CloudflareAPIError as e:
            logging.error(f"API error looking up zone ID '{zone_id}': {e}")
            return None

    def list_zones(self, per_page: int = 50) -> List[Dict]:
        """
        List all active zones in the account.

        Args:
            per_page: Number of zones per page (max 50)

        Returns:
            List of zone dictionaries with 'id' and 'name' keys
        """
        zones = []
        page = 1

        while True:
            try:
                response_data = self.request(
                    "GET",
                    "/zones",
                    params={
                        "status": "active",
                        "account.id": self.account_id,
                        "page": page,
                        "per_page": min(per_page, 50),
                    },
                )

                results = response_data.get("result", [])
                if not results:
                    break

                zones.extend(results)

                result_info = response_data.get("result_info", {})
                total_pages = result_info.get("total_pages", 1)

                if page >= total_pages:
                    break
                page += 1

            except CloudflareAPIError as e:
                logging.error(f"API error listing zones: {e}")
                break

        return zones

    def clear_zone_cache(self, zone_name: str = None, zone_id: str = None):
        """Clear zone cache entries."""
        with self._cache_lock:
            if zone_name:
                self._zone_cache.pop(zone_name, None)
            if zone_id:
                self._zone_details_cache.pop(zone_id, None)
            if not zone_name and not zone_id:
                self._zone_cache.clear()
                self._zone_details_cache.clear()


# Module-level convenience functions using default client
_default_client: CloudflareClient = None


def get_client() -> CloudflareClient:
    """Get or create the default CloudflareClient instance."""
    global _default_client
    if _default_client is None:
        _default_client = CloudflareClient()
    return _default_client


def cf_request(
    method: str,
    endpoint: str,
    json_data: Dict = None,
    params: Dict = None,
    log_errors: bool = True,
) -> Dict[str, Any]:
    """Make a Cloudflare API request using the default client."""
    return get_client().request(method, endpoint, json_data, params, log_errors)


def get_zone_id(zone_name: str) -> Optional[str]:
    """Get zone ID by name using the default client."""
    return get_client().get_zone_id(zone_name)


def list_zones() -> List[Dict]:
    """List all zones using the default client."""
    return get_client().list_zones()
