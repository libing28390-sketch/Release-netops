"""D2: only CMDB-managed device names are tokenized (exact match)."""

import logging

import pytest

from ai.security import known_identifiers
from ai.security.known_identifiers import (
    KNOWN_HOSTNAMES_UNAVAILABLE,
    KnownDeviceNameCache,
    known_device_names,
    reset_cache,
    set_known_device_names_for_tests,
)
from ai.security.output import StreamingOutputResolver
from ai.security.tokenization import TOKEN_RE, ScopedTokenVault, tokenize_text


TENANT = "tenant-d2"
TASK = "task-d2"


@pytest.fixture(autouse=True)
def _clean_device_cache():
    reset_cache()
    yield
    reset_cache()


def tokenize(text: str, vault: ScopedTokenVault) -> str:
    return tokenize_text(text, tenant_id=TENANT, task_id=TASK, vault=vault)


def restore(text: str, vault: ScopedTokenVault) -> str:
    return vault.resolve_text(text, tenant_id=TENANT, task_id=TASK)


def test_known_device_names_are_tokenized_case_insensitively_and_restorable():
    set_known_device_names_for_tests(["sw-core01", "CORE-SW1"])
    vault = ScopedTokenVault()
    text = "交换机sw-core01的端口下联 core-sw1，再查 SW-CORE01."
    out = tokenize(text, vault)

    assert "sw-core01" not in out
    assert "core-sw1" not in out
    assert "SW-CORE01" not in out
    assert out.count("[[NXA_DEVICE_") == 3
    assert restore(out, vault) == text


def test_streaming_resolver_restores_device_tokens_split_across_chunks():
    set_known_device_names_for_tests(["sw-core01"])
    vault = ScopedTokenVault()
    text = "请检查 sw-core01 的上联口"
    out = tokenize(text, vault)
    token = TOKEN_RE.search(out).group(0)
    assert token.startswith("[[NXA_DEVICE_")

    resolver = StreamingOutputResolver(tenant_id=TENANT, task_id=TASK, vault=vault)
    cut = out.index(token) + 8  # split inside the token
    streamed = resolver.push(out[:cut]) + resolver.push(out[cut:]) + resolver.flush()
    assert streamed == text


def test_product_model_is_not_tokenized():
    set_known_device_names_for_tests(["sw-core01"])
    vault = ScopedTokenVault()
    text = "sw-core01 的型号是 CE6800-48S"
    out = tokenize(text, vault)
    assert "CE6800-48S" in out
    assert "sw-core01" not in out
    # Without names, a bare device name is no longer tokenized by pattern.
    reset_cache()
    set_known_device_names_for_tests([])
    assert tokenize("CE6800-48S 和 sw-core01", ScopedTokenVault()) == "CE6800-48S 和 sw-core01"


@pytest.mark.parametrize(
    "text",
    [
        "score is high",
        "the core-dump file",
        "hardcore mode",
        "core_01 interface",
        "core.example.com",
    ],
)
def test_device_name_inside_another_word_is_not_replaced(text):
    set_known_device_names_for_tests(["core"])
    vault = ScopedTokenVault()
    out = tokenize(text, vault)
    assert "[[NXA_DEVICE_" not in out
    assert restore(out, vault) == text


def test_whole_word_device_name_with_punctuation_and_chinese_boundaries():
    set_known_device_names_for_tests(["core"])
    vault = ScopedTokenVault()
    text = "设备core。另一台(core), core."
    out = tokenize(text, vault)
    assert out.count("[[NXA_DEVICE_") == 3
    assert restore(out, vault) == text


def test_longest_device_name_wins():
    set_known_device_names_for_tests(["sw-core01", "sw-core01-mgmt"])
    vault = ScopedTokenVault()
    out = tokenize("登录 sw-core01-mgmt", vault)
    assert out.count("[[NXA_DEVICE_") == 1
    token = TOKEN_RE.search(out).group(0)
    assert vault.resolve_token(token, tenant_id=TENANT, task_id=TASK) == "sw-core01-mgmt"


def test_text_inside_existing_tokens_is_not_retokenized():
    vault = ScopedTokenVault()
    existing = vault.put("10.1.1.1", kind="IP", tenant_id=TENANT, task_id=TASK)
    # Inject the token's own pieces as "device names".
    random_part = existing[len("[[NXA_IP_"):-2]
    set_known_device_names_for_tests(["NXA_IP", random_part])
    text = f"地址 {existing} 已脱敏"
    assert tokenize(text, vault) == text


def test_ip_and_fqdn_keep_their_own_tokens_when_device_names_are_known():
    set_known_device_names_for_tests(["sw-core01"])
    vault = ScopedTokenVault()
    text = "trace 192.0.2.10 from sw-core01.example.com"
    out = tokenize(text, vault)
    assert "[[NXA_IP_" in out
    assert "[[NXA_HOST_" in out
    assert "[[NXA_DEVICE_" not in out
    assert restore(out, vault) == text


def test_empty_device_set_keeps_existing_behavior():
    set_known_device_names_for_tests([])
    vault = ScopedTokenVault()
    text = "交换机sw-core01 CORE-SW1 地址10.1.1.1"
    out = tokenize(text, vault)
    assert "sw-core01" in out
    assert "CORE-SW1" in out
    assert "10.1.1.1" not in out
    assert "[[NXA_DEVICE_" not in out


def test_database_is_not_read_under_tests_by_default():
    # The global cache must not pick up dev-database devices during pytest.
    assert known_device_names() == frozenset()


def test_names_are_filtered_by_length_and_letters():
    cache = KnownDeviceNameCache(
        loader=lambda: ["", None, "ab", "12345", "x" * 65, "  sw-core01  ", "SW-CORE01", "acc-sw2"],
        enabled=lambda: True,
    )
    assert cache.get() == frozenset({"sw-core01", "acc-sw2"})


def test_loader_failure_returns_empty_set_and_logs_debug(caplog):
    def broken_loader():
        raise RuntimeError('relation "devices" does not exist')

    cache = KnownDeviceNameCache(loader=broken_loader, enabled=lambda: True)
    with caplog.at_level(logging.DEBUG, logger=known_identifiers.__name__):
        assert cache.get() == frozenset()
    assert any(KNOWN_HOSTNAMES_UNAVAILABLE in record.getMessage() for record in caplog.records)


def test_cache_ttl_uses_injected_clock():
    now = [1000.0]
    calls = []
    batches = [["sw-core01"], ["sw-core01", "acc-sw2"]]

    def loader():
        calls.append(now[0])
        return batches[min(len(calls) - 1, 1)]

    cache = KnownDeviceNameCache(loader=loader, clock=lambda: now[0], ttl_seconds=300, enabled=lambda: True)
    assert cache.get() == frozenset({"sw-core01"})
    version = cache.version
    now[0] += 299
    assert cache.get() == frozenset({"sw-core01"})
    assert len(calls) == 1
    now[0] += 2
    assert cache.get() == frozenset({"sw-core01", "acc-sw2"})
    assert len(calls) == 2
    assert cache.version > version


def test_default_ttl_reads_setting(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "AI_KNOWN_HOSTNAME_TTL_SECONDS", 10, raising=False)
    now = [0.0]
    calls = []
    cache = KnownDeviceNameCache(loader=lambda: calls.append(1) or ["sw-core01"], clock=lambda: now[0], enabled=lambda: True)
    cache.get()
    now[0] = 11
    cache.get()
    assert len(calls) == 2
