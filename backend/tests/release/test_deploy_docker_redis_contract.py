from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "deploy-docker.sh"
COMPOSE = ROOT / "docker-compose.yml"
ENV_EXAMPLE = ROOT / ".env.example"


def test_deploy_script_uses_the_unified_compose_file_and_offline_image():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "docker-compose.redis.yml" not in source
    assert "COMPOSE_FILES=(-f docker-compose.yml)" in source
    assert "NETOPS_REDIS_ENABLED" in source
    assert "compose()" in source
    assert "compose_service_args()" in source
    assert "compose stop redis" in source
    assert "redis:7.4.2-alpine" in source
    assert "redis-status" in source
    assert "redis-logs" in source
    assert "compose logs --timestamps -f --tail=200 redis" in source
    assert "--pull never" in source
    assert 'set_env_value REDIS_PASSWORD' in source
    assert 'set_env_value REDIS_URL "redis://nexora:' in source
    assert 'set_env_value GRAFANA_ROOT_URL "https://${server_name}/grafana/"' in source
    assert "%(domain)s" in source
    assert "replace-with-your-server-host" in source
    assert "start_deferred_vmagent" in source
    assert 'docker compose --project-name "$project_name"' in source
    assert "resolve_compose_project_name()" in source
    assert 'index .Config.Labels "com.docker.compose.project"' in source
    assert "nexora-db 2>/dev/null || true" in source
    assert 'project_name="${project_name:-nexora}"' in source
    assert "Reset removes the integrated Redis service and volume" in source
    assert "local local_images=(nexora-netops nexora-nginx nexora-postgres redis:7.4.2-alpine)" in source


def test_deploy_script_keeps_an_explicit_way_to_disable_the_sidecar():
    source = SCRIPT.read_text(encoding="utf-8")

    assert '"${NETOPS_REDIS_ENABLED:-1}" != "0"' in source
    assert '"${NETOPS_REDIS_ENABLED:-1}" == "0"' in source
    assert "Set to 0 to run db/netops/monitoring/nginx without Redis." in source


def test_legacy_dashboard_cleanup_uses_stdin_auth_and_only_targets_retired_uid():
    source = SCRIPT.read_text(encoding="utf-8")
    cleanup = source.split("prune_legacy_grafana_dashboard() {", 1)[1].split("\nrequired_images()", 1)[0]

    assert "nexora-server-metrics" in cleanup
    assert '"Server & Host Metrics"' in cleanup
    assert "--config -" in cleanup
    assert "--user " not in cleanup
    assert 'read -r -s -p "Grafana admin password (input hidden): "' in cleanup


def test_redis_sidecar_uses_a_restricted_acl_user_and_keeps_ai_rate_limits_working():
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    service = compose["services"]["redis"]
    source = COMPOSE.read_text(encoding="utf-8")

    assert service["image"] == "redis:7.4.2-alpine"
    assert service["container_name"] == "nexora-redis"
    assert service["entrypoint"] == ["/bin/sh", "-ec"]
    assert isinstance(service["command"], list)
    assert len(service["command"]) == 1
    assert service["command"][0].splitlines()[0] == "umask 077"
    assert "nexora-redis-data:/data" in service["volumes"]
    assert compose["volumes"]["nexora-redis-data"]["name"] == "nexora-redis-data"
    assert "user default off" in source
    assert "user nexora on" in source
    assert "~nexora:*" in source
    assert "~ai:ratelimit:*" in source
    assert "+incr" in source
    assert "+eval" in source
    assert "/usr/local/bin/docker-entrypoint.sh redis-server" in source
    assert "--aclfile /data/nexora-users.acl" in source
    assert "redis-cli --user nexora" in source
    assert "TZ: ${TZ:-Asia/Shanghai}" in source


def test_postgres_session_and_log_timezone_follow_the_shanghai_default():
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    db_service = compose["services"]["db"]
    env_example = ENV_EXAMPLE.read_text(encoding="utf-8")

    assert db_service["command"] == [
        "postgres",
        "-c",
        "timezone=${TZ:-Asia/Shanghai}",
        "-c",
        "log_timezone=${TZ:-Asia/Shanghai}",
        "-c",
        "compute_query_id=auto",
        "-c",
        "pg_stat_statements.max=${PG_STAT_STATEMENTS_MAX:-5000}",
        "-c",
        "pg_stat_statements.track=${PG_STAT_STATEMENTS_TRACK:-top}",
        "-c",
        "pg_stat_statements.track_planning=${PG_STAT_STATEMENTS_TRACK_PLANNING:-off}",
        "-c",
        "shared_preload_libraries=${POSTGRES_SHARED_PRELOAD_LIBRARIES:-pg_stat_statements}",
    ]
    assert "TZ: ${TZ:-Asia/Shanghai}" in COMPOSE.read_text(encoding="utf-8")
    assert "REDIS_URL=redis://nexora@redis:6379/0" in env_example


def test_postgres_exporter_is_limited_and_uses_a_dedicated_monitor_role():
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    exporter = compose["services"]["postgres-exporter"]
    assert exporter["image"] == "quay.io/prometheuscommunity/postgres-exporter:v0.20.1"
    assert exporter["command"] == [
        "--collector.stat_statements",
        "--collector.stat_statements.limit=${PG_STAT_STATEMENTS_EXPORT_LIMIT:-100}",
    ]
    assert any("nexora_metrics" in value for value in exporter["environment"])
    assert "POSTGRES_EXPORTER_PASSWORD" in " ".join(exporter["environment"])
    assert "--collector.stat_statements.include_query" not in exporter["command"]
    assert "GRANT pg_monitor" in (ROOT / "docker" / "postgres" / "21-postgres-exporter-role.sh").read_text(encoding="utf-8")
    assert "quay.io/prometheuscommunity/postgres-exporter:v0.20.1" in (ROOT / "scripts" / "deploy-docker.sh").read_text(encoding="utf-8")
