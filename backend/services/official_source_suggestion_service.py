"""Deterministic official-source suggestions for local knowledge misses.

This module is deliberately a small allow-list, not a web searcher.  A model
may describe a missing topic, but it must never invent a vendor URL.  The
operator can open one of these reviewed vendor entry points, verify the exact
model/release, and then submit the URL through the explicit official import
workflow.
"""

from __future__ import annotations

from typing import Any


_VENDOR_ALIASES = {
    "huawei": "Huawei",
    "华为": "Huawei",
    "h3c": "H3C",
    "华三": "H3C",
    "新华三": "H3C",
    "cisco": "Cisco",
    "思科": "Cisco",
    "ruijie": "Ruijie",
    "锐捷": "Ruijie",
}

_VENDOR_ENTRY_POINTS = {
    "Huawei": "https://support.huawei.com/enterprise/en/index.html",
    "H3C": "https://www.h3c.com/en/Support/Resource_Center/",
    "Cisco": "https://www.cisco.com/c/en/us/support/switches/index.html",
    "Ruijie": "https://www.ruijie.com.cn/fw/wd/",
}

_FEATURE_URLS = {
    "Huawei": {
        "ospf": "https://support.huawei.com/enterprise/en/doc/EDOC1100459443/d770f3cd/configuring-ospf-attributes-on-different-types-of-networks",
        "vrrp": "https://info.support.huawei.com/enterprise/en/doc/EDOC1100352651/23b3c78a/example-for-configuring-association-between-vrrp-and-the-interface-status",
        "qos": "https://info.support.huawei.com/enterprise/en/doc/EDOC1100333649/df30cd60/mqc-configuration-commands",
        "aaa": "https://info.support.huawei.com/hedex/api/pages/EDOC1100277644/AEM10221/03/resources/vrp/dc_vrp_aaa_cfg_1003.html",
        "mlag": "https://info.support.huawei.com/enterprise/en/doc/EDOC1100458988/ce1602ef/configuration-examples-for-m-lag",
    },
    "H3C": {
        "ospf": "https://www.h3c.com/en/d_201903/1159013_294551_0.htm",
        "vrrp": "https://www.h3c.com/en/d_202507/2576036_294551_0.htm",
        "qos": "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Reference_Guides/Command_References/H3C_CR-14616/09/202310/1955674_294551_0.htm",
        "aaa": "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Configure___Deploy/Configuration_Guides/H3C_S6520X_HI_MS4600_CGs_R68xx-27445/00/202602/2752054_294551_0.htm",
        "mlag": "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Switches/00-Public/Configure___Deploy/Configuration_Guides/S6800%5BS6860%5D%5BS6861%5D%28R27xx%29S6820%28R630x%29_CG/03/202106/1416646_294551_0.htm",
    },
    "Cisco": {
        "ospf": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-13/configuration_guide/rtng/b_1713_rtng_9300_cg/configuring_ospf.html",
        "vrrp": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-15/configuration_guide/ip/b_1715_ip_9300_cg/vrrpv3_protocol___support.html",
        "qos": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/26-x/configuration_guide/qos/b_26x_qos_9300_cg/configuring_qos.html",
        "aaa": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/26-x/configuration_guide/sec/b_26x_sec_9300_cg/configuring_local_authentication_and_authorization.html",
        "mlag": "https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/106x/configuration/interfaces/cisco-nexus-9000-series-nx-os-interfaces-configuration-guide-release-106x/m_configuring_vpcs_9x.html",
    },
    "Ruijie": {
        "vlan": "https://www.ruijie.com.cn/fw/wt/35635/",
        "lacp": "https://www.ruijie.com.cn/fw/wt/90880/",
        "ospf": "https://www.ruijie.com.cn/fw/wt/32518/",
        "static_route": "https://www.ruijie.com.cn/fw/wt/37267/",
        "acl": "https://www.ruijie.com.cn/fw/wt/37269/",
    },
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _vendor(value: Any) -> str:
    raw = _text(value).lower()
    return _VENDOR_ALIASES.get(raw, _text(value))


def suggest_official_sources(request: Any, *, limit: int = 3) -> list[dict[str, str]]:
    """Return allow-listed official links for a structured retrieval request."""

    vendor = _vendor(getattr(request, "vendor", ""))
    if vendor not in _VENDOR_ENTRY_POINTS:
        return []
    feature = _text(getattr(request, "feature", "")).lower()
    model = _text(getattr(request, "product_model", "")) or _text(getattr(request, "product_series", ""))
    links: list[dict[str, str]] = []
    feature_url = _FEATURE_URLS.get(vendor, {}).get(feature)
    if feature_url:
        links.append({
            "label": f"{vendor} 官方 {feature.upper()} 文档",
            "url": feature_url,
            "source_kind": "configuration_guide",
            "review_action": "核对型号与软件版本后再导入",
        })
    links.append({
        "label": f"{vendor} 官方产品/文档入口" + (f"（{model}）" if model else ""),
        "url": _VENDOR_ENTRY_POINTS[vendor],
        "source_kind": "product_support",
        "review_action": "搜索精确型号并选择对应版本文档",
    })
    return links[: max(1, min(5, int(limit or 3)))]


__all__ = ["suggest_official_sources"]
