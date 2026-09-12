from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "deploy-docker.sh"
COMPOSE = ROOT / "docker-compose.redis.yml"
ENV_EXAMPLE = ROOT / ".env.example"


def test_deploy_script_includes_redis_compose_overlay_and_offline_image():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "docker-compose.redis.yml" in source
    assert "NETOPS_REDIS_ENABLED" in source
    assert "compose()" in source
    assert "redis:7.4.2-alpine" in source
    assert "redis-status" in source
    assert "redis-logs" in source
    assert "compose logs --timestamps -f --tail=200 redis" in source
    assert "--pull never" in source
    assert 'set_env_value REDIS_PASSWORD' in source
    assert 'set_env_value REDIS_URL "redis://nexora:' in source
    assert 'docker compose --project-name "$project_name"' in source
    assert 'Reset removes any sidecar volume left by an earlier Redis-enabled run' in source


def test_deploy_script_keeps_an_explicit_way_to_disable_the_sidecar():
    source = SCRIPT.read_text(encoding="utf-8")

    assert '"${NETOPS_REDIS_ENABLED:-1}" != "0"' in source
    assert "without the optional Redis sidecar" in source


def test_redis_sidecar_uses_a_restricted_acl_user_and_keeps_ai_rate_limits_working():
    source = COMPOSE.read_text(encoding="utf-8")
    env_example = ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "user default off" in source
    assert "user nexora on" in source
    assert "~nexora:*" in source
    assert "~ai:ratelimit:*" in source
    assert "+incr" in source
    assert "+eval" in source
    assert "/usr/local/bin/docker-entrypoint.sh redis-server" in source
    assert "--aclfile /data/nexora-users.acl" in source
    assert "redis-cli --user nexora" in source
    assert "REDIS_URL=redis://nexora@redis:6379/0" in env_example
