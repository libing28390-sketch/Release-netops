"""Read-only, vendor-bound diagnostic orchestration for Copilot.

The orchestrator owns the diagnosis state machine and command contract.  It
never accepts a write command, never infers a vendor from a model name, and
does not open a device connection unless the caller explicitly authorizes a
planned read-only step.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Mapping

from ai.security.minimizer import minimize_tool_result
from ai.security.sanitizer import sanitize_text
from core.enum_compat import StrEnum


class DiagnosisState(StrEnum):
    SYMPTOM = "symptom"
    SCOPE = "scope"
    HYPOTHESIS = "hypothesis"
    EVIDENCE = "evidence"
    CHECK = "check"
    CONCLUSION = "conclusion"
    REMEDIATION = "remediation"
    VERIFICATION = "verification"
    COMPLETED = "completed"
    FAILED = "failed"


class DiagnosticErrorCode(StrEnum):
    AUTH_FAILED = "DIA_SSH_AUTH_FAILED"
    TIMEOUT = "DIA_TCP_TIMEOUT"
    UNREACHABLE = "DIA_UNREACHABLE"
    UNSUPPORTED = "DIA_COMMAND_UNSUPPORTED"
    PARSE_FAILED = "DIA_PARSE_FAILED"
    NOT_AUTHORIZED = "DIA_NOT_AUTHORIZED"
    PLATFORM_REQUIRED = "DIA_PLATFORM_REQUIRED"
    DRIVER_FAILED = "DIA_DRIVER_FAILED"


class DiagnosticOrchestrationError(ValueError):
    def __init__(self, code: DiagnosticErrorCode, message: str = "diagnostic operation failed"):
        super().__init__(message)
        self.code = code
        self.user_message = {
            DiagnosticErrorCode.AUTH_FAILED: "设备认证失败，请检查授权凭据。",
            DiagnosticErrorCode.TIMEOUT: "设备响应超时，请确认管理面可达。",
            DiagnosticErrorCode.UNREACHABLE: "设备当前不可达。",
            DiagnosticErrorCode.UNSUPPORTED: "当前平台不支持该只读检查。",
            DiagnosticErrorCode.PARSE_FAILED: "命令输出无法解析，请补充原始输出或选择对应平台。",
            DiagnosticErrorCode.NOT_AUTHORIZED: "该只读检查尚未获得本次授权。",
            DiagnosticErrorCode.PLATFORM_REQUIRED: "缺少明确的设备平台，未回退到其他厂商命令。",
            DiagnosticErrorCode.DRIVER_FAILED: "只读驱动执行失败。",
        }[code]


@dataclass(frozen=True)
class CommandSpec:
    vendor: str
    platform: str
    purpose: str
    command: str
    read_only: bool = True
    timeout_seconds: float = 8.0


@dataclass
class DiagnosticStep:
    step_no: int
    purpose: str
    command: str | None
    target: str
    status: str = "planned"
    evidence: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0
    error_code: str | None = None
    authorization_required: bool = True
    evidence_hash: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_no": self.step_no,
            "purpose": self.purpose,
            "command": self.command,
            "target": self.target,
            "status": self.status,
            "evidence": self.evidence,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "authorization_required": self.authorization_required,
            "evidence_hash": self.evidence_hash,
        }


PLAYBOOKS: dict[str, tuple[str, ...]] = {
    "unreachable": ("ping", "tcp", "ssh"),
    "interface_down": ("interface_status",),
    "interface_flap": ("interface_status", "interface_history"),
    "ospf": ("interface_status", "ospf_neighbors"),
    "bgp": ("interface_status", "bgp_summary"),
    "packet_loss": ("ping", "interface_status", "interface_counters"),
    "cpu": ("cpu",),
    "memory": ("memory",),
}


COMMANDS: dict[tuple[str, str, str], str] = {
    ("cisco", "ios", "interface_status"): "show ip interface brief",
    ("cisco", "ios_xe", "interface_status"): "show ip interface brief",
    ("cisco", "ios", "ospf_neighbors"): "show ip ospf neighbor",
    ("cisco", "ios_xe", "ospf_neighbors"): "show ip ospf neighbor",
    ("cisco", "ios", "bgp_summary"): "show ip bgp summary",
    ("cisco", "ios_xe", "bgp_summary"): "show ip bgp summary",
    ("cisco", "ios", "cpu"): "show processes cpu sorted",
    ("cisco", "ios_xe", "cpu"): "show processes cpu sorted",
    ("cisco", "ios", "memory"): "show processes memory sorted",
    ("cisco", "ios_xe", "memory"): "show processes memory sorted",
    ("huawei", "vrp", "interface_status"): "display ip interface brief",
    ("huawei", "vrp", "ospf_neighbors"): "display ospf peer",
    ("huawei", "vrp", "bgp_summary"): "display bgp peer",
    ("huawei", "vrp", "cpu"): "display cpu-usage",
    ("huawei", "vrp", "memory"): "display memory-usage",
    ("h3c", "comware", "interface_status"): "display ip interface brief",
    ("h3c", "comware", "ospf_neighbors"): "display ospf peer",
    ("h3c", "comware", "bgp_summary"): "display bgp peer",
    ("h3c", "comware", "cpu"): "display cpu-usage",
    ("h3c", "comware", "memory"): "display memory",
}


def normalize_interface_name(value: str) -> str:
    raw = re.sub(r"\s+", "", str(value or "").strip())
    replacements = (
        (r"(?i)^(?:tengigabitethernet|tenge)", "TenGigabitEthernet"),
        (r"(?i)^te", "TenGigabitEthernet"),
        (r"(?i)^xge", "TenGigabitEthernet"),
        (r"(?i)^10ge", "TenGigabitEthernet"),
        (r"(?i)^gigabitethernet", "GigabitEthernet"),
        (r"(?i)^ge", "GigabitEthernet"),
        (r"(?i)^ethernet", "Ethernet"),
    )
    for pattern, prefix in replacements:
        match = re.match(pattern + r"(.+)$", raw)
        if match:
            return f"{prefix}{match.group(1)}"
    return raw


def _normalize_vendor(value: str | None) -> str:
    vendor = str(value or "").strip().lower().replace(" ", "_")
    aliases = {"cisco_systems": "cisco", "huawei_technologies": "huawei", "hp": "h3c", "comware": "h3c"}
    return aliases.get(vendor, vendor)


def _normalize_platform(value: str | None) -> str:
    platform = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {"iosxe": "ios_xe", "ios_xe": "ios_xe", "ios": "ios", "vrp5": "vrp", "vrp8": "vrp", "comware7": "comware"}
    return aliases.get(platform, platform)


def command_contract(vendor: str | None, platform: str | None, purpose: str) -> CommandSpec:
    normalized_vendor = _normalize_vendor(vendor)
    normalized_platform = _normalize_platform(platform)
    if not normalized_vendor or not normalized_platform:
        raise DiagnosticOrchestrationError(DiagnosticErrorCode.PLATFORM_REQUIRED)
    command = COMMANDS.get((normalized_vendor, normalized_platform, purpose))
    if not command:
        raise DiagnosticOrchestrationError(DiagnosticErrorCode.UNSUPPORTED)
    return CommandSpec(normalized_vendor, normalized_platform, purpose, command)


def parse_cli_output(output: str, *, vendor: str | None, platform: str | None, purpose: str) -> list[dict[str, Any]]:
    if not str(platform or "").strip():
        raise DiagnosticOrchestrationError(DiagnosticErrorCode.PLATFORM_REQUIRED)
    text = str(output or "")
    if not text.strip():
        raise DiagnosticOrchestrationError(DiagnosticErrorCode.PARSE_FAILED)
    findings: list[dict[str, Any]] = []
    if purpose == "interface_status":
        for line in text.splitlines():
            match = re.match(r"\s*([^\s]+)\s+[^\s]+\s+(up|down)\s+(up|down)\s*$", line, re.I)
            if match:
                findings.append({"interface": normalize_interface_name(match.group(1)), "status": f"{match.group(2).lower()}/{match.group(3).lower()}"})
    elif purpose in {"ospf_neighbors", "bgp_summary"}:
        findings = [{"line": sanitize_text(line)[:240]} for line in text.splitlines() if line.strip() and not line.lstrip().startswith(("<", "#"))][:50]
    elif purpose in {"cpu", "memory"}:
        values = re.findall(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%", text)
        findings = [{"utilization_percent": float(value)} for value in values[:10]]
    else:
        findings = [{"line": sanitize_text(line)[:240]} for line in text.splitlines() if line.strip()][:50]
    if not findings:
        raise DiagnosticOrchestrationError(DiagnosticErrorCode.PARSE_FAILED)
    return findings


class DiagnosticOrchestrator:
    def __init__(self, *, probe: Callable[[CommandSpec, Mapping[str, Any]], Awaitable[Any]] | None = None, max_concurrency: int = 3):
        self.probe = probe
        self._semaphore = asyncio.Semaphore(max(1, min(int(max_concurrency), 8)))

    def build_plan(self, *, symptom: str, playbook: str, vendor: str | None, platform: str | None, target: str, device_id: str | None = None) -> dict[str, Any]:
        if playbook not in PLAYBOOKS:
            raise ValueError("unsupported diagnostic playbook")
        steps: list[DiagnosticStep] = []
        for index, purpose in enumerate(PLAYBOOKS[playbook], start=1):
            command: str | None = None
            if purpose not in {"ping", "tcp", "ssh"}:
                command = command_contract(vendor, platform, purpose).command
            steps.append(DiagnosticStep(index, purpose, command, target))
        return {
            "run_id": f"dia_{uuid.uuid4().hex[:16]}",
            "state": DiagnosisState.SYMPTOM.value,
            "symptom": sanitize_text(symptom)[:1000],
            "playbook": playbook,
            "vendor": _normalize_vendor(vendor) if vendor else None,
            "platform": _normalize_platform(platform) if platform else None,
            "device_id": device_id,
            "read_only": True,
            "steps": [step.as_dict() for step in steps],
            "write_operations_enabled": False,
        }

    async def run(
        self,
        *,
        plan: Mapping[str, Any],
        authorized_steps: Iterable[int] = (),
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        authorized = {int(item) for item in authorized_steps}
        state = DiagnosisState.EVIDENCE
        steps: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        latest_fingerprints: set[str] = set()
        for raw_step in plan.get("steps") or []:
            step = DiagnosticStep(
                int(raw_step.get("step_no") or len(steps) + 1),
                str(raw_step.get("purpose") or "check"),
                raw_step.get("command"),
                str(raw_step.get("target") or "unknown"),
            )
            if step.step_no not in authorized:
                step.status = "skipped"
                step.error_code = DiagnosticErrorCode.NOT_AUTHORIZED.value
                steps.append(step.as_dict())
                continue
            fingerprint = hashlib.sha256(f"{step.purpose}|{step.command}|{step.target}".encode()).hexdigest()
            if fingerprint in latest_fingerprints:
                step.status = "skipped"
                step.error_code = "DIA_NO_INFORMATION_GAIN"
                steps.append(step.as_dict())
                continue
            latest_fingerprints.add(fingerprint)
            started = time.perf_counter()
            try:
                async with self._semaphore:
                    if self.probe is None:
                        raise DiagnosticOrchestrationError(DiagnosticErrorCode.UNREACHABLE)
                    spec = command_contract(plan.get("vendor"), plan.get("platform"), step.purpose) if step.command else CommandSpec(str(plan.get("vendor") or "network"), str(plan.get("platform") or "probe"), step.purpose, step.purpose)
                    output = await asyncio.wait_for(self.probe(spec, context or {}), timeout=spec.timeout_seconds)
                if isinstance(output, str):
                    parsed = parse_cli_output(output, vendor=plan.get("vendor"), platform=plan.get("platform"), purpose=step.purpose)
                elif isinstance(output, Mapping):
                    parsed = [dict(output)]
                else:
                    parsed = [{"value": output}]
                step.status = "passed"
                step.evidence = minimize_tool_result({"items": parsed}).get("items", [])[:50]
                evidence.extend(step.evidence)
            except asyncio.TimeoutError:
                step.status = "failed"
                step.error_code = DiagnosticErrorCode.TIMEOUT.value
            except DiagnosticOrchestrationError as exc:
                step.status = "failed"
                step.error_code = exc.code.value
            except PermissionError:
                step.status = "failed"
                step.error_code = DiagnosticErrorCode.AUTH_FAILED.value
            except Exception:
                step.status = "failed"
                step.error_code = DiagnosticErrorCode.DRIVER_FAILED.value
            step.duration_ms = max(0, int((time.perf_counter() - started) * 1000))
            step.evidence_hash = hashlib.sha256(repr(step.evidence).encode()).hexdigest()[:16] if step.evidence else None
            steps.append(step.as_dict())
        passed = [item for item in steps if item["status"] == "passed"]
        failed = [item for item in steps if item["status"] == "failed"]
        state = DiagnosisState.CONCLUSION if passed else DiagnosisState.FAILED
        return {
            "run_id": plan.get("run_id"),
            "state": state.value,
            "symptom": plan.get("symptom"),
            "hypotheses": self._hypotheses(plan.get("playbook"), passed, failed),
            "steps": steps,
            "evidence": evidence[:100],
            "conclusion": "证据已收集，需结合现场确认" if passed else "未获得足够只读证据",
            "next_checks": ["复核失败步骤的稳定错误码", "补充平台/版本或粘贴 CLI 输出", "确认影响范围后再进行变更审批"],
            "read_only": True,
            "write_operations_enabled": False,
        }

    @staticmethod
    def _hypotheses(playbook: str | None, passed: list[dict[str, Any]], failed: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not passed:
            return [{"hypothesis": "当前证据不足", "confidence": 0.2, "status": "unconfirmed"}]
        return [{"hypothesis": f"{playbook or 'network'} 路径存在需要进一步核验的信号", "confidence": 0.55, "status": "candidate", "supporting_steps": [item["step_no"] for item in passed]}]


diagnostic_orchestrator = DiagnosticOrchestrator()
