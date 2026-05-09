"""
Cloudflare Access application and policy management.

Handles creating, finding, updating, and deleting Access applications
that protect tunnel endpoints.
"""

import logging
from typing import Any, Dict, List, Optional

from .cloudflare_api import CloudflareClient, CloudflareAPIError
from . import settings


class AccessManager:
    """Manager for Cloudflare Access operations."""

    def __init__(self, client: CloudflareClient = None, account_id: str = None):
        """
        Initialize the Access manager.

        Args:
            client: CloudflareClient instance (creates one if not provided)
            account_id: Cloudflare account ID (defaults to settings)
        """
        self.client = client or CloudflareClient()
        self.account_id = account_id or settings.CF_ACCOUNT_ID

    def find_application(self, domain: str) -> Optional[Dict]:
        """
        Find an Access application by domain.

        Args:
            domain: Application domain to search for

        Returns:
            Application dict or None if not found
        """
        logging.info(f"Finding Access application for domain '{domain}'")

        try:
            response = self.client.request(
                "GET",
                f"/accounts/{self.account_id}/access/apps",
                params={"domain": domain},
            )

            apps = response.get("result", [])
            for app in apps:
                if app.get("domain") == domain:
                    logging.info(f"Found Access application {app.get('id')} for '{domain}'")
                    return app

            response = self.client.request(
                "GET",
                f"/accounts/{self.account_id}/access/apps",
                params={"per_page": 100},
            )

            apps = response.get("result", [])
            for app in apps:
                if app.get("domain") == domain:
                    return app
                if domain in app.get("self_hosted_domains", []):
                    logging.info(f"Found Access application {app.get('id')} with domain in self_hosted_domains")
                    return app

            logging.info(f"No Access application found for '{domain}'")
            return None

        except CloudflareAPIError as e:
            logging.error(f"API error finding Access application: {e}")
            return None

    def create_application(
        self,
        domain: str,
        name: str,
        session_duration: str = "24h",
        app_launcher_visible: bool = False,
        self_hosted_domains: List[str] = None,
        policies: List[Dict] = None,
        allowed_idps: List[str] = None,
        auto_redirect_to_identity: bool = False,
    ) -> Optional[Dict]:
        """
        Create an Access application.

        Args:
            domain: Primary domain for the application
            name: Application name
            session_duration: Session duration (e.g., "24h")
            app_launcher_visible: Show in App Launcher
            self_hosted_domains: Additional domains
            policies: Access policies to apply
            allowed_idps: Allowed identity provider IDs
            auto_redirect_to_identity: Auto-redirect to IdP

        Returns:
            Created application dict or None on error
        """
        logging.info(f"Creating Access application '{name}' for domain '{domain}'")

        payload = {
            "name": name,
            "domain": domain,
            "type": "self_hosted",
            "session_duration": session_duration,
            "app_launcher_visible": app_launcher_visible,
            "auto_redirect_to_identity": auto_redirect_to_identity,
        }

        if self_hosted_domains:
            payload["self_hosted_domains"] = self_hosted_domains

        if policies:
            payload["policies"] = policies

        if allowed_idps:
            payload["allowed_idps"] = allowed_idps

        try:
            response = self.client.request(
                "POST",
                f"/accounts/{self.account_id}/access/apps",
                json_data=payload,
            )

            app = response.get("result")
            if app and app.get("id"):
                logging.info(f"Created Access application {app.get('id')}")
                return app
            else:
                logging.error("Access application creation succeeded but no ID returned")
                return None

        except CloudflareAPIError as e:
            logging.error(f"API error creating Access application: {e}")
            return None

    def update_application(
        self,
        app_id: str,
        domain: str,
        name: str,
        session_duration: str = "24h",
        app_launcher_visible: bool = False,
        self_hosted_domains: List[str] = None,
        policies: List[Dict] = None,
        allowed_idps: List[str] = None,
        auto_redirect_to_identity: bool = False,
    ) -> Optional[Dict]:
        """
        Update an Access application.

        Args:
            app_id: Application ID to update
            domain: Primary domain
            name: Application name
            session_duration: Session duration
            app_launcher_visible: Show in App Launcher
            self_hosted_domains: Additional domains
            policies: Access policies
            allowed_idps: Allowed IdP IDs
            auto_redirect_to_identity: Auto-redirect to IdP

        Returns:
            Updated application dict or None on error
        """
        logging.info(f"Updating Access application {app_id}")

        payload = {
            "name": name,
            "domain": domain,
            "type": "self_hosted",
            "session_duration": session_duration,
            "app_launcher_visible": app_launcher_visible,
            "auto_redirect_to_identity": auto_redirect_to_identity,
        }

        if self_hosted_domains:
            payload["self_hosted_domains"] = self_hosted_domains

        if policies is not None:
            payload["policies"] = policies

        if allowed_idps:
            payload["allowed_idps"] = allowed_idps

        try:
            response = self.client.request(
                "PUT",
                f"/accounts/{self.account_id}/access/apps/{app_id}",
                json_data=payload,
            )

            app = response.get("result")
            if app:
                logging.info(f"Updated Access application {app_id}")
                return app
            return None

        except CloudflareAPIError as e:
            logging.error(f"API error updating Access application: {e}")
            return None

    def delete_application(self, app_id: str) -> bool:
        """
        Delete an Access application.

        Args:
            app_id: Application ID to delete

        Returns:
            True on success, False on error
        """
        logging.info(f"Deleting Access application {app_id}")

        try:
            self.client.request(
                "DELETE",
                f"/accounts/{self.account_id}/access/apps/{app_id}",
            )
            logging.info(f"Deleted Access application {app_id}")
            return True

        except CloudflareAPIError as e:
            logging.error(f"API error deleting Access application: {e}")
            return False

    def list_applications(self, per_page: int = 100) -> List[Dict]:
        """
        List all Access applications.

        Args:
            per_page: Number of applications per page

        Returns:
            List of application dicts
        """
        apps = []
        page = 1

        while True:
            try:
                response = self.client.request(
                    "GET",
                    f"/accounts/{self.account_id}/access/apps",
                    params={"page": page, "per_page": per_page},
                )

                results = response.get("result", [])
                if not results:
                    break

                apps.extend(results)

                result_info = response.get("result_info", {})
                total_pages = result_info.get("total_pages", 1)

                if page >= total_pages:
                    break
                page += 1

            except CloudflareAPIError as e:
                logging.error(f"API error listing Access applications: {e}")
                break

        return apps

    def create_policy(
        self,
        name: str,
        decision: str,
        include: List[Dict],
        exclude: List[Dict] = None,
        require: List[Dict] = None,
    ) -> Optional[Dict]:
        """
        Create a reusable Access policy.

        Args:
            name: Policy name
            decision: Policy decision (allow, deny, bypass)
            include: Include rules
            exclude: Exclude rules
            require: Require rules

        Returns:
            Created policy dict or None on error
        """
        logging.info(f"Creating Access policy '{name}'")

        payload = {
            "name": name,
            "decision": decision,
            "include": include,
        }

        if exclude:
            payload["exclude"] = exclude

        if require:
            payload["require"] = require

        try:
            response = self.client.request(
                "POST",
                f"/accounts/{self.account_id}/access/policies",
                json_data=payload,
            )

            policy = response.get("result")
            if policy and policy.get("id"):
                logging.info(f"Created Access policy {policy.get('id')}")
                return policy
            return None

        except CloudflareAPIError as e:
            logging.error(f"API error creating Access policy: {e}")
            return None

    def find_policy(self, name: str) -> Optional[Dict]:
        """
        Find an Access policy by name.

        Args:
            name: Policy name to search for

        Returns:
            Policy dict or None if not found
        """
        try:
            response = self.client.request(
                "GET",
                f"/accounts/{self.account_id}/access/policies",
            )

            policies = response.get("result", [])
            for policy in policies:
                if policy.get("name") == name:
                    return policy

            return None

        except CloudflareAPIError as e:
            logging.error(f"API error finding Access policy: {e}")
            return None

    def delete_policy(self, policy_id: str) -> bool:
        """
        Delete an Access policy.

        Args:
            policy_id: Policy ID to delete

        Returns:
            True on success, False on error
        """
        try:
            self.client.request(
                "DELETE",
                f"/accounts/{self.account_id}/access/policies/{policy_id}",
            )
            logging.info(f"Deleted Access policy {policy_id}")
            return True

        except CloudflareAPIError as e:
            logging.error(f"API error deleting Access policy: {e}")
            return False


def build_bypass_policy() -> Dict:
    """Build a policy that bypasses access checks."""
    return {
        "decision": "bypass",
        "include": [{"everyone": {}}],
    }


def build_allow_policy(emails: List[str] = None, email_domains: List[str] = None) -> Dict:
    """
    Build a policy that allows specific users.

    Args:
        emails: List of allowed email addresses
        email_domains: List of allowed email domains

    Returns:
        Policy dict
    """
    include = []

    if emails:
        for email in emails:
            include.append({"email": {"email": email}})

    if email_domains:
        for domain in email_domains:
            include.append({"email_domain": {"domain": domain}})

    if not include:
        include.append({"everyone": {}})

    return {
        "decision": "allow",
        "include": include,
    }


# Module-level convenience instance
_default_manager: AccessManager = None


def get_manager() -> AccessManager:
    """Get or create the default AccessManager instance."""
    global _default_manager
    if _default_manager is None:
        _default_manager = AccessManager()
    return _default_manager


def find_access_application(domain: str) -> Optional[Dict]:
    """Find an Access application by domain."""
    return get_manager().find_application(domain)


def create_access_application(
    domain: str,
    name: str,
    session_duration: str = "24h",
    policies: List[Dict] = None,
) -> Optional[Dict]:
    """Create an Access application."""
    return get_manager().create_application(
        domain=domain,
        name=name,
        session_duration=session_duration,
        policies=policies,
    )


def delete_access_application(app_id: str) -> bool:
    """Delete an Access application."""
    return get_manager().delete_application(app_id)
