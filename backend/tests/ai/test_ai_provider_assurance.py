from __future__ import annotations

import pytest

from ai.security.gateway import AISecurityGateway, SecurityBlocked, SecurityPolicy


def _gateway(*, classifications=("PUBLIC", "INTERNAL", "CONFIDENTIAL")) -> AISecurityGateway:
    return AISecurityGateway(
        policy=SecurityPolicy(
            external_ai_enabled=True,
            allowed_provider_types=("deepseek", "local", "ollama"),
            allowed_classifications=classifications,
            allowed_data_regions=("unknown", "cn", "global"),
            identifiers_must_be_tokenized=False,
        )
    )


def test_internal_cloud_does_not_require_supplier_assurance() -> None:
    gateway = _gateway()
    payload = gateway.protect(
        [{"role": "user", "content": "请说明园区交换机的 VLAN 规划"}],
        provider_type="deepseek",
        data_classification="INTERNAL",
        data_region="cn",
        provider_allowed_classification="INTERNAL",
        provider_no_training_confirmed=True,
        provider_retention_days=30,
        provider_data_processing_agreement_ref="dpa-2026-001",
    )
    assert payload.metadata["classification"] == "INTERNAL"

    # Supplier assurance fields are no longer part of the Provider setup
    # flow.  They remain accepted as legacy arguments for compatibility, but
    # they must not be required for an otherwise allowed INTERNAL request.
    payload_without_legacy_assurance = gateway.protect(
        [{"role": "user", "content": "请说明园区交换机的 VLAN 规划"}],
        provider_type="deepseek",
        data_classification="INTERNAL",
        data_region="cn",
        provider_allowed_classification="INTERNAL",
    )
    assert payload_without_legacy_assurance.metadata["classification"] == "INTERNAL"


def test_cloud_confidential_is_blocked_but_local_is_allowed() -> None:
    gateway = _gateway()
    with pytest.raises(SecurityBlocked) as exc:
        gateway.protect(
            [{"role": "user", "content": "设备序列号 SN-EXAMPLE-001"}],
            provider_type="deepseek",
            data_classification="CONFIDENTIAL",
            data_region="cn",
            provider_allowed_classification="CONFIDENTIAL",
        )
    assert exc.value.reason_code == "AI_SECURITY_CLASSIFICATION_DENIED"

    payload = gateway.protect(
        [{"role": "user", "content": "设备序列号 SN-EXAMPLE-001"}],
        provider_type="local",
        data_classification="CONFIDENTIAL",
        data_region="unknown",
        provider_allowed_classification="CONFIDENTIAL",
    )
    assert payload.metadata["classification"] == "CONFIDENTIAL"

