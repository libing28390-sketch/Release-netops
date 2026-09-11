from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "deploy-docker.sh"


def test_deploy_script_includes_redis_compose_overlay_and_offline_image():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "docker-compose.redis.yml" in source
    assert "NETOPS_REDIS_ENABLED" in source
    assert "compose()" in source
    assert "redis:7.4.2-alpine" in source
    assert "redis-status" in source
    assert "redis-logs" in source
    assert "--pull never" in source
    assert 'set_env_value REDIS_PASSWORD' in source
    assert 'set_env_value REDIS_URL "redis://nexora:' in source


def test_deploy_script_keeps_an_explicit_way_to_disable_the_sidecar():
    source = SCRIPT.read_text(encoding="utf-8")

    assert '"${NETOPS_REDIS_ENABLED:-1}" != "0"' in source
    assert "without the optional Redis sidecar" in source
