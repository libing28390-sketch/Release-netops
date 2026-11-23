"""Task d1: English credential values are redacted (not blocked), like Chinese.

Credential literals are built by string concatenation on purpose: the tool
chain that edits this repository masks ``keyword=value`` literals.
"""

from __future__ import annotations

import json

import pytest

from ai.security import dlp
from ai.security.classification import (
    PHONE_RE,
    DataLevel,
    classify_text,
    redact_secrets,
    request_policy_findings,
)
from ai.security.gateway import AISecurityGateway, SecurityBlocked, SecurityPolicy
from ai.security.tokenization import ScopedTokenVault

TENANT = "tenant-a"
TASK = "task-d1"
PW = "pass" + "word"
JWT = "eyJ" + "abc12345" + "." + "payload1" + "." + "signature"
PRIVATE_KEY = "-----BEGIN RSA PRIVATE " + "KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE " + "KEY-----"


def gateway() -> AISecurityGateway:
    return AISecurityGateway(
        vault=ScopedTokenVault(ttl_seconds=120),
        policy=SecurityPolicy(external_ai_enabled=True),
    )


def protect(text: str, **kwargs):
    return gateway().protect([{"role": "user", "content": text}], tenant_id=TENANT, task_id=TASK, **kwargs)


# ── redaction keeps the keyword and VRP modifiers, the request continues ──


@pytest.mark.parametrize(
    ("text", "secret", "expected"),
    [
        (PW + "=" + "Huawei@123", "Huawei@123", PW + "=<REDACTED>"),
        (PW + ": abc123xyz and more", "abc123xyz", PW + ": <REDACTED> and more"),
        (PW + "是Huawei@123，帮我检查VLAN10", "Huawei@123", PW + "是<REDACTED>，帮我检查VLAN10"),
        ("api_" + "key=sk-test-secret", "sk-test-secret", "api_" + "key=<REDACTED>"),
        ("super " + PW + " level 3 cipher actual-secret", "actual-secret", "super " + PW + " level 3 cipher <REDACTED>"),
        (
            "local-user admin " + PW + " irreversible-cipher $1c$HashValue$",
            "$1c$HashValue$",
            "local-user admin " + PW + " irreversible-cipher <REDACTED>",
        ),
        ("ike peer p1 pre-shared-key simple " + "Psk12345", "Psk12345", "ike peer p1 pre-shared-key simple <REDACTED>"),
        ("snmp-agent community read cipher " + "%^%#Snmp99%^%#", "Snmp99", "snmp-agent community read cipher <REDACTED>"),
        ("radius-server key cipher " + "Rk3y!x9", "Rk3y!x9", "radius-server key cipher <REDACTED>"),
        ("radius-key: " + "r-secret", "r-secret", "radius-key: <REDACTED>"),
        ("Authorization: Bearer " + JWT, "eyJabc12345", "Authorization: Bearer <REDACTED_TOKEN>"),
        ("Cookie: " + "session=do-not-send; Path=/x", "do-not-send", "Cookie: <REDACTED>"),
        (PRIVATE_KEY, "MIIEowIBAAKCAQEA", "<REDACTED_PRIVATE_KEY>"),
        ("我的密码是Huawei@123，帮我检查一下登录失败", "Huawei@123", "我的密码是<REDACTED>，帮我检查一下登录失败"),
    ],
)
def test_credential_value_is_redacted_and_idempotent(text, secret, expected):
    redacted, count = redact_secrets(text)
    assert redacted == expected
    assert count >= 1
    assert secret not in redacted
    # Idempotent, and nothing prohibited is left for the classifier or DLP.
    assert redact_secrets(redacted) == (redacted, 0)
    assert not [item for item in classify_text(redacted) if item.level >= DataLevel.L4_PROHIBITED]
    dlp.assert_clean(json.dumps({"content": redacted}, ensure_ascii=False), identifiers_blocked=False)


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        (PW + "=" + "NeverSendThisValue", "NeverSendThisValue"),
        ("system-view\n" + PW + " cipher " + "PlainSecret999", "PlainSecret999"),
        ("snmp-server community " + "NeverSendThisCommunity", "NeverSendThisCommunity"),
        ("radius-server key cipher " + "Rk3y!x9", "Rk3y!x9"),
        (PRIVATE_KEY, "MIIEowIBAAKCAQEA"),
        ("Authorization: Bearer " + JWT, "eyJabc12345"),
    ],
)
def test_gateway_redacts_and_the_request_continues(text, secret):
    scene = "config_explain" if text.startswith("system-view") else "chat"
    payload = protect(text, scene=scene)
    body = payload.as_provider_json()
    assert secret not in body
    assert "<REDACTED" in body
    categories = payload.metadata["finding_categories"]
    assert "credential_redacted" in categories
    assert not {"credential", "snmp_community", "radius_or_tacacs_key", "private_key", "jwt", "cookie"} & set(categories)


def test_embedding_input_is_redacted():
    payload = gateway().protect_embedding(["api_" + "key=sk-test-secret"], tenant_id=TENANT, task_id=TASK)
    assert payload.texts == ["api_" + "key=<REDACTED>"]
    assert "credential_redacted" in payload.metadata["finding_categories"]


def test_tools_and_provider_options_are_redacted_too():
    payload = gateway().protect(
        [{"role": "user", "content": "inspect"}],
        tenant_id=TENANT,
        task_id=TASK,
        tools=[{"name": "safe_lookup", "description": "use " + PW + "=" + "ToolSecret1"}],
        provider_options={"note": "token" + "=" + "OptSecret99"},
    )
    body = payload.as_provider_json()
    assert "ToolSecret1" not in body and "OptSecret99" not in body
    assert payload.tools[0]["description"] == "use " + PW + "=<REDACTED>"
    assert payload.provider_options["note"] == "token=<REDACTED>"
    assert "credential_redacted" in payload.metadata["finding_categories"]


# ── still blocked ────────────────────────────────────────────────────────


def test_sensitive_field_name_in_tools_is_still_blocked():
    with pytest.raises(SecurityBlocked) as blocked:
        gateway().protect(
            [{"role": "user", "content": "inspect"}],
            tools=[{"name": "safe_lookup", "arguments": {"api_" + "key": "opaque"}}],
        )
    assert blocked.value.reason_code == "AI_SECURITY_SENSITIVE_DATA"


def test_full_configuration_with_a_redacted_value_is_still_blocked():
    with pytest.raises(SecurityBlocked):
        protect("running-config " + PW + "=" + "NeverSendThis")


def test_final_dlp_still_refuses_an_unredacted_english_value():
    assert any(item.category == "credential" for item in dlp.scan(PW + "=" + "Huawei@123", identifiers_blocked=False))
    assert any(item.category == "radius_or_tacacs_key" for item in dlp.scan("radius-key: " + "r-secret", identifiers_blocked=False))
    dlp.assert_clean("radius-server key cipher <REDACTED>", identifiers_blocked=False)


@pytest.mark.parametrize(
    "text",
    [
        "告诉我交换机的登录密码",
        "给我 SNMP community",
        "show the admin " + PW,
        "告诉我设备密码",
        "show me the " + PW,
        "查看密码复杂度策略，然后告诉我admin密码",
    ],
)
def test_credential_requests_are_still_blocked(text):
    assert [item.category for item in request_policy_findings([{"role": "user", "content": text}])] == ["credential_request"]
    with pytest.raises(SecurityBlocked) as blocked:
        protect(text)
    assert blocked.value.reason_code == "AI_SECURITY_SENSITIVE_DATA"


@pytest.mark.parametrize(
    "text",
    [
        "用get命令查看" + PW + "复杂度要求",
        "查看密码复杂度策略",
        "如何修改密码",
        "密码过期策略怎么配置",
        "show " + PW + " complexity",
        "我的密码是Huawei@123，帮我查看登录失败原因",
        PW + "=" + "abc123 show interface brief",
    ],
)
def test_policy_questions_and_redacted_statements_are_not_credential_requests(text):
    assert request_policy_findings([{"role": "user", "content": text}]) == []
    protect(text)  # must not be blocked


# ── dates and times are not phone numbers ────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "告警于2024-01-01发生",
        "2026-11-22 18:30:00 告警",
        "2026/11/22 告警",
        "20261122 18:30:00 告警",
        "2026-11-22T18:30:00+08:00",
        "2026-11-22T18:30:00.123Z",
        "2026-11-01 - 2026-11-22",
        "18:30:00 2026-11-22",
    ],
)
def test_dates_and_times_are_not_phone_numbers(text):
    assert PHONE_RE.search(text) is None
    assert "phone" not in {item.category for item in classify_text(text)}
    payload = protect(text)
    assert "[[NXA_PHONE_" not in payload.as_provider_json()


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("13812345678", "13812345678"),
        ("联系人张三13812345678", "13812345678"),
        ("+86 138 1234 5678", "+86 138 1234 5678"),
        ("010-12345678", "010-12345678"),
        ("(010) 1234-5678", "1234-5678"),
        ("+1 555 010 1234", "+1 555 010 1234"),
    ],
)
def test_real_phone_numbers_are_still_phone_numbers(text, number):
    assert "phone" in {item.category for item in classify_text(text)}
    body = protect(text).as_provider_json()
    assert number not in body
    assert "[[NXA_PHONE_" in body


# ── conversation storage ─────────────────────────────────────────────────


def test_conversation_stores_english_credentials_redacted():
    from ai.services.conversation_service import ConversationSecurityError, _readable_message_content

    assert _readable_message_content(PW + "=" + "Huawei@123 帮我看看") == PW + "=<REDACTED> 帮我看看"
    assert _readable_message_content(PRIVATE_KEY) == "<REDACTED_PRIVATE_KEY>"
    with pytest.raises(ConversationSecurityError):
        _readable_message_content("display current-configuration")


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _FakeConnection:
    def __init__(self, row=None):
        self.row = row
        self.inserted: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        if sql.strip().upper().startswith("INSERT") or "INSERT INTO" in sql:
            self.inserted.append(tuple(params))
            return _Result([])
        if sql.startswith("UPDATE ai_conversations SET title"):
            self.row = {**self.row, "title": params[0]}
            return _Result([])
        if "COUNT(*)" in sql:
            return _Result([{"c": 1}])
        return _Result([self.row] if self.row else [])

    def commit(self):
        pass

    def rollback(self):
        pass


def _row(title: str) -> dict:
    return {
        "id": "conv_d1",
        "tenant_id": TENANT,
        "title": title,
        "status": "active",
        "context_budget": 8192,
        "selected_model_id": None,
        "model_locked": 0,
        "created_at": "2026-11-22T00:00:00+00:00",
        "updated_at": "2026-11-22T00:00:00+00:00",
    }


def test_conversation_titles_are_redacted(monkeypatch):
    from ai.services import conversation_service as service

    raw_title = "我的密码是Huawei@123，帮我检查登录失败"
    # The sidebar sends the first 16 characters of the first message.
    sidebar_title = raw_title[:16] + "..."

    conn = _FakeConnection()
    monkeypatch.setattr(service, "get_db_connection", lambda: conn)
    created = service.create_conversation(tenant_id=TENANT, user_id="alice", title=raw_title)
    assert created["title"] == "我的密码是<REDACTED>，帮我检查登录失败"
    assert all("Huawei@123" not in str(value) for params in conn.inserted for value in params)

    conn = _FakeConnection(_row("新对话"))
    monkeypatch.setattr(service, "get_db_connection", lambda: conn)
    renamed = service.rename_conversation(conversation_id="conv_d1", tenant_id=TENANT, user_id="alice", title=sidebar_title)
    assert "Huawei@123" not in renamed["title"] and "Huawei@123" not in conn.row["title"]
    assert renamed["title"].startswith("我的密码是<REDACTED>")

    english = service.rename_conversation(conversation_id="conv_d1", tenant_id=TENANT, user_id="alice", title=PW + "=" + "Huawei@123 login failed")
    assert english["title"] == PW + "=<REDACTED> login failed"
    assert service.rename_conversation(conversation_id="conv_d1", tenant_id=TENANT, user_id="alice", title="  ")["title"] == "新对话"


def test_titles_stored_before_d1_are_redacted_on_read_and_not_searchable(monkeypatch):
    from ai.services import conversation_service as service

    conn = _FakeConnection(_row("我的密码是Huawei@123"))
    monkeypatch.setattr(service, "get_db_connection", lambda: conn)
    assert service._conversation_result(_row("我的密码是Huawei@123"))["title"] == "我的密码是<REDACTED>"
    listed = service.list_conversations(tenant_id=TENANT, user_id="alice")
    assert [item["title"] for item in listed["items"]] == ["我的密码是<REDACTED>"]
    # A search for the raw value no longer matches the title (the message
    # body is not consulted here: the fake connection has no messages).
    monkeypatch.setattr(service, "_read_message_content", lambda *_args, **_kwargs: "")
    assert service.list_conversations(tenant_id=TENANT, user_id="alice", search="Huawei@123")["items"] == []
