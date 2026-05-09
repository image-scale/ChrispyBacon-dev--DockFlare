"""Tests for Docker container event handling."""

import pytest
import threading
import time
from unittest.mock import Mock, MagicMock, patch

from dockflare.docker_events import (
    ContainerEvent,
    DockerEventHandler,
    scan_existing_containers,
    start_event_listener,
    get_handler,
)
from dockflare.labels import RouteConfig


class TestContainerEvent:
    """Tests for ContainerEvent class."""

    def test_creates_event_with_required_fields(self):
        """Should create event with event_type and container_id."""
        event = ContainerEvent(
            event_type="start",
            container_id="abc123def456",
        )

        assert event.event_type == "start"
        assert event.container_id == "abc123def456"
        assert event.container_name == "abc123def456"[:12]
        assert event.labels == {}

    def test_creates_event_with_all_fields(self):
        """Should create event with all fields."""
        labels = {"dockflare.enable": "true", "dockflare.hostname": "app.example.com"}
        event = ContainerEvent(
            event_type="start",
            container_id="abc123def456",
            container_name="my-app",
            labels=labels,
        )

        assert event.event_type == "start"
        assert event.container_id == "abc123def456"
        assert event.container_name == "my-app"
        assert event.labels == labels

    def test_repr_format(self):
        """Should have readable repr."""
        event = ContainerEvent(
            event_type="stop",
            container_id="abc123",
            container_name="my-app",
        )

        assert "ContainerEvent" in repr(event)
        assert "stop" in repr(event)
        assert "my-app" in repr(event)


class TestDockerEventHandler:
    """Tests for DockerEventHandler class."""

    @pytest.fixture
    def handler(self):
        """Create a DockerEventHandler."""
        return DockerEventHandler()

    def test_init_creates_empty_handler_lists(self, handler):
        """Should initialize with empty handler lists."""
        assert handler._start_handlers == []
        assert handler._stop_handlers == []

    def test_on_start_registers_handler(self, handler):
        """Should register start handler."""
        callback = Mock()
        handler.on_start(callback)

        assert callback in handler._start_handlers

    def test_on_stop_registers_handler(self, handler):
        """Should register stop handler."""
        callback = Mock()
        handler.on_stop(callback)

        assert callback in handler._stop_handlers

    def test_multiple_handlers_can_be_registered(self, handler):
        """Should allow multiple handlers."""
        callback1 = Mock()
        callback2 = Mock()
        handler.on_start(callback1)
        handler.on_start(callback2)

        assert len(handler._start_handlers) == 2


class TestDockerEventHandlerHandleEvent:
    """Tests for handle_event method."""

    @pytest.fixture
    def handler(self):
        return DockerEventHandler()

    def test_calls_start_handlers_on_start_event(self, handler):
        """Should call start handlers for start events."""
        callback = Mock()
        handler.on_start(callback)

        labels = {
            "dockflare.enable": "true",
            "dockflare.hostname": "app.example.com",
            "dockflare.service": "http://app:80",
        }
        event = ContainerEvent(
            event_type="start",
            container_id="abc123",
            container_name="my-app",
            labels=labels,
        )

        handler.handle_event(event)

        callback.assert_called_once()
        call_args = callback.call_args[0]
        assert call_args[0] == event
        assert isinstance(call_args[1], list)

    def test_calls_stop_handlers_on_stop_event(self, handler):
        """Should call stop handlers for stop events."""
        callback = Mock()
        handler.on_stop(callback)

        event = ContainerEvent(
            event_type="stop",
            container_id="abc123",
            container_name="my-app",
        )

        handler.handle_event(event)

        callback.assert_called_once_with(event)

    def test_calls_stop_handlers_on_die_event(self, handler):
        """Should call stop handlers for die events."""
        callback = Mock()
        handler.on_stop(callback)

        event = ContainerEvent(
            event_type="die",
            container_id="abc123",
            container_name="my-app",
        )

        handler.handle_event(event)

        callback.assert_called_once_with(event)

    def test_does_not_call_start_handlers_without_routes(self, handler):
        """Should not call start handlers if no routes parsed."""
        callback = Mock()
        handler.on_start(callback)

        event = ContainerEvent(
            event_type="start",
            container_id="abc123",
            container_name="my-app",
            labels={},
        )

        handler.handle_event(event)

        callback.assert_not_called()

    def test_handles_exception_in_start_handler(self, handler):
        """Should continue on handler exception."""
        callback1 = Mock(side_effect=Exception("Handler error"))
        callback2 = Mock()
        handler.on_start(callback1)
        handler.on_start(callback2)

        labels = {
            "dockflare.enable": "true",
            "dockflare.hostname": "app.example.com",
            "dockflare.service": "http://app:80",
        }
        event = ContainerEvent(
            event_type="start",
            container_id="abc123",
            container_name="my-app",
            labels=labels,
        )

        handler.handle_event(event)

        callback1.assert_called_once()
        callback2.assert_called_once()

    def test_handles_exception_in_stop_handler(self, handler):
        """Should continue on stop handler exception."""
        callback1 = Mock(side_effect=Exception("Handler error"))
        callback2 = Mock()
        handler.on_stop(callback1)
        handler.on_stop(callback2)

        event = ContainerEvent(
            event_type="stop",
            container_id="abc123",
            container_name="my-app",
        )

        handler.handle_event(event)

        callback1.assert_called_once()
        callback2.assert_called_once()


class TestDockerEventHandlerProcessDockerEvent:
    """Tests for process_docker_event method."""

    @pytest.fixture
    def handler(self):
        return DockerEventHandler()

    def test_processes_start_action(self, handler):
        """Should process start action."""
        callback = Mock()
        handler.on_start(callback)

        docker_event = {
            "Action": "start",
            "Actor": {
                "ID": "abc123def456",
                "Attributes": {
                    "name": "my-app",
                    "dockflare.enable": "true",
                    "dockflare.hostname": "app.example.com",
                    "dockflare.service": "http://app:80",
                },
            },
        }

        handler.process_docker_event(docker_event)

        callback.assert_called_once()

    def test_processes_stop_action(self, handler):
        """Should process stop action."""
        callback = Mock()
        handler.on_stop(callback)

        docker_event = {
            "Action": "stop",
            "Actor": {
                "ID": "abc123def456",
                "Attributes": {"name": "my-app"},
            },
        }

        handler.process_docker_event(docker_event)

        callback.assert_called_once()

    def test_processes_die_action(self, handler):
        """Should process die action."""
        callback = Mock()
        handler.on_stop(callback)

        docker_event = {
            "Action": "die",
            "Actor": {
                "ID": "abc123def456",
                "Attributes": {"name": "my-app"},
            },
        }

        handler.process_docker_event(docker_event)

        callback.assert_called_once()

    def test_processes_kill_action(self, handler):
        """Should process kill action as stop."""
        callback = Mock()
        handler.on_stop(callback)

        docker_event = {
            "Action": "kill",
            "Actor": {
                "ID": "abc123def456",
                "Attributes": {"name": "my-app"},
            },
        }

        handler.process_docker_event(docker_event)

        callback.assert_called_once()

    def test_ignores_unknown_action(self, handler):
        """Should ignore unknown actions."""
        start_callback = Mock()
        stop_callback = Mock()
        handler.on_start(start_callback)
        handler.on_stop(stop_callback)

        docker_event = {
            "Action": "pause",
            "Actor": {
                "ID": "abc123def456",
                "Attributes": {"name": "my-app"},
            },
        }

        handler.process_docker_event(docker_event)

        start_callback.assert_not_called()
        stop_callback.assert_not_called()

    def test_handles_status_field_fallback(self, handler):
        """Should fall back to status field if Action missing."""
        callback = Mock()
        handler.on_stop(callback)

        docker_event = {
            "status": "stop",
            "id": "abc123def456",
            "Actor": {
                "Attributes": {"name": "my-app"},
            },
        }

        handler.process_docker_event(docker_event)

        callback.assert_called_once()

    def test_handles_missing_action(self, handler):
        """Should handle missing action gracefully."""
        callback = Mock()
        handler.on_start(callback)

        docker_event = {
            "Actor": {
                "ID": "abc123def456",
                "Attributes": {"name": "my-app"},
            },
        }

        handler.process_docker_event(docker_event)

        callback.assert_not_called()

    def test_extracts_container_id_from_actor(self, handler):
        """Should extract container ID from Actor."""
        callback = Mock()
        handler.on_stop(callback)

        docker_event = {
            "Action": "stop",
            "Actor": {
                "ID": "full-container-id-12345",
                "Attributes": {"name": "my-app"},
            },
        }

        handler.process_docker_event(docker_event)

        event = callback.call_args[0][0]
        assert event.container_id == "full-container-id-12345"

    def test_extracts_container_name_from_attributes(self, handler):
        """Should extract container name from Attributes."""
        callback = Mock()
        handler.on_stop(callback)

        docker_event = {
            "Action": "stop",
            "Actor": {
                "ID": "abc123",
                "Attributes": {"name": "custom-name"},
            },
        }

        handler.process_docker_event(docker_event)

        event = callback.call_args[0][0]
        assert event.container_name == "custom-name"


class TestScanExistingContainers:
    """Tests for scan_existing_containers function."""

    def test_scans_running_containers(self):
        """Should scan and process running containers."""
        mock_container = Mock()
        mock_container.id = "abc123"
        mock_container.name = "my-app"
        mock_container.labels = {
            "dockflare.enable": "true",
            "dockflare.hostname": "app.example.com",
            "dockflare.service": "http://app:80",
        }

        mock_client = Mock()
        mock_client.containers.list.return_value = [mock_container]

        handler = DockerEventHandler()
        callback = Mock()
        handler.on_start(callback)

        routes = scan_existing_containers(mock_client, handler)

        assert len(routes) == 1
        assert routes[0].hostname == "app.example.com"
        callback.assert_called_once()

    def test_returns_empty_list_when_no_containers(self):
        """Should return empty list when no containers."""
        mock_client = Mock()
        mock_client.containers.list.return_value = []

        handler = DockerEventHandler()
        routes = scan_existing_containers(mock_client, handler)

        assert routes == []

    def test_filters_containers_by_label(self):
        """Should apply label filters."""
        mock_client = Mock()
        mock_client.containers.list.return_value = []

        handler = DockerEventHandler()
        scan_existing_containers(
            mock_client,
            handler,
            filter_labels={"dockflare.enable": "true"},
        )

        call_kwargs = mock_client.containers.list.call_args.kwargs
        assert "label" in call_kwargs["filters"]

    def test_handles_container_error(self):
        """Should handle error processing individual container."""
        mock_container1 = Mock()
        mock_container1.id = "abc123"
        mock_container1.name = "app1"
        mock_container1.labels = {
            "dockflare.enable": "true",
            "dockflare.hostname": "app1.example.com",
            "dockflare.service": "http://app:80",
        }

        mock_container2 = Mock()
        mock_container2.id = "def456"
        mock_container2.name = "app2"
        mock_container2.labels = property(lambda self: (_ for _ in ()).throw(Exception("Error")))

        mock_client = Mock()
        mock_client.containers.list.return_value = [mock_container1]

        handler = DockerEventHandler()
        routes = scan_existing_containers(mock_client, handler)

        assert len(routes) == 1

    def test_handles_list_error(self):
        """Should handle error listing containers."""
        mock_client = Mock()
        mock_client.containers.list.side_effect = Exception("Connection error")

        handler = DockerEventHandler()
        routes = scan_existing_containers(mock_client, handler)

        assert routes == []

    def test_skips_containers_without_routes(self):
        """Should skip containers without route labels."""
        mock_container = Mock()
        mock_container.id = "abc123"
        mock_container.name = "my-app"
        mock_container.labels = {}

        mock_client = Mock()
        mock_client.containers.list.return_value = [mock_container]

        handler = DockerEventHandler()
        callback = Mock()
        handler.on_start(callback)

        routes = scan_existing_containers(mock_client, handler)

        assert routes == []
        callback.assert_not_called()


class TestStartEventListener:
    """Tests for start_event_listener function."""

    def test_starts_listener_thread(self):
        """Should start a daemon thread."""
        mock_client = Mock()
        mock_client.events.return_value = iter([])

        handler = DockerEventHandler()
        stop_event = threading.Event()
        stop_event.set()

        thread = start_event_listener(mock_client, handler, stop_event)

        assert thread.daemon is True
        assert thread.name == "DockerEventListener"
        thread.join(timeout=1)

    def test_processes_container_events(self):
        """Should process container events."""
        events = [
            {
                "Type": "container",
                "Action": "start",
                "Actor": {
                    "ID": "abc123",
                    "Attributes": {
                        "name": "my-app",
                        "dockflare.enable": "true",
                        "dockflare.hostname": "app.example.com",
                        "dockflare.service": "http://app:80",
                    },
                },
            }
        ]

        mock_client = Mock()
        mock_client.events.return_value = iter(events)

        handler = DockerEventHandler()
        callback = Mock()
        handler.on_start(callback)

        stop_event = threading.Event()
        thread = start_event_listener(mock_client, handler, stop_event)

        time.sleep(0.1)
        stop_event.set()
        thread.join(timeout=1)

        callback.assert_called_once()

    def test_ignores_non_container_events(self):
        """Should ignore non-container events."""
        events = [
            {"Type": "network", "Action": "create"},
            {"Type": "volume", "Action": "create"},
        ]

        mock_client = Mock()
        mock_client.events.return_value = iter(events)

        handler = DockerEventHandler()
        callback = Mock()
        handler.on_start(callback)

        stop_event = threading.Event()
        thread = start_event_listener(mock_client, handler, stop_event)

        time.sleep(0.1)
        stop_event.set()
        thread.join(timeout=1)

        callback.assert_not_called()

    def test_stops_on_stop_event(self):
        """Should stop when stop event is set."""
        def slow_events():
            yield {"Type": "container", "Action": "start", "Actor": {"ID": "abc", "Attributes": {"name": "x"}}}
            time.sleep(1)
            yield {"Type": "container", "Action": "stop", "Actor": {"ID": "abc", "Attributes": {"name": "x"}}}

        mock_client = Mock()
        mock_client.events.return_value = slow_events()

        handler = DockerEventHandler()
        stop_event = threading.Event()

        thread = start_event_listener(mock_client, handler, stop_event)
        time.sleep(0.1)
        stop_event.set()

        thread.join(timeout=2)
        assert not thread.is_alive()


class TestGetHandler:
    """Tests for get_handler function."""

    @patch("dockflare.docker_events._default_handler", None)
    def test_creates_singleton(self):
        """Should create singleton handler."""
        import dockflare.docker_events as events_module
        events_module._default_handler = None

        handler1 = get_handler()
        handler2 = get_handler()

        assert handler1 is handler2
        assert isinstance(handler1, DockerEventHandler)

    @patch("dockflare.docker_events._default_handler", None)
    def test_returns_existing_handler(self):
        """Should return existing handler."""
        import dockflare.docker_events as events_module

        existing = DockerEventHandler()
        events_module._default_handler = existing

        handler = get_handler()

        assert handler is existing
