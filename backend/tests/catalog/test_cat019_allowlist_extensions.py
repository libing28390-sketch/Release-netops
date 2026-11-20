from __future__ import annotations


def test_cat019_additive_allowlist_accepts_huawei_h3c_and_cisco_datacenter(isolated_db, make_user):
    from services.source_registry_service import validate_official_url_input

    cases = (
        (
            "https://support.huawei.com/enterprise/en/doc/EDOC1100459443/d770f3cd/configuring-ospf-attributes-on-different-types-of-networks",
            "configuration_guide",
            {"vendor": "Huawei", "product_family": "S5700/S6700"},
        ),
        (
            "https://www.h3c.com/en/d_201903/1159013_294551_0.htm",
            "configuration_guide",
            {"vendor": "H3C", "product_family": "Comware 7 Switches"},
        ),
        (
            "https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus3000/sw/unicast/602_u1_1/l3_nx-os/l3_ospf.html",
            "configuration_guide",
            {"vendor": "Cisco", "product_family": "Nexus 3000/9000"},
        ),
    )
    for url, source_kind, metadata in cases:
        result = validate_official_url_input(
            url,
            source_kind=source_kind,
            metadata={
                **metadata,
                "version_scope": {"primary": "reviewed", "compatibility": "compatible"},
                "terms_review_status": "approved",
            },
        )
        assert result["matched_catalog"]["vendor"] == metadata["vendor"]
        assert result["source_kind"] == source_kind


def test_cat019_allows_cisco_troubleshooting_pages_after_reviewed_extension(isolated_db, make_user):
    from services.source_registry_service import validate_official_url_input

    cases = (
        (
            "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-13/configuration_guide/sys_mgmt/b_1713_sys_mgmt_9300_cg/troubleshooting_the_software_configuration.html",
            "Catalyst 9300",
        ),
        (
            "https://www.cisco.com/c/zh_cn/support/docs/switches/catalyst-9300-series-switches/225617-troubleshooting-network-latency-and.html",
            "Catalyst 9000",
        ),
        (
            "https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/92x/troubleshooting/guide/b-cisco-nexus-9000-nx-os-troubleshooting-guide-92x/b-cisco-nexus-9000-nx-os-troubleshooting-guide-92x_chapter_010.html",
            "Nexus 9000",
        ),
    )
    for url, product_family in cases:
        result = validate_official_url_input(
            url,
            source_kind="troubleshooting_guide",
            metadata={
                "vendor": "Cisco",
                "product_family": product_family,
                "version_scope": {"primary": "reviewed-current", "compatibility": "compatible"},
                "terms_review_status": "approved",
            },
        )
        assert result["source_kind"] == "troubleshooting_guide"
        assert result["matched_catalog"]["vendor"] == "Cisco"


def test_cat019_allows_reviewed_huawei_chinese_document_paths(isolated_db, make_user):
    from services.source_registry_service import validate_official_url_input

    cases = (
        (
            "https://support.huawei.com/enterprise/zh/doc/EDOC1100459455/a3558870/example-for-configuring-mux-vlan-on-an-aggregation-device",
            "configuration_guide",
            "S5700/S6700",
        ),
        (
            "https://support.huawei.com/enterprise/zh/doc/EDOC1100278276/c3f6a316",
            "configuration_guide",
            "S5700/S6700",
        ),
        (
            "https://info.support.huawei.com/enterprise/zh/doc/EDOC1100459453/99234d3a",
            "configuration_guide",
            "S5700/S6700",
        ),
        (
            "https://info.support.huawei.com/enterprise/zh/doc/EDOC1100459421/ddc3d496",
            "command_reference",
            "S5700/S6700",
        ),
        (
            "https://info.support.huawei.com/enterprise/zh/doc/EDOC1000075592/4079ef29",
            "troubleshooting_guide",
            "S-series",
        ),
    )
    for url, source_kind, product_family in cases:
        result = validate_official_url_input(
            url,
            source_kind=source_kind,
            metadata={
                "vendor": "Huawei",
                "product_family": product_family,
                "version_scope": {"primary": "exact-document-scope", "compatibility": "exact-document-scope"},
                "terms_review_status": "approved",
            },
        )
        assert result["source_kind"] == source_kind
        assert result["matched_catalog"]["vendor"] == "Huawei"
