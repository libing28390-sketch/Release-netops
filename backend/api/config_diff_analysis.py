"""Structured configuration difference, compliance, export, and audit APIs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import html
import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core.rbac import require_permission
from database import get_db_connection
from services.config_diff_analysis_service import (
    NORMALIZATION_VERSION,
    PARSER_VERSION,
    RISK_RULE_VERSION,
    cache_key,
    compare_structured_configs,
    evaluate_compliance,
    safe_json,
    validate_snapshot_content,
)
from services.config_search_service import _read_config_file


router = APIRouter()


class DiffAnalysisRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=120)
    snapshot_a_id: str = Field(min_length=1, max_length=120)
    snapshot_b_id: str = Field(min_length=1, max_length=120)
    mode: Literal["normalized", "raw"] = "normalized"
    force_refresh: bool = False


class DiffConfirmationRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=120)
    snapshot_a_id: str = Field(min_length=1, max_length=120)
    snapshot_b_id: str = Field(min_length=1, max_length=120)
    status: Literal["confirmed", "expected", "accepted_risk", "false_positive"] = "confirmed"
    note: str = Field(default="", max_length=2_000)


class SourceLinkRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=120)
    snapshot_a_id: str = Field(min_length=1, max_length=120)
    snapshot_b_id: str = Field(min_length=1, max_length=120)
    source_type: Literal["change_order", "automation_task", "audit_event", "external_ticket"]
    source_id: str = Field(min_length=1, max_length=120)
    source_label: str = Field(default="", max_length=240)


class ComplianceRuleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2_000)
    scope: dict[str, Any] = Field(default_factory=dict)
    rule_type: Literal["require", "forbid"]
    pattern: str = Field(min_length=1, max_length=2_000)
    minimum_count: int = Field(default=1, ge=1, le=1_000)
    severity: Literal["critical", "high", "medium", "low", "info"] = "medium"
    remediation: str = Field(default="", max_length=2_000)
    enabled: bool = True


class ComplianceScanRequest(BaseModel):
    device_ids: list[str] = Field(default_factory=list, max_length=500)


class GoldenBaselineRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2_000)
    scope: dict[str, Any] = Field(default_factory=dict)
    source_type: Literal["snapshot", "template", "inline"] = "snapshot"
    snapshot_id: str = Field(default="", max_length=120)
    template_id: str = Field(default="", max_length=120)
    expected_config: str = Field(default="", max_length=1_000_000)
    enabled: bool = True


class ChangeValidationWorkflowRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=120)
    change_order_id: str = Field(default="", max_length=120)
    before_snapshot_id: str = Field(default="", max_length=120)
    expected_snapshot_id: str = Field(default="", max_length=120)
    after_snapshot_id: str = Field(default="", max_length=120)
    stage: Literal["precheck", "dry_run", "approval", "executing", "postcheck", "rollback", "closed"] = "precheck"
    dry_run: bool = True
    note: str = Field(default="", max_length=2_000)


class InlineDiffRequest(BaseModel):
    device_id: str = Field(default="", max_length=120)
    before_content: str = Field(max_length=1_000_000)
    after_content: str = Field(max_length=1_000_000)
    vendor: str = Field(default="", max_length=80)
    platform: str = Field(default="", max_length=120)
    role: str = Field(default="", max_length=80)
    mode: Literal["normalized", "raw"] = "normalized"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_pair(conn, body: DiffAnalysisRequest) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    device_row = conn.execute(
        """
        SELECT id, hostname, ip_address, vendor, platform, version, role, site, status
        FROM devices WHERE id = ?
        """,
        (body.device_id,),
    ).fetchone()
    if not device_row:
        raise HTTPException(status_code=404, detail="设备不存在")
    rows = conn.execute(
        """
        SELECT * FROM config_snapshots
        WHERE device_id = ? AND id IN (?, ?)
        """,
        (body.device_id, body.snapshot_a_id, body.snapshot_b_id),
    ).fetchall()
    mapped = {row["id"]: dict(row) for row in rows}
    if body.snapshot_a_id not in mapped or body.snapshot_b_id not in mapped:
        raise HTTPException(status_code=404, detail="A/B 快照不存在或不属于该设备")
    if body.snapshot_a_id == body.snapshot_b_id:
        raise HTTPException(status_code=422, detail="A/B 不能选择同一份快照")
    return dict(device_row), mapped[body.snapshot_a_id], mapped[body.snapshot_b_id]


def _correlate_sources(
    conn,
    device: dict[str, Any],
    snapshot_a: dict[str, Any],
    snapshot_b: dict[str, Any],
    has_changes: bool,
) -> dict[str, Any]:
    correlations: list[dict[str, Any]] = []
    device_id = str(device["id"])
    target_like = f"%{device_id}%"
    orders = conn.execute(
        """
        SELECT id, order_number, title, status, requester_username, actual_start,
               actual_end, updated_at
        FROM change_orders
        WHERE target_devices_json LIKE ?
        ORDER BY updated_at DESC
        LIMIT 10
        """,
        (target_like,),
    ).fetchall()
    executions = conn.execute(
        """
        SELECT pe.id, pe.scenario_name, pe.status, pe.author, pe.created_at,
               pe.updated_at
        FROM playbook_executions pe
        JOIN execution_device_results edr ON edr.execution_id = pe.id
        WHERE edr.device_id = ?
        ORDER BY pe.created_at DESC
        LIMIT 10
        """,
        (device_id,),
    ).fetchall()
    audits = conn.execute(
        """
        SELECT id, event_type, summary, actor_username, created_at
        FROM audit_events
        WHERE device_id = ?
        ORDER BY created_at DESC
        LIMIT 10
        """,
        (device_id,),
    ).fetchall()
    try:
        target_time = datetime.fromisoformat(str(snapshot_b.get("timestamp") or "").replace("Z", "+00:00"))
        if target_time.tzinfo is None:
            target_time = target_time.replace(tzinfo=timezone.utc)
    except ValueError:
        target_time = datetime.now(timezone.utc)
    window = timedelta(hours=4)

    def within(value: str) -> bool:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return abs(parsed - target_time) <= window
        except ValueError:
            return False

    for row in orders:
        timestamp = row["actual_end"] or row["actual_start"] or row["updated_at"]
        if within(timestamp):
            correlations.append({
                "source_type": "change_order",
                "source_id": row["id"],
                "label": f"{row['order_number']} · {row['title']}",
                "status": row["status"],
                "actor": row["requester_username"],
                "timestamp": timestamp,
            })
    for row in executions:
        if within(row["updated_at"] or row["created_at"]):
            correlations.append({
                "source_type": "automation_task",
                "source_id": row["id"],
                "label": row["scenario_name"] or "Automation",
                "status": row["status"],
                "actor": row["author"],
                "timestamp": row["updated_at"] or row["created_at"],
            })
    for row in audits:
        if within(row["created_at"]):
            correlations.append({
                "source_type": "audit_event",
                "source_id": row["id"],
                "label": row["summary"],
                "status": row["event_type"],
                "actor": row["actor_username"],
                "timestamp": row["created_at"],
            })
    manual_links = conn.execute(
        """
        SELECT source_type, source_id, source_label, linked_by, linked_at
        FROM config_diff_source_links
        WHERE device_id = ? AND snapshot_a_id = ? AND snapshot_b_id = ?
        ORDER BY linked_at DESC
        """,
        (device_id, snapshot_a["id"], snapshot_b["id"]),
    ).fetchall()
    correlations.extend([
        {
            "source_type": row["source_type"],
            "source_id": row["source_id"],
            "label": row["source_label"],
            "status": "manually_linked",
            "actor": row["linked_by"],
            "timestamp": row["linked_at"],
        }
        for row in manual_links
    ])
    return {
        "correlations": correlations,
        "out_of_band_suspected": bool(has_changes and not correlations),
        "message": (
            "未在四小时窗口内找到平台任务、变更工单或审计事件，疑似带外变更。"
            if has_changes and not correlations
            else "已找到可能的变更来源。" if correlations
            else "A/B 配置无变化。"
        ),
    }


def _compliance_rules(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM config_compliance_rules WHERE enabled = 1 ORDER BY severity, name"
    ).fetchall()
    return [
        {
            **dict(row),
            "scope": safe_json(row["scope_json"], {}),
        }
        for row in rows
    ]


def _analyze(conn, body: DiffAnalysisRequest) -> dict[str, Any]:
    device, snapshot_a, snapshot_b = _load_pair(conn, body)
    content_a = _read_config_file(snapshot_a.get("file_path") or "")
    content_b = _read_config_file(snapshot_b.get("file_path") or "")
    if not content_a or not content_b:
        raise HTTPException(status_code=422, detail="无法读取 A/B 快照内容")
    validation_a = validate_snapshot_content(content_a, vendor=snapshot_a.get("vendor") or device.get("vendor") or "")
    validation_b = validate_snapshot_content(content_b, vendor=snapshot_b.get("vendor") or device.get("vendor") or "")
    hash_a = snapshot_a.get("raw_hash") or validation_a["content_hash"]
    hash_b = snapshot_b.get("raw_hash") or validation_b["content_hash"]
    key = cache_key(body.device_id, hash_a, hash_b, body.mode)
    if not body.force_refresh:
        cached = conn.execute("SELECT result_json FROM config_diff_cache WHERE cache_key = ?", (key,)).fetchone()
        if cached:
            result = json.loads(cached["result_json"])
            result["cache"] = {"hit": True, "key": key}
            return result

    analysis = compare_structured_configs(
        content_a,
        content_b,
        vendor=snapshot_b.get("vendor") or device.get("vendor") or "",
        device=device,
        mode=body.mode,
    )
    compliance = evaluate_compliance(content_b, _compliance_rules(conn), device)
    source = _correlate_sources(conn, device, snapshot_a, snapshot_b, analysis["has_changes"])
    direction_reversed = str(snapshot_a.get("timestamp") or "") > str(snapshot_b.get("timestamp") or "")
    config_types = {
        "a": snapshot_a.get("config_type") or "running",
        "b": snapshot_b.get("config_type") or "running",
    }
    result = {
        "device": device,
        "snapshot_a": {
            key_name: snapshot_a.get(key_name)
            for key_name in (
                "id", "timestamp", "trigger", "author", "size", "integrity_status",
                "validation_status", "config_type", "collection_source",
                "collection_task_id", "change_ticket_id", "raw_hash", "line_count",
            )
        },
        "snapshot_b": {
            key_name: snapshot_b.get(key_name)
            for key_name in (
                "id", "timestamp", "trigger", "author", "size", "integrity_status",
                "validation_status", "config_type", "collection_source",
                "collection_task_id", "change_ticket_id", "raw_hash", "line_count",
            )
        },
        "direction": "A_TO_B",
        "direction_reversed": direction_reversed,
        "validation": {"a": validation_a, "b": validation_b},
        "config_types": config_types,
        "running_startup_sync": (
            not analysis["has_changes"]
            if set(config_types.values()) == {"running", "startup"}
            else None
        ),
        "compliance": compliance,
        "source_correlation": source,
        **analysis,
        "cache": {"hit": False, "key": key},
    }
    now = _now()
    conn.execute(
        """
        INSERT INTO config_diff_cache (
            cache_key, device_id, snapshot_a_id, snapshot_b_id, diff_mode,
            normalization_version, parser_version, risk_rule_version,
            result_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            result_json = excluded.result_json,
            updated_at = excluded.updated_at
        """,
        (
            key,
            body.device_id,
            body.snapshot_a_id,
            body.snapshot_b_id,
            body.mode,
            NORMALIZATION_VERSION,
            PARSER_VERSION,
            RISK_RULE_VERSION,
            json.dumps(result, ensure_ascii=False),
            now,
            now,
        ),
    )
    return result


@router.post("/config-diff/analysis")
def analyze_config_diff(
    body: DiffAnalysisRequest,
    _user=require_permission("configuration", "read"),
):
    conn = get_db_connection()
    try:
        result = _analyze(conn, body)
        conn.commit()
        return result
    finally:
        conn.close()


@router.post("/config-diff/inline-analysis")
def analyze_inline_config_diff(
    body: InlineDiffRequest,
    _user=require_permission("configuration", "read"),
):
    return compare_structured_configs(
        body.before_content,
        body.after_content,
        vendor=body.vendor,
        device={
            "id": body.device_id,
            "vendor": body.vendor,
            "platform": body.platform,
            "role": body.role,
        },
        mode=body.mode,
    )


@router.post("/config-diff/export")
def export_config_diff(
    body: DiffAnalysisRequest,
    format: Literal["markdown", "html", "json"] = Query(default="markdown"),
    _user=require_permission("configuration", "export"),
):
    conn = get_db_connection()
    try:
        result = _analyze(conn, body)
        conn.commit()
    finally:
        conn.close()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if format == "json":
        return Response(
            json.dumps(result, ensure_ascii=False, indent=2),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="config-diff-{timestamp}.json"'},
        )

    summary = result["summary"]
    markdown = [
        "# 配置差异分析报告",
        "",
        f"- 设备：{result['device'].get('hostname')} ({result['device'].get('ip_address')})",
        f"- 方向：A `{result['snapshot_a'].get('timestamp')}` → B `{result['snapshot_b'].get('timestamp')}`",
        f"- 新增行：{summary['added_lines']}",
        f"- 删除行：{summary['removed_lines']}",
        f"- 变更对象：{summary['changed_objects']}",
        f"- 高风险变更：{summary['high_risk_changes']}",
        f"- 合规率：{result['compliance']['compliance_rate']}%",
        f"- 变更来源：{result['source_correlation']['message']}",
        "",
        "## 对象级变更",
        "",
    ]
    for item in result["objects"]:
        markdown.extend([
            f"### {item['object_type']} · {item['object_name']}",
            "",
            f"- 变化：{item['change_type']}",
            f"- 风险：{item['risk_level']} — {item['risk_reason']}",
            f"- 潜在影响：{item['potential_impact']}",
            "",
            "```diff",
            *[f"- {line}" for line in item["before_lines"]],
            *[f"+ {line}" for line in item["after_lines"]],
            "```",
            "",
        ])
    markdown.extend(["## 统一差异", "", "```diff", *result["unified_diff"], "```", ""])
    markdown_text = "\n".join(markdown)
    if format == "markdown":
        return Response(
            markdown_text,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="config-diff-{timestamp}.md"'},
        )

    body_html = "<br>".join(html.escape(line) for line in markdown_text.splitlines())
    html_document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>配置差异分析报告</title>
<style>body{{font-family:system-ui;margin:40px;color:#0f172a;line-height:1.65}}
code,pre{{font-family:Consolas,monospace}} .meta{{color:#475569}}
@media print{{body{{margin:16mm}}}}</style></head>
<body>{body_html}</body></html>"""
    return Response(
        html_document,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="config-diff-{timestamp}.html"'},
    )


@router.post("/config-diff/confirm")
def confirm_config_diff(
    body: DiffConfirmationRequest,
    user=require_permission("configuration", "update"),
):
    confirmation_id = str(uuid.uuid4())
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO config_diff_confirmations (
                id, device_id, snapshot_a_id, snapshot_b_id, status, note,
                confirmed_by, confirmed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                confirmation_id,
                body.device_id,
                body.snapshot_a_id,
                body.snapshot_b_id,
                body.status,
                body.note,
                user.get("username") or "",
                _now(),
            ),
        )
        conn.commit()
        return {"id": confirmation_id, "success": True}
    finally:
        conn.close()


@router.post("/config-diff/source-links")
def link_config_diff_source(
    body: SourceLinkRequest,
    user=require_permission("configuration", "update"),
):
    link_id = str(uuid.uuid4())
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO config_diff_source_links (
                id, device_id, snapshot_a_id, snapshot_b_id, source_type,
                source_id, source_label, linked_by, linked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                link_id,
                body.device_id,
                body.snapshot_a_id,
                body.snapshot_b_id,
                body.source_type,
                body.source_id,
                body.source_label,
                user.get("username") or "",
                _now(),
            ),
        )
        conn.execute(
            "DELETE FROM config_diff_cache WHERE device_id = ? AND snapshot_a_id = ? AND snapshot_b_id = ?",
            (body.device_id, body.snapshot_a_id, body.snapshot_b_id),
        )
        conn.commit()
        return {"id": link_id, "success": True}
    finally:
        conn.close()


@router.get("/config-diff/baselines")
def list_golden_baselines(_user=require_permission("configuration", "read")):
    conn = get_db_connection()
    try:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM config_golden_baselines ORDER BY enabled DESC, updated_at DESC"
        ).fetchall()]
    finally:
        conn.close()


@router.post("/config-diff/baselines")
def create_golden_baseline(
    body: GoldenBaselineRequest,
    user=require_permission("configuration", "update"),
):
    if body.source_type == "snapshot" and not body.snapshot_id:
        raise HTTPException(status_code=422, detail="快照型基线必须指定 snapshot_id")
    if body.source_type == "inline" and not body.expected_config.strip():
        raise HTTPException(status_code=422, detail="内置文本型基线不能为空")
    conn = get_db_connection()
    try:
        if body.snapshot_id:
            snapshot = conn.execute("SELECT id FROM config_snapshots WHERE id = ?", (body.snapshot_id,)).fetchone()
            if not snapshot:
                raise HTTPException(status_code=404, detail="基线快照不存在")
        baseline_id = str(uuid.uuid4())
        now = _now()
        conn.execute(
            """
            INSERT INTO config_golden_baselines (
                id, name, description, scope_json, source_type, snapshot_id,
                template_id, expected_config, enabled, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                baseline_id, body.name, body.description, json.dumps(body.scope, ensure_ascii=False),
                body.source_type, body.snapshot_id, body.template_id, body.expected_config,
                1 if body.enabled else 0, user.get("username") or "", now, now,
            ),
        )
        conn.commit()
        return {"id": baseline_id, "success": True}
    finally:
        conn.close()


@router.delete("/config-diff/baselines/{baseline_id}")
def delete_golden_baseline(baseline_id: str, _user=require_permission("configuration", "update")):
    conn = get_db_connection()
    try:
        cursor = conn.execute("DELETE FROM config_golden_baselines WHERE id = ?", (baseline_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="黄金基线不存在")
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


@router.get("/config-diff/workflows")
def list_change_validation_workflows(
    device_id: str = Query(default="", max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    _user=require_permission("configuration", "read"),
):
    conn = get_db_connection()
    try:
        if device_id:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM config_change_validation_workflows WHERE device_id = ? ORDER BY updated_at DESC LIMIT ?",
                (device_id, limit),
            ).fetchall()]
        return [dict(row) for row in conn.execute(
            "SELECT * FROM config_change_validation_workflows ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()]
    finally:
        conn.close()


@router.post("/config-diff/workflows")
def create_change_validation_workflow(
    body: ChangeValidationWorkflowRequest,
    user=require_permission("configuration", "execute"),
):
    conn = get_db_connection()
    try:
        dry_run_result: dict[str, Any] = {}
        risk_summary: dict[str, Any] = {}
        if body.dry_run and body.before_snapshot_id and body.expected_snapshot_id:
            analysis = _analyze(conn, DiffAnalysisRequest(
                device_id=body.device_id,
                snapshot_a_id=body.before_snapshot_id,
                snapshot_b_id=body.expected_snapshot_id,
                mode="normalized",
                force_refresh=False,
            ))
            dry_run_result = {
                "has_changes": analysis.get("has_changes"),
                "changed_objects": analysis.get("summary", {}).get("changed_objects", 0),
                "unified_diff_lines": len(analysis.get("unified_diff", [])),
                "requires_mfa": analysis.get("requires_mfa", False),
            }
            risk_summary = analysis.get("summary", {}).get("risk_counts", {})
        workflow_id = str(uuid.uuid4())
        now = _now()
        conn.execute(
            """
            INSERT INTO config_change_validation_workflows (
                id, change_order_id, device_id, before_snapshot_id,
                expected_snapshot_id, after_snapshot_id, stage,
                dry_run_result_json, risk_summary_json, precheck_result_json,
                postcheck_result_json, rollback_plan_json, requires_mfa,
                approved_by, executed_by, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', '{}', 1, '', ?, ?, ?, ?)
            """,
            (
                workflow_id, body.change_order_id, body.device_id, body.before_snapshot_id,
                body.expected_snapshot_id, body.after_snapshot_id, body.stage,
                json.dumps(dry_run_result, ensure_ascii=False), json.dumps(risk_summary, ensure_ascii=False),
                json.dumps({"note": body.note}, ensure_ascii=False), user.get("username") or "",
                body.stage, now, now,
            ),
        )
        conn.commit()
        return {"id": workflow_id, "success": True, "stage": body.stage, "dry_run": dry_run_result, "risk_summary": risk_summary}
    finally:
        conn.close()


@router.get("/config-diff/compliance/rules")
def list_config_compliance_rules(
    _user=require_permission("configuration", "read"),
):
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM config_compliance_rules ORDER BY severity, name").fetchall()
        return [
            {
                **dict(row),
                "scope": safe_json(row["scope_json"], {}),
                "enabled": bool(row["enabled"]),
            }
            for row in rows
        ]
    finally:
        conn.close()


@router.post("/config-diff/compliance/rules")
def create_config_compliance_rule(
    body: ComplianceRuleRequest,
    user=require_permission("configuration", "update"),
):
    rule_id = str(uuid.uuid4())
    now = _now()
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO config_compliance_rules (
                id, name, description, scope_json, rule_type, pattern,
                minimum_count, severity, remediation, enabled, created_by,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rule_id,
                body.name,
                body.description,
                json.dumps(body.scope, ensure_ascii=False),
                body.rule_type,
                body.pattern,
                body.minimum_count,
                body.severity,
                body.remediation,
                1 if body.enabled else 0,
                user.get("username") or "",
                now,
                now,
            ),
        )
        conn.commit()
        return {"id": rule_id, "success": True}
    finally:
        conn.close()


@router.put("/config-diff/compliance/rules/{rule_id}")
def update_config_compliance_rule(
    rule_id: str,
    body: ComplianceRuleRequest,
    _user=require_permission("configuration", "update"),
):
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            """
            UPDATE config_compliance_rules
            SET name = ?, description = ?, scope_json = ?, rule_type = ?,
                pattern = ?, minimum_count = ?, severity = ?, remediation = ?,
                enabled = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                body.name,
                body.description,
                json.dumps(body.scope, ensure_ascii=False),
                body.rule_type,
                body.pattern,
                body.minimum_count,
                body.severity,
                body.remediation,
                1 if body.enabled else 0,
                _now(),
                rule_id,
            ),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="合规规则不存在")
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


@router.delete("/config-diff/compliance/rules/{rule_id}")
def delete_config_compliance_rule(
    rule_id: str,
    _user=require_permission("configuration", "update"),
):
    conn = get_db_connection()
    try:
        cursor = conn.execute("DELETE FROM config_compliance_rules WHERE id = ?", (rule_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="合规规则不存在")
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


@router.post("/config-diff/compliance/scan")
def scan_config_compliance(
    body: ComplianceScanRequest,
    user=require_permission("configuration", "execute"),
):
    conn = get_db_connection()
    try:
        if body.device_ids:
            placeholders = ",".join("?" for _ in body.device_ids)
            devices = conn.execute(
                f"SELECT id, hostname, vendor, platform, role, site FROM devices WHERE id IN ({placeholders})",
                tuple(body.device_ids),
            ).fetchall()
        else:
            devices = conn.execute("SELECT id, hostname, vendor, platform, role, site FROM devices ORDER BY hostname").fetchall()
        rules = _compliance_rules(conn)
        items = []
        now = _now()
        for raw_device in devices:
            device = dict(raw_device)
            snapshot = conn.execute(
                """
                SELECT id, file_path FROM config_snapshots
                WHERE device_id = ?
                  AND COALESCE(config_type, 'running') = 'running'
                  AND COALESCE(integrity_status, 'unknown') NOT IN ('invalid', 'corrupt')
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (device["id"],),
            ).fetchone()
            if not snapshot:
                items.append({"device_id": device["id"], "hostname": device["hostname"], "status": "no_valid_snapshot"})
                continue
            content = _read_config_file(snapshot["file_path"] or "")
            result = evaluate_compliance(content, rules, device)
            scan_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO config_compliance_scan_results (
                    id, device_id, snapshot_id, compliant_count,
                    noncompliant_count, compliance_rate, findings_json,
                    status, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)
                """,
                (
                    scan_id,
                    device["id"],
                    snapshot["id"],
                    result["compliant_count"],
                    result["noncompliant_count"],
                    result["compliance_rate"],
                    json.dumps(result["findings"], ensure_ascii=False),
                    user.get("username") or "",
                    now,
                ),
            )
            items.append({"id": scan_id, "device_id": device["id"], "hostname": device["hostname"], "status": "completed", **result})
        conn.commit()
        return {
            "items": items,
            "total": len(items),
            "completed": sum(1 for item in items if item["status"] == "completed"),
        }
    finally:
        conn.close()
