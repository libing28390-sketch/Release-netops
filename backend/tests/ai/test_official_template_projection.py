from urllib.parse import urlsplit

from services.official_template_projection_service import (
    _feature,
    _product_scope,
    _render,
)
from services.official_product_catalog_service import (
    MODEL_CATALOG,
    OFFICIAL_MODEL_REFERENCE,
    model_aliases,
    vendor_models,
)


def _row(template_id: str, content: str = "", vendor: str = "Cisco") -> dict[str, str]:
    return {
        "id": template_id,
        "name": template_id,
        "category": "configuration",
        "vendor": vendor,
        "description": "",
        "content": content,
    }


def test_projection_classifies_basic_features_before_broad_aliases():
    assert _feature(_row("official-cisco-static-route-basic", "ip route 192.0.2.0 255.255.255.0 192.0.2.1"))[0] == "static_route"
    assert _feature(_row("official-cisco-acl-basic", "ip access-list extended MGMT_ONLY"))[0] == "acl"
    assert _feature(_row("official-cisco-ssh-basic", "ip ssh version 2"))[0] == "ssh"
    assert _feature(_row("official-cisco-stp-basic", "spanning-tree mode rapid-pvst"))[0] == "stp"


def test_projection_uses_template_identity_before_rollback_content():
    assert _feature(_row("official-cisco-access-port", "no spanning-tree portfast"))[0] == "access_port"


def test_projection_keeps_hsrp_separate_from_vrrp():
    assert _feature(_row("official-cisco-hsrp-basic", "standby 1 ip 192.0.2.1"))[0] == "hsrp"


def test_projection_renders_secret_inputs_as_vault_references():
    rendered = _render(
        "snmp-server user nms auth sha {{ snmp_auth_key }} priv aes 128 {{ snmp_priv_key }}"
    )
    assert "<from-secret-vault:snmp_auth_key>" in rendered
    assert "<from-secret-vault:snmp_priv_key>" in rendered


def test_projection_keeps_data_center_product_scopes_specific():
    assert _product_scope(_row("official-huawei-ce6800-bgp-basic", "", "Huawei"))[1] == "CE6800"
    assert _product_scope(_row("official-h3c-s6800-s9825-bgp-basic", "", "H3C"))[1] == "S6800/S9825/S9855"
    assert _product_scope(_row("official-cisco-nexus-bgp-basic", ""))[1] == "Nexus 3000/9000"


# Huawei/H3C/Cisco are the fully reviewed vendors; the others were added later
# with a smaller, still official-source-backed model list.
CORE_VENDORS = ("Huawei", "H3C", "Cisco")
KNOWN_SCOPES = {"campus", "datacenter", "wan", "security"}


def test_reviewed_catalog_covers_ten_models_per_vendor_and_both_network_scopes():
    for vendor in CORE_VENDORS:
        rows = vendor_models(vendor)
        assert len(rows) >= 10
        scopes = {row["scope"] for row in rows}
        # Campus and data-center coverage stays mandatory; WAN routers and
        # security appliances are optional additions.
        assert {"campus", "datacenter"} <= scopes <= KNOWN_SCOPES
        assert all(row["model"] for row in rows)
        # A CloudEngine display name and its bare hardware token are aliases
        # of one reviewed row, not two unverified SKUs.
        if vendor == "Huawei":
            assert model_aliases(rows[0])[:2] == [rows[0]["model"], rows[0]["model"].replace("CloudEngine ", "")]
    for vendor, rows in MODEL_CATALOG.items():
        assert rows, vendor
        assert {row["scope"] for row in rows} <= KNOWN_SCOPES, vendor
        assert all(row["model"] and row["series"] and row["platform"] for row in rows), vendor


def test_catalog_platforms_keep_campus_and_data_center_cli_families_separate():
    assert {row["platform"] for row in MODEL_CATALOG["Cisco"] if row["scope"] == "campus"} == {"cisco_iosxe"}
    assert {row["platform"] for row in MODEL_CATALOG["Cisco"] if row["scope"] == "datacenter"} == {"cisco_nxos"}


def test_catalog_contains_official_catalyst_3850_and_h3c_s6850_scopes():
    c3850 = next(row for row in MODEL_CATALOG["Cisco"] if row["model"] == "C3850")
    s6850 = next(row for row in MODEL_CATALOG["H3C"] if row["model"] == "S6850")

    assert c3850["series"] == "Catalyst 3850"
    assert c3850["platform"] == "cisco_iosxe"
    assert s6850["series"] == "S6850"
    assert s6850["platform"] == "h3c_comware"


def test_every_catalog_model_has_vendor_official_provenance():
    allowed_hosts = {
        "Huawei": {"support.huawei.com", "info.support.huawei.com"},
        "H3C": {"www.h3c.com"},
        "Cisco": {"www.cisco.com"},
        # ruijie.com is Ruijie's current global site; ruijienetworks.com the older one.
        "Ruijie": {"www.ruijienetworks.com", "www.ruijie.com"},
        "Juniper": {"www.juniper.net"},
        "Fortinet": {"www.fortinet.com"},
        "Aruba": {"www.arubanetworks.com"},
    }
    # Every catalog vendor must have an explicit official host list.
    assert set(MODEL_CATALOG) <= set(allowed_hosts)
    for vendor, rows in MODEL_CATALOG.items():
        if vendor in CORE_VENDORS:
            assert len(rows) >= 10
        for row in rows:
            assert row["official_url"].startswith("https://")
            assert urlsplit(row["official_url"]).hostname in allowed_hosts[vendor]
            assert row["verification_level"] == "official_model_or_series_catalog"
            expected_date = "2026-09-04" if row["model"] in {"C3850", "S6850"} else "2026-08-23"
            # New vendor-reviewed catalog rows may carry a later review date.
            from datetime import date
            checked = date.fromisoformat(row["source_checked_at"])
            assert date.fromisoformat(expected_date) <= checked <= date.today()


def test_wan_and_security_models_have_their_own_official_page():
    """A router or firewall cannot be evidenced by a vendor's switch index page."""
    for vendor, rows in MODEL_CATALOG.items():
        generic = OFFICIAL_MODEL_REFERENCE[vendor]
        for row in rows:
            if row["scope"] in {"wan", "security"} and "switch" in generic.lower():
                assert row["official_url"] != generic, (vendor, row["model"])
