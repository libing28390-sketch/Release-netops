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
    assert "Set to 0 to run db/netops/nginx without Redis." in source


def test_redis_sidecar_uses_a_restricted_acl_user_and_keeps_ai_rate_limits_working():
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    service = compose["services"]["redis"]
    source = COMPOSE.read_text(encoding="utf-8")
    env_example = ENV_EXAMPLE.read_text(encoding="utf-8")

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
    assert "REDIS_URL=redis://nexora@redis:6379/0" in env_example
