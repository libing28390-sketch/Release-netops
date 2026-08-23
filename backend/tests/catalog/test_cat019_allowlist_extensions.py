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
        assert result["official_entry"]["vendor"] == metadata["vendor"]
        assert result["source_kind"] == source_kind
