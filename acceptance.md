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

## Task 2: Cloudflare API Client

### Acceptance Criteria
- [ ] cf_request("GET", "/zones") makes authenticated request with API token header
- [ ] cf_request handles successful JSON responses with success=true
- [ ] cf_request raises exception on success=false with error message
- [ ] cf_request handles HTTP errors and extracts Cloudflare error details
- [ ] cf_request handles empty/204 responses gracefully
- [ ] cf_request logs request method, URL, and response status
- [ ] get_zone_id("example.com") returns cached zone ID on repeat calls
- [ ] get_zone_id returns None for non-existent zones
- [ ] list_zones() returns list of active zone IDs with names
- [ ] Zone ID cache expires after TTL and refreshes on next call
