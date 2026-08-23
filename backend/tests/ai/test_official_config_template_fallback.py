from __future__ import annotations

from types import SimpleNamespace


def test_official_template_fallback_is_vendor_and_model_scoped(isolated_db):
    from ai.services.rag_retriever import RetrievalRequest
    from services.official_config_template_service import search_official_templates

    huawei = RetrievalRequest(
        query="华为交换机 S5700 OSPF 配置",
        vendor="Huawei",
        product_series="S5700",
        document_category="configuration",
        feature="ospf",
    )
    chunks = search_official_templates(huawei)
    assert chunks
    assert chunks[0]["vendor"] == "Huawei"
    assert chunks[0]["knowledge_source_type"] == "official_template"
    assert "S5700" in chunks[0]["document_name"]
    assert chunks[0]["metadata"]["official_only"] is True

    wrong_model = RetrievalRequest(
        query="华为交换机 S5735 OSPF 配置",
        vendor="Huawei",
        product_series="S5735",
        document_category="configuration",
        feature="ospf",
    )
    assert search_official_templates(wrong_model) == []


def test_official_template_fallback_covers_h3c_and_cisco_nexus(isolated_db):
    from ai.services.rag_retriever import RetrievalRequest
    from services.official_config_template_service import search_official_templates

    h3c = search_official_templates(
        RetrievalRequest(
            query="H3C Comware OSPF 配置",
            vendor="H3C",
            product_family="Comware 7 Switches",
            document_category="configuration",
            feature="ospf",
        )
    )
    assert h3c and h3c[0]["platform"] == "h3c_comware"

    nexus = search_official_templates(
        RetrievalRequest(
            query="Cisco Nexus 9000 OSPF 配置",
            vendor="Cisco",
            product_series="Nexus 9000",
            document_category="configuration",
            feature="ospf",
        )
    )
    assert nexus and nexus[0]["platform"] == "cisco_nxos"


def test_official_template_fallback_covers_data_center_vxlan_and_parser_scope(isolated_db):
    from ai.services.intent_parser import intent_parser
    from ai.services.rag_retriever import RetrievalRequest
    from services.official_config_template_service import search_official_templates

    import asyncio

    parsed = asyncio.run(intent_parser.parse_intent("Cisco Nexus 9000 VXLAN EVPN配置"))
    metadata = parsed["knowledge_intent"]
    assert metadata["product_series"] == "Nexus 3000/9000"
    assert metadata["feature"] == "vxlan"
    request = RetrievalRequest(
        query="Cisco Nexus 9000 VXLAN EVPN配置",
        **{key: value for key, value in metadata.items() if key in RetrievalRequest.__dataclass_fields__},
    )
    chunks = search_official_templates(request)
    assert chunks and chunks[0]["platform"] == "cisco_nxos"
    assert "feature vn-segment" in chunks[0]["content"]


def test_official_template_render_never_exposes_jinja_source_or_secret_values():
    from ai.services.assistant import AIAssistantService
    from services.official_config_template_service import _render_template

    rendered = _render_template(
        'system-view\nvlan {{ vlan_id | default(10) }}\n'
        'snmp-agent usm-user {{ snmp_user | default("nms-user") }} '
        'authentication-mode sha {{ snmp_auth_key }}'
    )
    assert "{{" not in rendered
    assert "vlan 10" in rendered
    assert "<from-secret-vault:snmp_auth_key>" in rendered

    answer = AIAssistantService()._knowledge_fallback_answer(
        [
            {
                "platform": "huawei_vrp",
                "document_category": "configuration",
                "template_id": "official-huawei-vlan-basic",
                "knowledge_source_type": "official_template",
                "document_name": "VLAN 创建（华为 VRP）",
                "content": "system-view\nvlan 10\nquit\n\ndisplay vlan 10",
                "rollback": "system-view\nundo vlan 10\nreturn",
                "description": "创建业务 VLAN。",
                "software_release": "V200R023",
                "official_source": "https://support.huawei.com/enterprise/",
            }
        ],
        request=SimpleNamespace(document_category="configuration", feature="vlan"),
    )
    assert "Huawei VRP" in answer
    assert "VLAN 创建（华为 VRP）" in answer
    assert "配置步骤" in answer
    assert "验证命令" in answer
    assert "回滚命令" in answer
    assert "General Overview" not in answer
