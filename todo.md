# Todo

## Plan
Build the core infrastructure first (configuration, Cloudflare API client), then Docker container monitoring and label parsing, followed by tunnel and DNS management, state persistence, reconciliation engine, and finally the Flask web application with API routes. Each feature includes production code and comprehensive tests.

## Tasks
- [x] Task 1: Implement configuration management with environment variable loading, defaults, and runtime settings for Cloudflare API, Docker, tunnels, and caching
- [x] Task 2: Implement Cloudflare API client with authentication, request handling, zone lookup, and retry logic for tunnel and DNS operations
- [x] Task 3: Implement Docker label parser that extracts tunnel configuration (hostname, service, access policies) from container labels with validation
- [x] Task 4: Implement tunnel management that creates, finds, and configures Cloudflare Tunnels via API with ingress rule building
- [x] Task 5: Implement DNS record management for creating, updating, and deleting CNAME records pointing to tunnel endpoints
- [x] Task 6: Implement state manager for persisting and loading tunnel rules, access groups, and agents with encryption support
- [x] Task 7: Implement Cloudflare Access manager for creating and managing Access applications and policies from container labels
- [x] Task 8: Implement Docker event handler that monitors container lifecycle events (start/stop/die) and triggers rule updates
- [x] Task 9: Implement reconciliation engine that compares desired state from containers with Cloudflare state and applies changes
- [x] Task 10: Implement cache layer with Redis and in-memory fallback for DNS records, zone data, and API responses
- [ ] Task 11: Implement Flask application factory with blueprints, authentication (local and OAuth), CSRF protection, and rate limiting
- [ ] Task 12: Implement API routes for rule management, tunnel status, agent enrollment, and system health endpoints
- [ ] Task 13: Implement backup and restore functionality for encrypted configuration, state, and rule data
- [ ] Task 14: Implement multi-host agent support with key management, heartbeat monitoring, and remote container discovery
