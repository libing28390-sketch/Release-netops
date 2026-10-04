from __future__ import annotations


def test_scoped_wan_report_filters_embedded_rows_and_redacts_aggregates() -> None:
    from services.wan_p1_service import _scope_wan_report_item

    report = {
        "id": "report-1",
        "result": {
            "links": [
                {"id": "link-a", "tenant_id": "tenant-a", "site_id": "site-a", "link_name": "Allowed"},
                {"id": "link-b", "tenant_id": "tenant-b", "site_id": "site-b", "link_name": "Secret link"},
            ],
            "link_metrics": [
                {"id": "link-a", "sample_count": 3},
                {"id": "link-b", "sample_count": 90},
            ],
            "rollups": [
                {"link_id": "link-a", "sample_count": 3},
                {"link_id": "link-b", "sample_count": 90},
            ],
            "alerts": [{"severity": "critical", "count": 90}],
            "probe_availability": [{"link_id": "link-a", "availability_pct": 100}],
        },
        "result_json": "full report payload",
    }

    scoped = _scope_wan_report_item(report, tenant_id="tenant-a", site_ids=("site-a",))

    assert scoped is not None
    assert [item["id"] for item in scoped["result"]["links"]] == ["link-a"]
    assert [item["id"] for item in scoped["result"]["link_metrics"]] == ["link-a"]
    assert [item["link_id"] for item in scoped["result"]["rollups"]] == ["link-a"]
    assert scoped["result"]["alerts"] == []
    assert scoped["result"]["probe_availability"] == []
    assert "Secret link" not in scoped["result_json"]
    assert report["result"]["links"][1]["link_name"] == "Secret link"


def test_scoped_wan_report_hides_when_it_has_no_authorized_link() -> None:
    from services.wan_p1_service import _scope_wan_report_item

    report = {
        "result": {
            "links": [{"id": "link-b", "tenant_id": "tenant-b", "site_id": "site-b"}],
            "link_metrics": [],
            "rollups": [],
        },
    }

    assert _scope_wan_report_item(report, tenant_id="tenant-a", site_ids=("site-a",)) is None
