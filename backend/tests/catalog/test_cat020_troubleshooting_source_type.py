from __future__ import annotations


def test_cat020_troubleshooting_source_type_is_allowlisted_for_h3c_and_ruijie(isolated_db, make_user):
    from services.source_registry_service import validate_official_url_input

    cases = (
        (
            "https://www.h3c.com/cn/d_202603/2776299_30005_0.htm",
            "H3C",
            "H3C Switches",
        ),
        (
            "https://www.ruijie.com.cn/fw/wt/93439/",
            "Ruijie",
            "RGOS Switches",
        ),
    )
    for url, vendor, product_family in cases:
        result = validate_official_url_input(
            url,
            source_kind="troubleshooting_guide",
            metadata={
                "vendor": vendor,
                "product_family": product_family,
                "version_scope": {"primary": "reviewed-current", "compatibility": "document-defined"},
                "terms_review_status": "approved",
            },
        )
        assert result["source_kind"] == "troubleshooting_guide"
        assert result["matched_catalog"]["vendor"] == vendor


def test_cat020_publisher_maps_troubleshooting_to_troubleshooting_category():
    from services.official_document_publisher import _category_for

    assert _category_for("troubleshooting_guide", "ospf") == "troubleshooting"


def test_cat020_document_taxonomy_maps_to_browse_directory_projection():
    from ai.services.knowledge_metadata import directory_metadata_for_document

    assert directory_metadata_for_document("command", "H3C") == {
        "knowledge_directory": "02_commands",
        "knowledge_directory_root": "02_commands",
        "knowledge_directory_vendor": "h3c",
        "knowledge_directory_path": "02_commands/h3c",
    }
    assert directory_metadata_for_document("troubleshooting", "Ruijie")[
        "knowledge_directory_path"
    ] == "05_troubleshooting/ruijie"
    assert directory_metadata_for_document("hardware", "unclassified")[
        "knowledge_directory_path"
    ] == "01_product"
