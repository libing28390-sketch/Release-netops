"""Batch 6 guardrails: output review (model output is untrusted).

* identity-card, bank-card and mobile numbers the model produced are masked;
* "密码是Huawei@123"-style values are redacted, the keyword is kept;
* values restored from the caller's own tokens are shown unchanged;
* the streaming resolver holds a number or a Chinese credential assignment
  that is split across provider chunks, so no half is emitted unmasked.

Valid numbers are generated with the same check-digit helpers the detector
uses instead of being hard-coded.
"""

from __future__ import annotations

from ai.security.classification import cn_id_checksum_ok, luhn_ok
from ai.security.output import StreamingOutputResolver, mask_personal_info, sanitize_output
from ai.security.tokenization import ScopedTokenVault

_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)


def make_id(first17: str = "11010519491231002") -> str:
    value = first17 + "10X98765432"[sum(int(d) * w for d, w in zip(first17, _ID_WEIGHTS)) % 11]
    assert cn_id_checksum_ok(value)
    return value


def make_card(prefix: str) -> str:
    for digit in "0123456789":
        if luhn_ok(prefix + digit):
            return prefix + digit
    raise AssertionError("no Luhn digit")


def wrong_check_digit(value: str) -> str:
    replacement = "0" if value[-1] != "0" else "1"
    bad = value[:-1] + replacement
    assert not cn_id_checksum_ok(bad)
    return bad


def _sanitize(text: str, vault: ScopedTokenVault | None = None) -> str:
    return sanitize_output(text, tenant_id="tenant-a", task_id="task-1", vault=vault or ScopedTokenVault(ttl_seconds=120))


def _stream(chunks: list[str], vault: ScopedTokenVault | None = None) -> list[str]:
    resolver = StreamingOutputResolver(tenant_id="tenant-a", task_id="task-1", vault=vault or ScopedTokenVault(ttl_seconds=120))
    out = [resolver.push(chunk) for chunk in chunks]
    out.append(resolver.flush())
    return out


# ── non-streaming ────────────────────────────────────────────────────────


def test_identity_card_with_valid_check_digit_is_masked():
    id_number = make_id()
    result = _sanitize(f"该用户身份证号是{id_number}。")
    assert id_number not in result
    assert f"{id_number[:3]}{'*' * 11}{id_number[-4:]}" in result


def test_identity_card_with_wrong_check_digit_is_not_masked():
    bad = wrong_check_digit(make_id())
    assert _sanitize(f"编号{bad}不是身份证") == f"编号{bad}不是身份证"


def test_grouped_bank_card_keeps_only_the_last_four_digits():
    card = make_card("436742123456789")
    grouped = " ".join(card[i:i + 4] for i in range(0, 16, 4))
    result = _sanitize(f"这张卡 {grouped} 已冻结")
    assert grouped not in result
    assert f"**** **** **** {card[-4:]}" in result


def test_unionpay_card_without_keyword_is_masked():
    card = make_card("622202123456789012")
    result = _sanitize(f"62 开头：{card}")
    assert card not in result and result.endswith(card[-4:])


def test_bank_card_after_keyword_is_masked():
    card = make_card("436742123456789")
    assert _sanitize(f"卡号{card}请核对") == f"卡号{'*' * 12}{card[-4:]}请核对"


def test_mobile_number_after_phone_keyword_is_masked():
    assert _sanitize("请联系电话13812345678") == "请联系电话138****5678"
    assert _sanitize("号码+86 138-1234-5678") == "号码+86 138-****-5678"


def test_long_counter_without_keyword_is_not_masked():
    assert _sanitize("共收到13912345678个报文") == "共收到13912345678个报文"


def test_identity_card_restored_from_the_users_token_is_not_masked():
    vault = ScopedTokenVault(ttl_seconds=120)
    id_number = make_id()
    token = vault.put(id_number, kind="IDCARD", tenant_id="tenant-a", task_id="task-1")
    assert _sanitize(f"你的身份证 {token} 已登记", vault) == f"你的身份证 {id_number} 已登记"


def test_chinese_credential_value_is_redacted_and_keyword_kept():
    assert _sanitize("密码是Huawei@123，请尽快修改") == "密码是<REDACTED_CREDENTIAL>，请尽快修改"
    assert _sanitize("口令：P@ssw0rd!") == "口令：<REDACTED_CREDENTIAL>"


def test_chinese_credential_prose_is_unchanged():
    for text in ("密码长度为8-16位", "RSA密钥为2048位", "密码：******", "密码为空", "请定期修改密码"):
        assert _sanitize(text) == text


def test_existing_output_rules_still_hold():
    assert _sanitize("<script>alert(1)</script>ok") == "ok"
    assert _sanitize("threshold > 80% <REDACTED>") == "threshold > 80% <REDACTED>"


def test_mask_personal_info_uses_the_prefix_for_keywords():
    assert mask_personal_info("13812345678", prefix="联系电话：") == "138****5678"
    assert mask_personal_info("13812345678") == "13812345678"


# ── streaming ────────────────────────────────────────────────────────────


def test_streamed_identity_card_split_across_chunks_is_masked():
    id_number = make_id()
    out = _stream([f"身份证 {id_number[:9]}", f"{id_number[9:]} 已核验"])
    combined = "".join(out)
    assert id_number not in combined
    assert all(id_number[:9] not in part for part in out)
    assert f"{id_number[:3]}{'*' * 11}{id_number[-4:]}" in combined


def test_streamed_mobile_number_uses_keyword_from_previous_chunk():
    out = _stream(["请拨打电话", "13812345678 联系"])
    assert "".join(out) == "请拨打电话138****5678 联系"


def test_streamed_chinese_credential_value_split_in_two_is_redacted():
    for chunks in (["管理员密码是Hua", "wei@123，记得改"], ["管理员密", "码是Huawei@123，记得改"]):
        combined = "".join(_stream(chunks))
        assert "Huawei@123" not in combined and "Hua" not in combined.replace("<REDACTED_CREDENTIAL>", "")
        assert combined == "管理员密码是<REDACTED_CREDENTIAL>，记得改"


def test_streamed_harmless_text_is_emitted_immediately():
    resolver = StreamingOutputResolver(tenant_id="tenant-a", task_id="task-1", vault=ScopedTokenVault(ttl_seconds=120))
    assert resolver.push("stream-ok") == "stream-ok"
    assert resolver.flush() == ""


def test_streamed_trailing_number_is_released_by_the_next_chunk():
    assert _stream(["VLAN 200", " 已创建"]) == ["VLAN ", "200 已创建", ""]


def test_streamed_tokens_still_resolve_across_chunks():
    vault = ScopedTokenVault(ttl_seconds=120)
    token = vault.put("192.0.2.10", kind="IP", tenant_id="tenant-a", task_id="task-1")
    out = _stream([f"See https://example.com and {token[:12]}", f"{token[12:]} in the answer."], vault)
    assert out[0] == "See https://example.com and "
    assert out[1] == "192.0.2.10 in the answer."
