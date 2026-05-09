# Acceptance Criteria

## Task 1: Configuration Management

### Acceptance Criteria
- [ ] get_int_env("TEST_INT", 100) returns 100 when TEST_INT is not set
- [ ] get_int_env("TEST_INT", 100) returns 50 when TEST_INT="50"
- [ ] get_int_env("TEST_INT", 100) returns 100 when TEST_INT="invalid" (logs warning)
- [ ] get_int_env("TEST_INT", 100, minimum=10) returns 100 when TEST_INT="5" (below minimum)
- [ ] APP_VERSION is a string starting with "v"
- [ ] LOG_LEVEL defaults to "WARNING" when not set
- [ ] CF_API_BASE_URL equals "https://api.cloudflare.com/client/v4"
- [ ] LABEL_PREFIX defaults to "dockflare." when LABEL_PREFIX env not set
- [ ] USE_EXTERNAL_CLOUDFLARED is False by default
- [ ] STATE_FILE_PATH has a sensible default path
- [ ] REDIS_DB_INDEX defaults to 0
- [ ] CLEANUP_INTERVAL_SECONDS defaults to 60
- [ ] AGENT_HEARTBEAT_TIMEOUT defaults to 60
- [ ] Configuration module can be imported without errors
