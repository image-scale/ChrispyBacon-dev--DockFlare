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

## Task 5: DNS Record Management

### Acceptance Criteria
- [ ] create_dns_record creates CNAME record pointing to tunnel
- [ ] find_dns_record finds existing CNAME for hostname in zone
- [ ] update_dns_record updates existing record to point to correct tunnel
- [ ] delete_dns_record removes DNS record by ID
- [ ] DNS content format is "{tunnel_id}.cfargotunnel.com"
- [ ] Record is created with proxied=true and TTL=1 (auto)
- [ ] Returns record ID on successful creation
