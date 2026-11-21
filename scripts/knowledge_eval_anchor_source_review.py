"""Build a source-backed 50-anchor Gold candidate without overwriting v1.

This utility records the automated source review performed against official
vendor documentation.  It corrects the anchors whose v1 Gold IDs were
demonstrably unrelated to their queries and proposes explicit feature labels
for the remaining unambiguous answer cases.  It deliberately does not
populate ``reviewer``/``reviewed_at`` as a human approval or change the
default CI dataset; those fields remain a separate human-signoff contract.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-golden-anchors-50.yaml"
DEFAULT_DATASET_OUTPUT = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-golden-anchors-50-source-reviewed-v2.yaml"
DEFAULT_REPORT_OUTPUT = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-golden-anchors-50-source-review.json"


CORRECTIONS: dict[str, dict[str, Any]] = {
    "ANCHOR-003": {
        "gold_document_ids": [
            "official-template-official-huawei-ce6885-interface-status-diagnostic",
            "official-template-official-huawei-access-port",
            "official-template-official-huawei-trunk-port",
        ],
        "feature": "interface",
        "feature_scope": ["interface", "access_port", "trunk"],
        "source_urls": [
            "https://info.support.huawei.com/info-finder/search-center/en/enterprise/wlan/ce6885-48ys8cq-pid-257795345/commands",
            "https://info.support.huawei.com/enterprise/en/doc/EDOC1100333403/cdd85713/basic-interface-configuration-commands",
            "https://info.support.huawei.com/enterprise/en/doc/EDOC1100419268/221a9cda/configuration-examples-for-vlans",
        ],
        "rationale": "The query combines CE6885 interface-state verification with uplink configuration; the explicit scope therefore includes the official interface-status, access-port and trunk identities instead of forcing one feature label.",
    },
    "ANCHOR-004": {
        "gold_document_ids": [
            "official-template-official-cisco-interface-switchport-basic",
            "official-template-official-cisco-access-port",
            "official-template-official-cisco-trunk-port",
        ],
        "feature": "interface",
        "feature_scope": ["interface", "access_port", "trunk"],
        "source_urls": [
            "https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/infra/interface-characteristics/interface-characteristics-configuration-guide.html",
            "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-3/configuration_guide/vlan/b_173_vlan_9400_cg.pdf",
        ],
        "rationale": "Cisco documents Layer 2 switchports as access or trunk ports; the dedicated interface-switchport projection plus both feature-specific projections are all acceptable identities.",
    },
    "ANCHOR-017": {
        "gold_document_ids": ["official-template-official-huawei-ce12800-vxlan-evpn-basic"],
        "feature": "vxlan",
        "source_urls": ["https://info.support.huawei.com/enterprise/zh/doc/EDOC1100420462/b4590a84"],
        "rationale": "The query names CE12800 and VXLAN EVPN; the existing CE6800-only ID was a product-scope mismatch.",
    },
    "ANCHOR-018": {
        "gold_document_ids": ["official-template-official-huawei-port-security-basic"],
        "feature": "port_security",
        "source_urls": ["https://info.support.huawei.com/hedex/api/pages/EDOC1000053358/YEF0907R/25/resources/en-us_task_0133020498.html"],
        "rationale": "The query explicitly asks for port-security enable and MAC limits; access-port configuration is not semantically acceptable.",
    },
    "ANCHOR-019": {
        "gold_document_ids": ["official-template-official-huawei-cpu-memory-diagnostic"],
        "feature": "system_monitoring",
        "source_urls": ["https://info.support.huawei.com/enterprise/en/doc/EDOC1100333828/91652f17/device-status-checking-commands"],
        "rationale": "The query is a read-only CPU/memory diagnostic; a trunk-port template is unrelated.",
    },
    "ANCHOR-026": {
        "gold_document_ids": ["official-template-official-cisco-arp-mac-diagnostic"],
        "feature": "arp",
        "source_urls": ["https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipaddr_arp/configuration/xe-3s/arp-xe-3s-book.pdf"],
        "rationale": "The query asks for show ip arp and show mac address-table; an access-port configuration template is unrelated.",
    },
    "ANCHOR-030": {
        "gold_document_ids": ["official-template-official-h3c-interface-brief-diagnostic"],
        "feature": "interface",
        "source_urls": ["https://www.h3c.com/en/Support/Resource_Center/EN/Home/Routers/00-Public/Reference_Guides/Command_References/H3C_MSR_Comware_7_CR-R0615/03/202210/1709588_294551_0.htm"],
        "rationale": "The query explicitly asks for display interface brief; an access-port configuration template is not the same evidence.",
    },
    "ANCHOR-034": {
        "gold_document_ids": ["official-template-official-h3c-arp-mac-diagnostic"],
        "feature": "arp",
        "source_urls": ["https://www.h3c.com/en/Support/Resource_Center/EN/Home/Security/00-Public/Reference_Guides/Command_References/H3C_IPS_Comware_7_CR%28R8560_R8660%29/10/202205/1607637_294551_0.htm"],
        "rationale": "The query asks for display arp and display mac-address troubleshooting output; access-port configuration is unrelated.",
    },
    "ANCHOR-016": {
        "gold_document_ids": ["official-template-official-huawei-ospf-bfd-basic"],
        "feature": "bfd",
        "source_urls": [
            "https://info.support.huawei.com/hedex/api/pages/EDOC1100149311/AZJ0713J/18/resources/admin/sec_admin_router_ospf_0065.html",
            "https://info.support.huawei.com/hedex/api/pages/EDOC1100363264/AEN0403J/05/resources/vrp/dc_vrp_ospf_cfg_0054.html",
        ],
        "rationale": "The query explicitly asks for OSPF/BFD fast detection; a generic OSPF template does not prove the BFD subfeature.",
    },
    "ANCHOR-020": {
        "gold_document_ids": ["official-template-official-huawei-super-password-basic"],
        "feature": "pam",
        "source_urls": [
            "https://info.support.huawei.com/hedex/api/pages/EDOC1100149308/AEJ0713J/18/resources/cli_vrp/super_password_pesudo.html",
        ],
        "rationale": "The query asks for super password privilege-level configuration; the former generic AAA template was not a precise semantic match.",
    },
    "ANCHOR-028": {
        "gold_document_ids": ["official-template-official-cisco-aaa-authentication-basic"],
        "feature": "pam",
        "source_urls": [
            "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-13/configuration_guide/sec/b_1713_sec_9300_cg/configuring_authentication.html",
        ],
        "rationale": "The query asks for AAA login authentication and local fallback; the former generic AAA/SSH template did not identify this subfeature precisely.",
    },
}


# Existing projected official templates are source-backed through their
# ``official_reference`` metadata. Keeping the compact identity map here
# makes the candidate artifact reproducible without reading mutable database
# content or copying vendor pages into the repository.
SOURCE_DOCUMENTS: dict[str, dict[str, str]] = {
    "official-template-official-huawei-vlan-basic": {"vendor": "Huawei", "platform": "huawei_vrp", "feature": "vlan", "source_url": "https://info.support.huawei.com/enterprise/en/doc/EDOC1100419268/221a9cda/configuration-examples-for-vlans"},
    "official-template-official-huawei-vlanif": {"vendor": "Huawei", "platform": "huawei_vrp", "feature": "vlan", "source_url": "https://info.support.huawei.com/enterprise/en/doc/EDOC1100419268/221a9cda/configuration-examples-for-vlans"},
    "official-template-official-cisco-vlan-basic": {"vendor": "Cisco", "platform": "cisco_iosxe", "feature": "vlan", "source_url": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-3/configuration_guide/vlan/b_173_vlan_9400_cg.pdf"},
    "official-template-official-cisco-svi": {"vendor": "Cisco", "platform": "cisco_iosxe", "feature": "vlan", "source_url": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-3/configuration_guide/vlan/b_173_vlan_9400_cg.pdf"},
    "official-template-official-huawei-access-port": {"vendor": "Huawei", "platform": "huawei_vrp", "feature": "access_port", "source_url": "https://info.support.huawei.com/enterprise/en/doc/EDOC1100419268/221a9cda/configuration-examples-for-vlans"},
    "official-template-official-huawei-trunk-port": {"vendor": "Huawei", "platform": "huawei_vrp", "feature": "trunk", "source_url": "https://info.support.huawei.com/enterprise/en/doc/EDOC1100419268/221a9cda/configuration-examples-for-vlans"},
    "official-template-official-huawei-ce6885-interface-status-diagnostic": {"vendor": "Huawei", "platform": "huawei_vrp", "feature": "interface", "source_url": "https://info.support.huawei.com/enterprise/en/doc/EDOC1100333403/cdd85713/basic-interface-configuration-commands"},
    "official-template-official-cisco-interface-switchport-basic": {"vendor": "Cisco", "platform": "cisco_iosxe", "feature": "interface", "source_url": "https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/infra/interface-characteristics/interface-characteristics-configuration-guide.html"},
    "official-template-official-cisco-access-port": {"vendor": "Cisco", "platform": "cisco_iosxe", "feature": "access_port", "source_url": "https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/infra/interface-characteristics/interface-characteristics-configuration-guide.html"},
    "official-template-official-cisco-trunk-port": {"vendor": "Cisco", "platform": "cisco_iosxe", "feature": "trunk", "source_url": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-3/configuration_guide/vlan/b_173_vlan_9400_cg.pdf"},
    "official-template-official-huawei-s5700-ospf-basic": {"vendor": "Huawei", "platform": "huawei_vrp", "feature": "ospf", "source_url": "https://support.huawei.com/enterprise/en/doc/EDOC1100459443/d770f3cd/configuring-ospf-attributes-on-different-types-of-networks"},
    "official-template-official-cisco-c9300-ospf-basic": {"vendor": "Cisco", "platform": "cisco_iosxe", "feature": "ospf", "source_url": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-13/configuration_guide/rtng/b_1713_rtng_9300_cg/configuring_ospf.html"},
    "official-template-official-huawei-ssh-basic": {"vendor": "Huawei", "platform": "huawei_vrp", "feature": "ssh", "source_url": "https://support.huawei.com/enterprise/en/doc/EDOC1100459417/bbc53f99/command-support"},
    "official-template-official-huawei-aaa-local": {"vendor": "Huawei", "platform": "huawei_vrp", "feature": "ssh", "source_url": "https://info.support.huawei.com/hedex/api/pages/EDOC1100277644/AEM10221/03/resources/vrp/dc_vrp_aaa_cfg_1003.html"},
    "official-template-official-cisco-ssh-basic": {"vendor": "Cisco", "platform": "cisco_iosxe", "feature": "ssh", "source_url": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/16-10/configuration_guide/sys_mgmt/b_1610_sys_mgmt_9300_cg/administering_the_device.html"},
    "official-template-official-cisco-aaa-local": {"vendor": "Cisco", "platform": "cisco_iosxe", "feature": "ssh", "source_url": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/26-x/configuration_guide/sec/b_26x_sec_9300_cg/configuring_local_authentication_and_authorization.html"},
    "official-template-official-huawei-ntp-client-basic": {"vendor": "Huawei", "platform": "huawei_vrp", "feature": "ntp", "source_url": "https://support.huawei.com/enterprise/en/doc/EDOC1100420157/8169f6dd/example-for-configuring-authenticated-ntp-broadcast-mode"},
    "official-template-official-cisco-ntp-client-basic": {"vendor": "Cisco", "platform": "cisco_iosxe", "feature": "ntp", "source_url": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/16-10/configuration_guide/sys_mgmt/b_1610_sys_mgmt_9300_cg/administering_the_device.html"},
    "official-template-official-huawei-static-route-basic": {"vendor": "Huawei", "platform": "huawei_vrp", "feature": "static_route", "source_url": "https://support.huawei.com/enterprise/en/doc/DOC1000047418/bfd73d2e/static-route-configuration"},
    "official-template-official-cisco-static-route-basic": {"vendor": "Cisco", "platform": "cisco_iosxe", "feature": "static_route", "source_url": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-8/configuration_guide/rtng/b_178_rtng_9300_cg/protocol_independent_features.html"},
    "official-template-official-huawei-bgp-basic": {"vendor": "Huawei", "platform": "huawei_vrp", "feature": "bgp", "source_url": "https://support.huawei.com/enterprise/en/doc/EDOC1100214493/f0d8283e/network-bgp"},
    "official-template-official-huawei-ce6800-bgp-basic": {"vendor": "Huawei", "platform": "huawei_vrp", "feature": "bgp", "source_url": "https://support.huawei.com/enterprise/en/doc/EDOC1100463796/5d103d4d/establishing-vxlan-tunnels-in-bgp-evpn-mode-distributed-vxlan-gateway"},
    "official-template-official-huawei-eth-trunk": {"vendor": "Huawei", "platform": "huawei_vrp", "feature": "lacp", "source_url": "https://info.support.huawei.com/enterprise/en/doc/EDOC1100365019/493f7e15/example-for-configuring-stack-eth-trunks"},
    "official-template-official-huawei-acl-basic": {"vendor": "Huawei", "platform": "huawei_vrp", "feature": "acl", "source_url": "https://support.huawei.com/enterprise/en/doc/EDOC1100459417/bbc53f99/command-support"},
    "official-template-official-huawei-ce12800-vxlan-evpn-basic": {"vendor": "Huawei", "platform": "huawei_vrp", "feature": "vxlan", "source_url": "https://info.support.huawei.com/enterprise/zh/doc/EDOC1100420462/b4590a84"},
    "official-template-official-huawei-port-security-basic": {"vendor": "Huawei", "platform": "huawei_vrp", "feature": "port_security", "source_url": "https://info.support.huawei.com/hedex/api/pages/EDOC1000053358/YEF0907R/25/resources/en-us_task_0133020498.html"},
    "official-template-official-huawei-cpu-memory-diagnostic": {"vendor": "Huawei", "platform": "huawei_vrp", "feature": "system_monitoring", "source_url": "https://info.support.huawei.com/enterprise/en/doc/EDOC1100333828/91652f17/device-status-checking-commands"},
    "official-template-official-huawei-ospf-bfd-basic": {"vendor": "Huawei", "platform": "huawei_vrp", "feature": "bfd", "source_url": "https://info.support.huawei.com/hedex/api/pages/EDOC1100149311/AZJ0713J/18/resources/admin/sec_admin_router_ospf_0065.html"},
    "official-template-official-huawei-super-password-basic": {"vendor": "Huawei", "platform": "huawei_vrp", "feature": "pam", "source_url": "https://info.support.huawei.com/hedex/api/pages/EDOC1100149308/AEJ0713J/18/resources/cli_vrp/super_password_pesudo.html"},
    "official-template-official-cisco-nexus-bgp-basic": {"vendor": "Cisco", "platform": "cisco_nxos", "feature": "bgp", "source_url": "https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/6-x/unicast/configuration/guide/l3_cli_nxos.pdf"},
    "official-template-official-cisco-lacp-port-channel": {"vendor": "Cisco", "platform": "cisco_iosxe", "feature": "lacp", "source_url": "https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/lyr2-fwd/etherchannel/etherchannel-configuration-guide/etherchannels.html"},
    "official-template-official-cisco-acl-basic": {"vendor": "Cisco", "platform": "cisco_iosxe", "feature": "acl", "source_url": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-13/configuration_guide/sec/b_1713_sec_9300_cg/configuring_ipv4_acls.html"},
    "official-template-official-cisco-arp-mac-diagnostic": {"vendor": "Cisco", "platform": "cisco_iosxe", "feature": "arp", "source_url": "https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipaddr_arp/configuration/xe-3s/arp-xe-3s-book.pdf"},
    "official-template-official-cisco-hsrp-basic": {"vendor": "Cisco", "platform": "cisco_iosxe", "feature": "hsrp", "source_url": "https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/ntw-servs/b-network-services/m_fhp-hsrp-0.html"},
    "official-template-official-cisco-aaa-authentication-basic": {"vendor": "Cisco", "platform": "cisco_iosxe", "feature": "pam", "source_url": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-13/configuration_guide/sec/b_1713_sec_9300_cg/configuring_authentication.html"},
    "official-template-official-h3c-vlan-basic": {"vendor": "H3C", "platform": "h3c_comware", "feature": "vlan", "source_url": "https://www.h3c.com/en/d_201905/1189999_294551_0.htm"},
    "official-template-official-h3c-trunk-port": {"vendor": "H3C", "platform": "h3c_comware", "feature": "trunk", "source_url": "https://www.h3c.com/en/d_201905/1189999_294551_0.htm"},
    "official-template-official-h3c-interface-brief-diagnostic": {"vendor": "H3C", "platform": "h3c_comware", "feature": "interface", "source_url": "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Routers/00-Public/Reference_Guides/Command_References/H3C_MSR_Comware_7_CR-R0615/03/202210/1709588_294551_0.htm"},
    "official-template-official-h3c-lacp-bridge-aggregation": {"vendor": "H3C", "platform": "h3c_comware", "feature": "lacp", "source_url": "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Configure___Deploy/Configuration_Guides/H3C_CG-26720/06/202506/2514322_294551_0.htm"},
    "official-template-official-h3c-bgp-basic": {"vendor": "H3C", "platform": "h3c_comware", "feature": "bgp", "source_url": "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/Technical_Documents/Configure___Deploy/Configuration_Guides/H3C_S6805_S9850_CGs_Release_671x-9253/05/202303/1790630_294551_0.htm"},
    "official-template-official-h3c-s6800-s9825-bgp-basic": {"vendor": "H3C", "platform": "h3c_comware", "feature": "bgp", "source_url": "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/Technical_Documents/Configure___Deploy/Configuration_Guides/H3C_CG-29160/06/202509/2657318_294551_0.htm"},
    "official-template-official-h3c-acl-basic": {"vendor": "H3C", "platform": "h3c_comware", "feature": "acl", "source_url": "https://www.h3c.com/en/d_202205/1607933_294551_0.htm"},
    "official-template-official-h3c-arp-mac-diagnostic": {"vendor": "H3C", "platform": "h3c_comware", "feature": "arp", "source_url": "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Security/00-Public/Reference_Guides/Command_References/H3C_IPS_Comware_7_CR%28R8560_R8660%29/10/202205/1607637_294551_0.htm"},
    "ruijie-rgos-vlan-access": {"vendor": "Ruijie", "platform": "ruijie_rgos", "feature": "vlan", "source_url": "https://www.ruijie.com.cn/fw/wt/35635/"},
    "ruijie-rgos-aggregateport": {"vendor": "Ruijie", "platform": "ruijie_rgos", "feature": "lacp", "source_url": "https://www.ruijie.com.cn/fw/wt/90880/"},
    "ruijie-rgos-show-route": {"vendor": "Ruijie", "platform": "ruijie_rgos", "feature": "static_route", "source_url": "https://www.ruijie.com.cn/fw/wt/37267/"},
    "ruijie-rgos-ospf": {"vendor": "Ruijie", "platform": "ruijie_rgos", "feature": "ospf", "source_url": "https://www.ruijie.com.cn/fw/wt/32518/"},
    "ruijie-rgos-show-lldp": {"vendor": "Ruijie", "platform": "ruijie_rgos", "feature": "lldp", "source_url": "https://www.ruijie.com.cn/fw/wt/18543/"},
    "ruijie-rgos-acl": {"vendor": "Ruijie", "platform": "ruijie_rgos", "feature": "acl", "source_url": "https://www.ruijie.com.cn/fw/wt/37269/"},
}


# A single ``feature`` field cannot faithfully represent a query whose
# acceptable set spans several feature labels. Store the primary intent and
# the complete accepted feature scope so the runner can measure pollution
# without silently rejecting a semantically valid supporting document.
FEATURE_SCOPE_PROPOSALS = {
    "ANCHOR-003": {
        "feature": "interface",
        "feature_scope": ["interface", "access_port", "trunk"],
        "rationale": "interface status plus uplink/access/trunk scope",
    },
    "ANCHOR-004": {
        "feature": "interface",
        "feature_scope": ["access_port", "trunk"],
        "rationale": "Cisco switchport configuration can be access or trunk",
    },
    "ANCHOR-029": {
        "feature": "vlan",
        "feature_scope": ["vlan", "trunk"],
        "rationale": "H3C trunk permit vlan all combines VLAN membership and trunk semantics",
    },
    "ANCHOR-049": {
        "feature": "vlan",
        "feature_scope": ["vlan", "access_port"],
        "rationale": "The typoed Huawei query explicitly contains both VLAN and access-port intent",
    },
}

FEATURE_PROPOSALS = {
    "ANCHOR-001": "vlan",
    "ANCHOR-002": "vlan",
    "ANCHOR-005": "ospf",
    "ANCHOR-006": "ospf",
    "ANCHOR-007": "ssh",
    "ANCHOR-008": "ssh",
    "ANCHOR-009": "ntp",
    "ANCHOR-010": "ntp",
    "ANCHOR-011": "static_route",
    "ANCHOR-012": "static_route",
    "ANCHOR-013": "bgp",
    "ANCHOR-014": "lacp",
    "ANCHOR-015": "acl",
    "ANCHOR-016": "bfd",
    "ANCHOR-017": "vxlan",
    "ANCHOR-018": "port_security",
    "ANCHOR-019": "system_monitoring",
    "ANCHOR-020": "pam",
    "ANCHOR-021": "trunk",
    "ANCHOR-022": "bgp",
    "ANCHOR-023": "lacp",
    "ANCHOR-024": "acl",
    "ANCHOR-025": "ospf",
    "ANCHOR-026": "arp",
    "ANCHOR-027": "hsrp",
    "ANCHOR-028": "pam",
    "ANCHOR-030": "interface",
    "ANCHOR-031": "lacp",
    "ANCHOR-032": "bgp",
    "ANCHOR-033": "acl",
    "ANCHOR-034": "arp",
    "ANCHOR-035": "vlan",
    "ANCHOR-036": "lacp",
    "ANCHOR-037": "static_route",
    "ANCHOR-038": "ospf",
    "ANCHOR-039": "lldp",
    "ANCHOR-040": "acl",
    "ANCHOR-041": "vlan",
}


def build_candidate(dataset: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = copy.deepcopy(dataset)
    candidate["dataset_id"] = "nexora-kb-eval-anchors-50-source-reviewed-v2-20260905"
    candidate["parent_dataset_id"] = dataset.get("dataset_id")
    candidate["status"] = "candidate"
    candidate["source_review_mode"] = "official_source_provenance_automated"
    candidate["human_review_required"] = True
    candidate["source_review_status"] = "complete_pending_human_signoff"
    candidate["source_review_artifact"] = "eval-golden-anchors-50-source-review.json"

    changes: list[dict[str, Any]] = []
    source_review_cases: list[dict[str, Any]] = []
    proposed_feature_cases: list[str] = []
    adjudication_cases: list[str] = []
    for case in candidate.get("cases", []):
        case_id = str(case.get("id") or "")
        correction = CORRECTIONS.get(case_id)
        if correction:
            previous_ids = list(case.get("gold_document_ids") or [])
            case["gold_document_ids"] = list(correction["gold_document_ids"])
            case["acceptable_document_ids"] = list(correction["gold_document_ids"])
            if correction.get("feature_scope"):
                case["feature_scope"] = list(correction["feature_scope"])
            changes.append(
                {
                    "case_id": case_id,
                    "previous_gold_document_ids": previous_ids,
                    "proposed_gold_document_ids": list(correction["gold_document_ids"]),
                    "feature_proposal": correction["feature"],
                    "feature_scope": list(correction.get("feature_scope") or []),
                    "source_urls": list(correction["source_urls"]),
                    "rationale": correction["rationale"],
                }
            )

        if str(case.get("expected_outcome") or "").strip().lower() != "answer":
            continue

        acceptable_ids = [
            str(item).strip()
            for item in (case.get("acceptable_document_ids") or case.get("gold_document_ids") or [])
            if str(item).strip()
        ]
        source_records = [
            {"document_id": document_id, **SOURCE_DOCUMENTS[document_id]}
            for document_id in acceptable_ids
            if document_id in SOURCE_DOCUMENTS
        ]
        if not source_records:
            continue

        # Make the reviewed candidate explicit for every source-backed answer
        # case.  The frozen v1 dataset predates this field and the audit tool
        # supports a gold_document_ids fallback, but a handoff/import consumer
        # should not need to infer the acceptable set from another field.
        case["acceptable_document_ids"] = acceptable_ids

        scope_proposal = FEATURE_SCOPE_PROPOSALS.get(case_id)
        proposed_feature = correction["feature"] if correction else (
            scope_proposal["feature"] if scope_proposal else FEATURE_PROPOSALS.get(case_id)
        )
        proposed_feature_scope = correction.get("feature_scope") if correction else (
            scope_proposal["feature_scope"] if scope_proposal else None
        )
        if proposed_feature:
            # This is a candidate annotation, not a human approval. It makes
            # the quality runner measure feature pollution on the proposed
            # dataset rather than silently reporting not_measured.
            case["feature"] = proposed_feature
            if proposed_feature_scope:
                case["feature_scope"] = list(proposed_feature_scope)
            proposed_feature_cases.append(case_id)

        review_status = "source_verified_pending_human_signoff"
        source_rationale = (
            correction.get("rationale")
            if correction and correction.get("feature_scope")
            else scope_proposal["rationale"]
            if scope_proposal
            else "Official source identity, vendor, platform and feature metadata were cross-checked; human signoff is still required."
        )
        case["source_review"] = {
            "status": review_status,
            "source_urls": sorted({item["source_url"] for item in source_records}),
            "document_checks": source_records,
            "feature_proposal": proposed_feature,
            "feature_scope": list(proposed_feature_scope or []),
            "rationale": source_rationale,
        }
        source_review_cases.append(
            {
                "case_id": case_id,
                "status": review_status,
                "document_ids": acceptable_ids,
                "source_urls": sorted({item["source_url"] for item in source_records}),
                "feature_proposal": proposed_feature,
                "feature_scope": list(proposed_feature_scope or []),
            }
        )

    report = {
        "schema_version": 1,
        "dataset_id": candidate["dataset_id"],
        "parent_dataset_id": dataset.get("dataset_id"),
        "status": "SOURCE_REVIEW_COMPLETE_PENDING_HUMAN_SIGNOFF",
        "review_mode": "official_source_provenance_automated",
        "human_review_required": True,
        "reviewer": "Codex automated source review",
        "reviewed_at": "2026-09-05T00:00:00+08:00",
        "annotation_status": "source_verified_pending_human_signoff",
        "default_ci_dataset_unchanged": True,
        "changed_case_count": len(changes),
        "source_review_case_count": len(source_review_cases),
        "proposed_feature_annotation_count": len(proposed_feature_cases),
        "feature_adjudication_required_case_ids": adjudication_cases,
        "machine_feature_scope_case_ids": sorted(FEATURE_SCOPE_PROPOSALS),
        "source_review_cases": source_review_cases,
        "changes": changes,
        "notes": [
            "Official vendor pages were used as provenance evidence; the local migration stores concise source-backed summaries rather than copied pages.",
            "The candidate contains automated feature and source annotations to reduce manual work, but it does not impersonate a domain reviewer and must not be treated as an approved human Gold signoff.",
            "The four multi-feature cases use an explicit feature_scope so the machine review does not silently collapse several valid feature labels into one.",
            "Human signoff is still a separate identity/approval step; after it, create a new frozen dataset ID and run the review checker plus the strict 50-anchor gate.",
        ],
    }
    return candidate, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--dataset-output", type=Path, default=DEFAULT_DATASET_OUTPUT)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT_OUTPUT)
    args = parser.parse_args()

    dataset = yaml.safe_load(args.input.read_text(encoding="utf-8"))
    candidate, report = build_candidate(dataset)
    args.dataset_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.dataset_output.write_text(
        yaml.safe_dump(candidate, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )
    args.report_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": report["status"], "changed_case_count": report["changed_case_count"], "dataset": str(args.dataset_output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
