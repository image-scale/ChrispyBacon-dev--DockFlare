"""
Docker container event handling.

Monitors Docker container lifecycle events and triggers rule updates
when containers start, stop, or die.
"""

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from .labels import parse_container_labels, RouteConfig


class ContainerEvent:
    """Represents a Docker container event."""

    def __init__(
        self,
        event_type: str,
        container_id: str,
        container_name: str = None,
        labels: Dict[str, str] = None,
    ):
        self.event_type = event_type
        self.container_id = container_id
        self.container_name = container_name or container_id[:12]
        self.labels = labels or {}

    def __repr__(self):
        return f"ContainerEvent({self.event_type}, {self.container_name})"


class DockerEventHandler:
    """Handler for Docker container events."""

    def __init__(self):
        """Initialize the event handler."""
        self._start_handlers: List[Callable[[ContainerEvent, List[RouteConfig]], None]] = []
        self._stop_handlers: List[Callable[[ContainerEvent], None]] = []
        self._lock = threading.Lock()
        self._running = False
        self._stop_event = threading.Event()

    def on_start(self, handler: Callable[[ContainerEvent, List[RouteConfig]], None]):
        """
        Register a handler for container start events.

        Handler receives the event and parsed route configurations.
        """
        with self._lock:
            self._start_handlers.append(handler)

    def on_stop(self, handler: Callable[[ContainerEvent], None]):
        """
        Register a handler for container stop/die events.

        Handler receives the event.
        """
        with self._lock:
            self._stop_handlers.append(handler)

    def handle_event(self, event: ContainerEvent):
        """
        Process a container event.

        Parses labels and calls appropriate handlers.
        """
        logging.info(f"Handling container event: {event}")

        if event.event_type == "start":
            routes = parse_container_labels(
                event.labels,
                container_id=event.container_id,
                container_name=event.container_name,
            )

            if routes:
                logging.info(f"Container {event.container_name} has {len(routes)} route(s)")

                with self._lock:
                    handlers = list(self._start_handlers)

                for handler in handlers:
                    try:
                        handler(event, routes)
                    except Exception as e:
                        logging.error(f"Error in start handler: {e}")
            else:
                logging.debug(f"Container {event.container_name} has no routes")

        elif event.event_type in ("stop", "die"):
            logging.info(f"Container {event.container_name} stopped/died")

            with self._lock:
                handlers = list(self._stop_handlers)

            for handler in handlers:
                try:
                    handler(event)
                except Exception as e:
                    logging.error(f"Error in stop handler: {e}")

    def process_docker_event(self, docker_event: Dict[str, Any]):
        """
        Process a raw Docker event dict.

        Converts Docker SDK event format to ContainerEvent.
        """
        action = docker_event.get("Action", docker_event.get("status"))
        if not action:
            return

        actor = docker_event.get("Actor", {})
        container_id = docker_event.get("id") or actor.get("ID", "")
        attributes = actor.get("Attributes", {})
        container_name = attributes.get("name", container_id[:12] if container_id else "unknown")

        if action == "start":
            labels = attributes
            event = ContainerEvent(
                event_type="start",
                container_id=container_id,
                container_name=container_name,
                labels=labels,
            )
            self.handle_event(event)

        elif action in ("stop", "die", "kill"):
            event = ContainerEvent(
                event_type="stop",
                container_id=container_id,
                container_name=container_name,
            )
            self.handle_event(event)


def scan_existing_containers(
    docker_client,
    handler: DockerEventHandler,
    filter_labels: Dict[str, str] = None,
) -> List[RouteConfig]:
    """
    Scan existing containers and process them.

    Args:
        docker_client: Docker client instance
        handler: Event handler to process containers
        filter_labels: Optional label filters

    Returns:
        List of all route configurations found
    """
    logging.info("Scanning existing containers")
    all_routes = []

    try:
        filters = {}
        if filter_labels:
            filters["label"] = [f"{k}={v}" for k, v in filter_labels.items()]

        containers = docker_client.containers.list(filters=filters)
        logging.info(f"Found {len(containers)} containers")

        for container in containers:
            try:
                event = ContainerEvent(
                    event_type="start",
                    container_id=container.id,
                    container_name=container.name,
                    labels=container.labels,
                )

                routes = parse_container_labels(
                    container.labels,
                    container_id=container.id,
                    container_name=container.name,
                )

                if routes:
                    logging.info(f"Container {container.name} has {len(routes)} route(s)")
                    all_routes.extend(routes)
                    handler.handle_event(event)

            except Exception as e:
                logging.error(f"Error processing container {container.name}: {e}")

    except Exception as e:
        logging.error(f"Error scanning containers: {e}")

    return all_routes


def start_event_listener(
    docker_client,
    handler: DockerEventHandler,
    stop_event: threading.Event = None,
) -> threading.Thread:
    """
    Start a background thread that listens for Docker events.

    Args:
        docker_client: Docker client instance
        handler: Event handler for processing events
        stop_event: Optional event to signal stop

    Returns:
        The listener thread
    """
    stop_event = stop_event or threading.Event()

    def listener():
        logging.info("Docker event listener starting")
        try:
            for event in docker_client.events(decode=True):
                if stop_event.is_set():
                    break

                event_type = event.get("Type")
                if event_type == "container":
                    handler.process_docker_event(event)

        except Exception as e:
            if not stop_event.is_set():
                logging.error(f"Error in event listener: {e}")

        logging.info("Docker event listener stopped")

    thread = threading.Thread(target=listener, daemon=True, name="DockerEventListener")
    thread.start()
    return thread


# Module-level convenience instance
_default_handler: DockerEventHandler = None


def get_handler() -> DockerEventHandler:
    """Get or create the default DockerEventHandler instance."""
    global _default_handler
    if _default_handler is None:
        _default_handler = DockerEventHandler()
    return _default_handler
