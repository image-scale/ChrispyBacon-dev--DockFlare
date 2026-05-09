# Acceptance Criteria

## Task 1: Configuration Management (COMPLETED)

### Acceptance Criteria
- [x] get_int_env("TEST_INT", 100) returns 100 when TEST_INT is not set
- [x] get_int_env("TEST_INT", 100) returns 50 when TEST_INT="50"
- [x] get_int_env("TEST_INT", 100) returns 100 when TEST_INT="invalid" (logs warning)
- [x] get_int_env("TEST_INT", 100, minimum=10) returns 100 when TEST_INT="5" (below minimum)
- [x] APP_VERSION is a string starting with "v"
- [x] LOG_LEVEL defaults to "WARNING" when not set
- [x] CF_API_BASE_URL equals "https://api.cloudflare.com/client/v4"
- [x] LABEL_PREFIX defaults to "dockflare." when LABEL_PREFIX env not set
- [x] USE_EXTERNAL_CLOUDFLARED is False by default
- [x] STATE_FILE_PATH has a sensible default path
- [x] REDIS_DB_INDEX defaults to 0
- [x] CLEANUP_INTERVAL_SECONDS defaults to 60
- [x] AGENT_HEARTBEAT_TIMEOUT defaults to 60
- [x] Configuration module can be imported without errors

## Task 2: Cloudflare API Client (COMPLETED)

### Acceptance Criteria
- [x] cf_request("GET", "/zones") makes authenticated request with API token header
- [x] cf_request handles successful JSON responses with success=true
- [x] cf_request raises exception on success=false with error message
- [x] cf_request handles HTTP errors and extracts Cloudflare error details
- [x] cf_request handles empty/204 responses gracefully
- [x] cf_request logs request method, URL, and response status
- [x] get_zone_id("example.com") returns cached zone ID on repeat calls
- [x] get_zone_id returns None for non-existent zones
- [x] list_zones() returns list of active zone IDs with names
- [x] Zone ID cache expires after TTL and refreshes on next call

## Task 3: Docker Label Parser (COMPLETED)

### Acceptance Criteria
- [x] extract_label(labels, "enable") returns label value using primary prefix "dockflare."
- [x] extract_label(labels, "enable") falls back to legacy prefix "cloudflare.tunnel."
- [x] extract_label with custom prefix checks custom prefix first
- [x] validate_hostname("api.example.com") returns True for valid hostnames
- [x] validate_hostname("*.example.com") returns True for wildcard hostnames
- [x] validate_hostname("-invalid.com") returns False for invalid hostnames
- [x] validate_service("http://app:8080") returns True for valid HTTP service URLs
- [x] validate_service("tcp://app:22") returns True for TCP protocol
- [x] validate_service("invalid") returns False for invalid service URLs
- [x] parse_container_labels extracts hostname, service, and access settings
- [x] parse_container_labels handles indexed labels (0.hostname, 1.hostname) for multiple routes
- [x] parse_container_labels returns empty list when enable=false

## Task 4: Tunnel Management (COMPLETED)

### Acceptance Criteria
- [x] find_tunnel("my-tunnel") returns (tunnel_id, token) for existing tunnel
- [x] find_tunnel returns (None, None) for non-existent tunnel
- [x] create_tunnel("my-tunnel") creates tunnel and returns (tunnel_id, token)
- [x] get_tunnel_token(tunnel_id) retrieves tunnel connection token
- [x] get_tunnel_config(tunnel_id) returns current ingress configuration
- [x] update_tunnel_config(tunnel_id, ingress) updates tunnel ingress rules
- [x] build_ingress_entry creates proper ingress rule dict from route config
- [x] Ingress entries include hostname, service, and originRequest settings

## Task 5: DNS Record Management (COMPLETED)

### Acceptance Criteria
- [x] create_dns_record creates CNAME record pointing to tunnel
- [x] find_dns_record finds existing CNAME for hostname in zone
- [x] update_dns_record updates existing record to point to correct tunnel
- [x] delete_dns_record removes DNS record by ID
- [x] DNS content format is "{tunnel_id}.cfargotunnel.com"
- [x] Record is created with proxied=true and TTL=1 (auto)
- [x] Returns record ID on successful creation

## Task 6: State Manager (COMPLETED)

### Acceptance Criteria
- [x] save_state persists rules, access groups, and agents to JSON file
- [x] load_state reads and populates state from JSON file
- [x] State includes managed_rules dict keyed by hostname|path
- [x] State includes access_groups dict keyed by group ID
- [x] State includes agents dict keyed by agent ID
- [x] State can be accessed via thread-safe get/set operations
- [x] load_state handles missing file gracefully (empty state)
- [x] State file path is configurable via settings

## Task 7: Cloudflare Access Manager (COMPLETED)

### Acceptance Criteria
- [x] AccessManager.find_application finds app by domain
- [x] AccessManager.create_application creates Access application
- [x] AccessManager.update_application updates existing application
- [x] AccessManager.delete_application removes application
- [x] build_bypass_policy creates bypass policy with everyone rule
- [x] build_allow_policy creates allow policy with email/domain rules
- [x] Module-level convenience functions use default manager

## Task 8: Docker Event Handler (COMPLETED)

### Acceptance Criteria
- [x] ContainerEvent class represents Docker container events
- [x] DockerEventHandler.on_start registers start event handlers
- [x] DockerEventHandler.on_stop registers stop/die event handlers
- [x] handle_event parses labels and calls appropriate handlers
- [x] process_docker_event converts Docker SDK event format to ContainerEvent
- [x] scan_existing_containers processes running containers on startup
- [x] start_event_listener starts background thread for Docker events
- [x] Event listener stops gracefully when stop_event is set
- [x] Handlers continue execution even if one handler raises exception

## Task 9: Reconciliation Engine (COMPLETED)

### Acceptance Criteria
- [x] ReconciliationResult tracks created, updated, deleted, and restored rules
- [x] Reconciler.reconcile creates new rules from routes
- [x] Reconciler.reconcile updates rules when service or settings change
- [x] Reconciler skips manual rules to avoid overwriting them
- [x] Reconciler restores rules marked for deletion when container restarts
- [x] Reconciler marks missing rules for deletion with grace period
- [x] Reconciler saves state after making changes
- [x] cleanup_expired_rules removes rules past their deletion time
- [x] ReconciliationRunner runs periodic reconciliation in background
- [x] ReconciliationRunner can be manually triggered

## Task 10: Cache Layer (COMPLETED)

### Acceptance Criteria
- [x] MemoryCache stores values with TTL-based expiration
- [x] MemoryCache evicts expired entries before oldest when full
- [x] RedisCache connects to Redis and stores JSON-serialized values
- [x] RedisCache handles connection failures gracefully
- [x] CacheManager falls back to memory when Redis unavailable
- [x] CacheManager supports namespacing for different data types
- [x] get_or_set returns cached value or computes and caches new value
- [x] Module-level functions provide convenient access to zone and DNS caching

## Task 11: Flask Application Factory (COMPLETED)

### Acceptance Criteria
- [x] create_app returns configured Flask application
- [x] Application has secret key and secure session settings
- [x] CSRF protection is enabled via Flask-WTF
- [x] Rate limiting is enabled via Flask-Limiter
- [x] User class supports password, OAuth, and API authentication methods
- [x] Login manager loads users from session and request headers
- [x] Web blueprint provides login, logout, and dashboard routes
- [x] API blueprint provides status, health, and rules endpoints
- [x] Disabled password login mode auto-authenticates users

## Task 12: API Routes (COMPLETED)

### Acceptance Criteria
- [x] GET /api/v1/status returns API status with version and timestamp
- [x] GET /api/v1/health returns health check with component checks
- [x] GET /api/v1/rules lists all managed rules with filtering
- [x] POST /api/v1/rules creates new manual rules
- [x] DELETE /api/v1/rules/<key> deletes rules
- [x] GET /api/v1/tunnel/status returns tunnel connection status
- [x] GET /api/v1/agents lists registered agents
- [x] POST /api/v1/agents/enroll enrolls new agents with API keys
- [x] POST /api/v1/agents/<id>/heartbeat updates agent status
- [x] GET /api/v1/system/info returns system information
