"""
NetOps 批量巡检脚本模板
用法: python batch_inspection.py --target all|site:xxx|device:xxx
"""
import argparse
import json
import sys
from datetime import datetime

import requests

# ============ 配置 ============
API_BASE = "http://localhost:8000"
TOKEN = "YOUR_BEARER_TOKEN"  # 替换为实际 token
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# ============ 辅助函数 ============

def api_get(path: str, params: dict | None = None) -> dict:
    resp = requests.get(f"{API_BASE}{path}", headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def api_post(path: str, body: dict | None = None) -> dict:
    resp = requests.post(f"{API_BASE}{path}", headers=HEADERS, json=body, timeout=60)
    resp.raise_for_status()
    return resp.json()


# ============ 巡检步骤 ============

def get_devices(target: str) -> list[dict]:
    """获取巡检目标设备列表"""
    result = api_get("/devices/")
    devices = result.get("data", [])
    if target == "all":
        return devices
    if target.startswith("site:"):
        site = target.split(":", 1)[1]
        return [d for d in devices if d.get("site") == site]
    if target.startswith("device:"):
        dev_id = target.split(":", 1)[1]
        return [d for d in devices if d.get("id") == dev_id]
    return devices


def check_connectivity(device_id: str) -> dict:
    """连通性测试（deep 模式）"""
    return api_post(f"/devices/connect", body={"device_id": device_id, "check_mode": "deep"})


def get_health(device_id: str) -> dict:
    """获取设备健康评分"""
    return api_get(f"/device-health/device/{device_id}")


def run_compliance(device_id: str) -> dict:
    """运行合规检查"""
    return api_post("/compliance/run", body={"device_ids": [device_id]})


def generate_report(results: list[dict]) -> str:
    """生成 Markdown 巡检报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total = len(results)
    healthy = sum(1 for r in results if r.get("health_status") == "healthy")
    critical = sum(1 for r in results if r.get("health_status") == "critical")
    unreachable = sum(1 for r in results if not r.get("reachable"))

    lines = [
        f"# 巡检报告 — {now}\n",
        "## 概览\n",
        f"- 巡检设备数: {total}",
        f"- 健康: {healthy} | 异常: {critical} | 不可达: {unreachable}\n",
        "## 设备明细\n",
        "| 设备名 | IP | 健康评分 | 状态 | 告警数 | 合规 |",
        "|--------|-----|---------|------|--------|------|",
    ]

    for r in results:
        lines.append(
            f"| {r.get('hostname', '-')} "
            f"| {r.get('ip', '-')} "
            f"| {r.get('health_score', '-')} "
            f"| {r.get('health_status', '-')} "
            f"| {r.get('alert_count', 0)} "
            f"| {r.get('compliance_status', '-')} |"
        )

    # 异常发现
    issues = [r for r in results if r.get("health_status") != "healthy" or not r.get("reachable")]
    if issues:
        lines.append("\n## 异常发现\n")
        for i, r in enumerate(issues, 1):
            reason = r.get("issue_summary", "需进一步排查")
            lines.append(f"{i}. **{r.get('hostname')}** ({r.get('ip')}) — {reason}")

    return "\n".join(lines)


# ============ 主流程 ============

def main():
    parser = argparse.ArgumentParser(description="NetOps 批量巡检")
    parser.add_argument("--target", default="all", help="巡检范围: all | site:<name> | device:<id>")
    parser.add_argument("--output", default="inspection_report.md", help="报告输出文件")
    args = parser.parse_args()

    devices = get_devices(args.target)
    if not devices:
        print("未找到匹配设备", file=sys.stderr)
        sys.exit(1)

    print(f"开始巡检 {len(devices)} 台设备...")
    results = []

    for dev in devices:
        device_id = dev["id"]
        hostname = dev.get("hostname", dev.get("ip", "unknown"))
        print(f"  [{hostname}] 连通性检测...")

        record = {
            "hostname": hostname,
            "ip": dev.get("ip"),
            "reachable": False,
            "health_score": None,
            "health_status": "unknown",
            "alert_count": 0,
            "compliance_status": "unknown",
            "issue_summary": "",
        }

        # 1) 连通性
        try:
            conn = check_connectivity(device_id)
            record["reachable"] = conn.get("data", {}).get("reachable", False)
        except Exception as e:
            record["issue_summary"] = f"连通性测试失败: {e}"
            results.append(record)
            continue

        if not record["reachable"]:
            record["issue_summary"] = "设备不可达"
            results.append(record)
            continue

        # 2) 健康评分
        try:
            health = get_health(device_id)
            hdata = health.get("data", {})
            record["health_score"] = hdata.get("score")
            record["health_status"] = hdata.get("status", "unknown")
            record["alert_count"] = hdata.get("open_alerts_count", 0)
        except Exception:
            pass

        # 3) 合规
        try:
            comp = run_compliance(device_id)
            findings = comp.get("data", {}).get("findings", [])
            open_findings = [f for f in findings if f.get("status") == "open"]
            record["compliance_status"] = "non-compliant" if open_findings else "compliant"
        except Exception:
            pass

        # 汇总异常
        issues = []
        if record["health_score"] is not None and record["health_score"] < 50:
            issues.append(f"健康评分 {record['health_score']}")
        if record["alert_count"] > 0:
            issues.append(f"{record['alert_count']} 条告警")
        if record["compliance_status"] == "non-compliant":
            issues.append("合规偏离")
        record["issue_summary"] = "; ".join(issues) if issues else ""

        results.append(record)
        print(f"  [{hostname}] 完成 — 评分: {record['health_score']}, 状态: {record['health_status']}")

    # 生成报告
    report = generate_report(results)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n报告已生成: {args.output}")

    # 同时输出 JSON
    json_path = args.output.replace(".md", ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"JSON 数据: {json_path}")


if __name__ == "__main__":
    main()
