"""PAM command-stream assembly, canonical actions and immutable audit events."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from database import get_db_connection
from ai.security.sanitizer import sanitize_text


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class CommandAssembler:
    """Reconstruct submitted commands from terminal keystrokes.

    It handles control characters and cursor movement without persisting a raw
    keystroke stream. Callers receive a completed line only on Enter.
    """

    def __init__(self):
        self.buffer: list[str] = []
        self.cursor = 0
        self._escape = ""

    @property
    def text(self) -> str:
        return "".join(self.buffer)

    def _reset(self) -> str | None:
        command = self.text.strip()
        self.buffer = []
        self.cursor = 0
        self._escape = ""
        return command or None

    def feed(self, data: str) -> list[str]:
        completed: list[str] = []
        for char in str(data or ""):
            if self._escape:
                self._escape += char
                # CSI cursor controls: ESC [ D/C/H/F/3~
                if self._escape.startswith("\x1b["):
                    if char in "DC":
                        self.cursor = max(0, min(len(self.buffer), self.cursor + (1 if char == "C" else -1)))
                        self._escape = ""
                    elif char in "HF":
                        self.cursor = 0 if char == "H" else len(self.buffer)
                        self._escape = ""
                    elif char == "~":
                        if self._escape.endswith("3~") and self.cursor < len(self.buffer):
                            self.buffer.pop(self.cursor)
                        self._escape = ""
                    elif len(self._escape) > 8:
                        self._escape = ""
                elif len(self._escape) > 8:
                    self._escape = ""
                continue
            if char == "\x1b":
                self._escape = char
                continue
            if char in "\r\n":
                command = self._reset()
                if command:
                    completed.append(command)
                continue
            if char in "\x08\x7f":
                if self.cursor > 0:
                    self.cursor -= 1
                    self.buffer.pop(self.cursor)
                continue
            if char == "\x15":  # Ctrl-U
                self.buffer = []
                self.cursor = 0
                continue
            if char == "\x17":  # Ctrl-W
                while self.cursor > 0 and self.buffer[self.cursor - 1].isspace():
                    self.cursor -= 1
                    self.buffer.pop(self.cursor)
                while self.cursor > 0 and not self.buffer[self.cursor - 1].isspace():
                    self.cursor -= 1
                    self.buffer.pop(self.cursor)
                continue
            if ord(char) < 32:
                continue
            self.buffer.insert(self.cursor, char)
            self.cursor += 1
        return completed


def is_bare_terminal_enter(data: str) -> bool:
    """Return whether terminal input is only an Enter control sequence.

    A bare Enter is a terminal control action (for example, to refresh a
    Cisco prompt), not a command. PAM still audits and gates non-empty lines;
    this helper only identifies the empty-line case for the SSH relay.
    """
    return str(data or "") in {"\r", "\n", "\r\n"}


@dataclass(frozen=True)
class PromptContext:
    vendor_platform: str
    hostname: str
    mode: str
    privilege: str


class PromptParser:
    _PROMPT = re.compile(r"(?:^|\n)\s*(?P<body>[A-Za-z0-9_.:/-]*(?:[>#\]])|<[^>\r\n]+>)\s*$")

    def parse(self, prompt: str, *, vendor_platform: str = "unknown") -> PromptContext:
        lines = str(prompt or "").strip().splitlines()
        if not lines:
            return PromptContext(
                vendor_platform=vendor_platform,
                hostname="unknown",
                mode="unknown",
                privilege="unknown",
            )
        text = lines[-1].strip()
        hostname = text.strip("<>[]#>$ ") or "unknown"
        if text.startswith("<") and text.endswith(">"):
            mode, privilege = "exec", "user"
        elif text.endswith("]"):
            mode, privilege = "config", "privileged"
        elif text.endswith("#"):
            mode, privilege = "exec", "privileged"
        elif text.endswith(">"):
            mode, privilege = "exec", "user"
        elif text.endswith("$"):
            mode, privilege = "shell", "user"
        else:
            mode, privilege = "unknown", "unknown"
        return PromptContext(str(vendor_platform or "unknown"), hostname, mode, privilege)


@dataclass(frozen=True)
class CommandDecision:
    command_safe: str
    canonical_action: str
    risk_level: str
    risk_score: int
    risk_dimensions: dict[str, Any]
    policy_decision: str
    confirmation_required: bool
    reason_code: str


def canonical_action(command: str, *, vendor_platform: str = "unknown") -> str:
    normalized = re.sub(r"\s+", " ", str(command or "").strip().lower())
    if not normalized:
        return "EMPTY"
    if re.search(r"(?:password|passwd|secret|community|api[-_ ]?key|private[-_ ]?key)", normalized):
        return "CREDENTIAL_INPUT"
    if re.search(r"(?:reload|reboot|shutdown|erase|format|rm\s+-rf|drop\s+table|truncate|delete\s+from)", normalized):
        return "DESTRUCTIVE_CHANGE"
    if re.search(r"(?:configure terminal|conf t|system-view|interface\s+|commit|write(?: memory)?|save|undo\s+)", normalized):
        return "CONFIG_CHANGE"
    if re.search(r"(?:show|display)\s+(?:running-config|current-configuration)", normalized):
        return "READ_FULL_CONFIGURATION"
    if re.search(r"(?:show|display)\s+", normalized):
        return "READ_OPERATIONAL_STATE"
    if normalized.startswith(("get ", "cat ", "ip ", "ping ", "traceroute ")):
        return "READ_OPERATIONAL_STATE"
    return "OTHER_COMMAND"


def redact_command_input(command: str) -> str:
    """Remove secret values before a command enters any audit projection."""
    safe = str(command or "")
    safe = re.sub(
        r"(?is)(\b(?:password|passwd|secret|community|token|api[_ -]?key|access[_ -]?token|private[_ -]?key|pre-shared-key|key-string)\b\s*(?:[:=]|cipher|simple|hash|7|8|9)?\s*)([^\s,;]+)",
        r"\1<REDACTED>",
        safe,
    )
    safe = re.sub(r"(?is)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", "<REDACTED_PRIVATE_KEY>", safe)
    return safe


def assess_command(
    command: str,
    *,
    vendor_platform: str = "unknown",
    context: dict[str, Any] | None = None,
    asset: dict[str, Any] | None = None,
    source_type: str = "interactive",
    history: list[str] | None = None,
) -> CommandDecision:
    raw_command = re.sub(r"\s+", " ", str(command or "").strip())
    safe_command = redact_command_input(raw_command)
    action = canonical_action(raw_command, vendor_platform=vendor_platform)
    lowered = raw_command.lower()
    dimensions: dict[str, Any] = {
        "command": action,
        "context": str((context or {}).get("change_window") or "normal"),
        "asset_criticality": str((asset or {}).get("criticality") or "normal"),
        "source_type": source_type,
        "history_repeats": sum(1 for item in (history or []) if item.strip().lower() == lowered),
    }
    if action == "CREDENTIAL_INPUT" or "-----begin" in lowered:
        return CommandDecision(safe_command, action, "L4", 100, dimensions, "BLOCK", False, "secret_input")
    if action == "DESTRUCTIVE_CHANGE":
        return CommandDecision(safe_command, action, "L4", 95, dimensions, "BLOCK", False, "destructive_command")
    if action == "CONFIG_CHANGE":
        score = 70
        if dimensions["asset_criticality"] in {"critical", "high"}:
            score += 15
        if dimensions["context"] not in {"approved", "change_window"}:
            score += 10
        return CommandDecision(safe_command, action, "L3", min(score, 94), dimensions, "CONFIRM", True, "write_requires_approval")
    if action == "READ_FULL_CONFIGURATION":
        return CommandDecision(safe_command, action, "L3", 60, dimensions, "CONFIRM", True, "full_config_sensitive")
    if action == "READ_OPERATIONAL_STATE":
        return CommandDecision(safe_command, action, "L1", 15, dimensions, "ALLOW", False, "read_only")
    return CommandDecision(safe_command, action, "L2", 30, dimensions, "ALLOW", False, "unclassified_command")


def redact_output(output: str) -> tuple[str, list[str]]:
    raw = str(output or "")
    safe = sanitize_text(raw)
    categories: list[str] = []
    safe = re.sub(
        r"(?i)(\b(?:password|passwd|secret|community|token|api[_ -]?key|private[_ -]?key)\b\s*(?:[:=]|\s)\s*)([^\s,;]+)",
        r"\1<REDACTED>",
        safe,
    )
    if safe != raw:
        categories.append("credential")
    if re.search(r"-----BEGIN .*PRIVATE KEY-----", raw, re.IGNORECASE):
        categories.append("private_key")
    return safe, sorted(set(categories))


def hash_event(event: dict[str, Any], previous_hash: str | None = None) -> str:
    body = json.dumps({"previous_hash": previous_hash or "", **event}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def record_operation_event(
    *,
    tenant_id: str,
    session_id: str | None,
    actor_id: str | None,
    device_id: str | None,
    source_type: str,
    action_code: str,
    decision: CommandDecision,
    previous_hash: str | None = None,
) -> dict[str, Any]:
    safe_event = {
        "tenant_id": tenant_id,
        "session_id": session_id,
        "source_type": source_type,
        "actor_id": actor_id,
        "device_id": device_id,
        "action_code": action_code,
        "risk_level": decision.risk_level,
        "policy_decision": decision.policy_decision,
        "accepted_state": "pending" if decision.policy_decision == "CONFIRM" else "accepted" if decision.policy_decision == "ALLOW" else "blocked",
        "metadata": {"risk_dimensions": decision.risk_dimensions, "reason_code": decision.reason_code},
    }
    event_hash = hash_event(safe_event, previous_hash)
    event_id = f"ope_{uuid.uuid4().hex[:16]}"
    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO pam_operation_events
                    (id, tenant_id, session_id, source_type, actor_id, device_id,
                     action_code, risk_level, policy_decision, accepted_state,
                     metadata_json, previous_hash, event_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id, tenant_id, session_id, source_type, actor_id, device_id,
                    action_code, decision.risk_level, decision.policy_decision,
                    safe_event["accepted_state"], json.dumps(safe_event["metadata"], ensure_ascii=False),
                    previous_hash, event_hash, _now(),
                ),
            )
            conn.commit()
    except Exception:
        # A missing migration must not make the live terminal write raw data;
        # callers still receive the hash-chain event for an in-memory/audit
        # retry queue.
        pass
    return {"id": event_id, "event_hash": event_hash, **safe_event}


def record_command_event(
    *,
    session_id: str,
    command_index: int,
    decision: CommandDecision,
    vendor_platform: str,
    cli_mode: str,
    operation_event_id: str | None = None,
) -> dict[str, Any]:
    event_id = f"cmd_{uuid.uuid4().hex[:16]}"
    safe = {
        "id": event_id,
        "operation_event_id": operation_event_id,
        "session_id": session_id,
        "command_index": int(command_index),
        "command_safe": decision.command_safe,
        "canonical_action": decision.canonical_action,
        "vendor_platform": vendor_platform,
        "cli_mode": cli_mode,
        "risk_level": decision.risk_level,
        "risk_dimensions": decision.risk_dimensions,
        "policy_decision": decision.policy_decision,
        "confirmation_required": decision.confirmation_required,
        "accepted_state": "pending" if decision.policy_decision == "CONFIRM" else "accepted" if decision.policy_decision == "ALLOW" else "blocked",
        "execution_status": "blocked" if decision.policy_decision == "BLOCK" else "pending",
        "created_at": _now(),
    }
    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO pam_command_events
                    (id, operation_event_id, session_id, command_index, command_safe,
                     canonical_action, vendor_platform, cli_mode, risk_level,
                    risk_dimensions_json, policy_decision, confirmation_required, accepted_state, execution_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    safe["id"], operation_event_id, session_id, safe["command_index"], safe["command_safe"],
                    safe["canonical_action"], vendor_platform, cli_mode, decision.risk_level,
                    json.dumps(decision.risk_dimensions, ensure_ascii=False), decision.policy_decision,
                    int(decision.confirmation_required), safe["accepted_state"], safe["execution_status"], safe["created_at"],
                ),
            )
            # Keep the session list and replay index consistent with the
            # structured command projection. The command index is monotonic
            # per session, so this is safe for retries and duplicate writes.
            conn.execute(
                "UPDATE pam_sessions SET command_count = CASE WHEN COALESCE(command_count, 0) < ? THEN ? ELSE command_count END WHERE id = ?",
                (safe["command_index"], safe["command_index"], session_id),
            )
            conn.commit()
    except Exception:
        pass
    return safe


def build_command_submission(
    *,
    tenant_id: str,
    session_id: str,
    actor_id: str | None,
    device_id: str | None,
    source_type: str,
    command_index: int,
    decision: CommandDecision,
    vendor_platform: str,
    cli_mode: str,
    previous_hash: str | None = None,
    enforcement_mode: str = "enforced",
) -> dict[str, dict[str, Any]]:
    """Build the in-memory audit projection without performing database I/O.

    The interactive relay needs the decision and event identifiers immediately,
    while PostgreSQL persistence is performed by ``persist_command_submission``
    after the terminal has received the command/output.
    """
    now = _now()
    audit_only = enforcement_mode == "audit_only"
    recorded_policy_decision = "AUDIT" if audit_only else decision.policy_decision
    accepted_state = "accepted" if audit_only or decision.policy_decision == "ALLOW" else "pending" if decision.policy_decision == "CONFIRM" else "blocked"
    execution_status = "executing" if audit_only else "blocked" if decision.policy_decision == "BLOCK" else "pending"
    operation_event_id = f"ope_{uuid.uuid4().hex[:16]}"
    operation_payload = {
        "tenant_id": tenant_id,
        "session_id": session_id,
        "source_type": source_type,
        "actor_id": actor_id,
        "device_id": device_id,
        "action_code": decision.canonical_action,
        "risk_level": decision.risk_level,
        "policy_decision": recorded_policy_decision,
        "accepted_state": accepted_state,
        "metadata": {
            "risk_dimensions": decision.risk_dimensions,
            "reason_code": decision.reason_code,
            "enforcement_mode": enforcement_mode,
            "recommended_policy_decision": decision.policy_decision,
        },
    }
    operation_hash = hash_event(operation_payload, previous_hash)
    operation = {
        "id": operation_event_id,
        "event_hash": operation_hash,
        "previous_hash": previous_hash,
        "created_at": now,
        **operation_payload,
    }

    command_event_id = f"cmd_{uuid.uuid4().hex[:16]}"
    command = {
        "id": command_event_id,
        "operation_event_id": operation_event_id,
        "session_id": session_id,
        "command_index": int(command_index),
        "command_safe": decision.command_safe,
        "canonical_action": decision.canonical_action,
        "vendor_platform": vendor_platform,
        "cli_mode": cli_mode,
        "risk_level": decision.risk_level,
        "risk_dimensions": decision.risk_dimensions,
        "policy_decision": recorded_policy_decision,
        "confirmation_required": decision.confirmation_required,
        "accepted_state": accepted_state,
        "execution_status": execution_status,
        "created_at": now,
    }

    return {"operation": operation, "command": command}


def persist_command_submission(submission: dict[str, dict[str, Any]]) -> None:
    """Persist a built command projection in one PostgreSQL transaction."""
    operation = submission["operation"]
    command = submission["command"]
    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO pam_operation_events
                    (id, tenant_id, session_id, source_type, actor_id, device_id,
                     action_code, risk_level, policy_decision, accepted_state,
                     metadata_json, previous_hash, event_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation["id"], operation["tenant_id"], operation["session_id"],
                    operation["source_type"], operation["actor_id"], operation["device_id"],
                    operation["action_code"], operation["risk_level"], operation["policy_decision"],
                    operation["accepted_state"], json.dumps(operation["metadata"], ensure_ascii=False),
                    operation.get("previous_hash"), operation["event_hash"], operation["created_at"],
                ),
            )
            conn.execute(
                """
                INSERT INTO pam_command_events
                    (id, operation_event_id, session_id, command_index, command_safe,
                     canonical_action, vendor_platform, cli_mode, risk_level,
                     risk_dimensions_json, policy_decision, confirmation_required,
                     accepted_state, execution_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command["id"], command["operation_event_id"], command["session_id"],
                    command["command_index"], command["command_safe"], command["canonical_action"],
                    command["vendor_platform"], command["cli_mode"], command["risk_level"],
                    json.dumps(command["risk_dimensions"], ensure_ascii=False), command["policy_decision"],
                    int(command["confirmation_required"]), command["accepted_state"],
                    command["execution_status"], command["created_at"],
                ),
            )
            conn.execute(
                """
                UPDATE pam_sessions
                SET last_event_hash = ?,
                    command_count = CASE WHEN COALESCE(command_count, 0) < ? THEN ? ELSE command_count END,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    operation["event_hash"], command["command_index"], command["command_index"],
                    operation["created_at"], command["session_id"],
                ),
            )
            conn.commit()
    except Exception:
        # Audit persistence must not make the interactive terminal unusable.
        pass


def record_command_submission(
    *,
    tenant_id: str,
    session_id: str,
    actor_id: str | None,
    device_id: str | None,
    source_type: str,
    command_index: int,
    decision: CommandDecision,
    vendor_platform: str,
    cli_mode: str,
    previous_hash: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Build and synchronously persist one command for non-interactive callers."""
    submission = build_command_submission(
        tenant_id=tenant_id,
        session_id=session_id,
        actor_id=actor_id,
        device_id=device_id,
        source_type=source_type,
        command_index=command_index,
        decision=decision,
        vendor_platform=vendor_platform,
        cli_mode=cli_mode,
        previous_hash=previous_hash,
    )
    persist_command_submission(submission)
    return submission


def mark_command_event(command_event_id: str, *, accepted_state: str | None = None, execution_status: str | None = None, started_at: str | None = None, finished_at: str | None = None) -> None:
    """Advance execution state without changing the original command decision."""
    assignments: list[str] = []
    params: list[Any] = []
    for column, value in (("accepted_state", accepted_state), ("execution_status", execution_status), ("started_at", started_at), ("finished_at", finished_at)):
        if value is not None:
            assignments.append(f"{column} = ?")
            params.append(value)
    if not assignments:
        return
    params.append(command_event_id)
    try:
        with get_db_connection() as conn:
            conn.execute(f"UPDATE pam_command_events SET {', '.join(assignments)} WHERE id = ?", tuple(params))
            conn.commit()
    except Exception:
        pass


def record_command_output(*, command_event_id: str, output: str, device_state: str = "unknown") -> dict[str, Any]:
    safe_output, categories = redact_output(output)
    output_hash = hashlib.sha256(str(output or "").encode("utf-8", errors="replace")).hexdigest()
    result = {
        "id": f"out_{uuid.uuid4().hex[:16]}",
        "command_event_id": command_event_id,
        "output_safe": safe_output,
        "output_hash": output_hash,
        "device_state": device_state,
        "dlp_categories": categories,
        "created_at": _now(),
    }
    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO pam_command_outputs
                    (id, command_event_id, output_safe, output_hash, device_state,
                     dlp_categories_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result["id"], command_event_id, safe_output, output_hash, device_state,
                    json.dumps(categories), result["created_at"],
                ),
            )
            conn.commit()
    except Exception:
        pass
    return result


def create_approval_request(
    *,
    tenant_id: str,
    session_id: str | None,
    command_event_id: str,
    requester_id: str,
    reason: str = "",
    ttl_seconds: int = 900,
) -> dict[str, Any]:
    """Create a separate approval record for a CONFIRM command.

    Approval records contain only the command event reference and safe
    metadata. They never copy raw terminal input or output.
    """
    approval_id = f"apr_{uuid.uuid4().hex[:16]}"
    now = datetime.now(timezone.utc)
    expires_at = (now.timestamp() + max(60, min(int(ttl_seconds or 900), 86400)))
    expires_iso = datetime.fromtimestamp(expires_at, timezone.utc).replace(microsecond=0).isoformat()
    with get_db_connection() as conn:
        if session_id:
            row = conn.execute(
                """
                SELECT e.policy_decision, e.risk_level
                FROM pam_command_events e
                JOIN pam_sessions s ON s.id = e.session_id AND s.tenant_id = ?
                WHERE e.id = ? AND e.session_id = ?
                """,
                (tenant_id, command_event_id, session_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT policy_decision, risk_level FROM pam_command_events WHERE id = ?",
                (command_event_id,),
            ).fetchone()
        if not row:
            raise ValueError("command event not found")
        if str(row[0]) != "CONFIRM":
            raise ValueError("only CONFIRM commands may request approval")
        conn.execute(
            "INSERT INTO pam_approval_requests (id, tenant_id, session_id, command_event_id, requester_id, state, reason, expires_at, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
            (approval_id, tenant_id, session_id, command_event_id, requester_id, str(reason or "")[:500], expires_iso, _now()),
        )
        conn.execute("UPDATE pam_command_events SET accepted_state = 'pending', approval_id = ? WHERE id = ?", (approval_id, command_event_id))
        conn.commit()
    return {"id": approval_id, "tenant_id": tenant_id, "session_id": session_id, "command_event_id": command_event_id, "state": "pending", "expires_at": expires_iso}


def decide_approval(
    approval_id: str,
    *,
    approver_id: str,
    approved: bool,
    mfa_verified: bool,
    decision_note: str = "",
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Approve/deny a pending command, requiring a distinct MFA-verified approver."""
    with get_db_connection() as conn:
        if tenant_id:
            row = conn.execute("SELECT * FROM pam_approval_requests WHERE id = ? AND tenant_id = ?", (approval_id, tenant_id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM pam_approval_requests WHERE id = ?", (approval_id,)).fetchone()
        if not row:
            raise ValueError("approval request not found")
        item = dict(row)
        if item.get("state") != "pending":
            raise ValueError("approval request is no longer pending")
        if str(item.get("requester_id") or "") == str(approver_id or ""):
            raise ValueError("requester cannot approve their own command")
        expires_at = str(item.get("expires_at") or "")
        if expires_at and datetime.fromisoformat(expires_at.replace("Z", "+00:00")) < datetime.now(timezone.utc):
            conn.execute("UPDATE pam_approval_requests SET state = 'expired', decided_at = ? WHERE id = ?", (_now(), approval_id))
            conn.commit()
            raise ValueError("approval request expired")
        if approved and not mfa_verified:
            raise ValueError("MFA verification is required to approve")
        state = "approved" if approved else "denied"
        accepted = "accepted" if approved else "blocked"
        execution = "pending" if approved else "blocked"
        conn.execute(
            "UPDATE pam_approval_requests SET state = ?, approver_id = ?, mfa_verified = ?, decided_at = ?, decision_note = ? WHERE id = ?",
            (state, approver_id, int(bool(mfa_verified)), _now(), str(decision_note or "")[:500], approval_id),
        )
        conn.execute(
            "UPDATE pam_command_events SET accepted_state = ?, execution_status = ?, approval_id = ? WHERE id = ?",
            (accepted, execution, approval_id, item.get("command_event_id")),
        )
        conn.commit()
        return {"id": approval_id, "state": state, "approver_id": approver_id, "mfa_verified": bool(mfa_verified), "command_event_id": item.get("command_event_id")}


def create_change_transaction(
    *,
    tenant_id: str,
    session_id: str | None,
    device_id: str | None,
    created_by: str,
    ticket_id: str | None = None,
    risk_level: str = "L3",
    diff: dict[str, Any] | None = None,
    rollback_plan: dict[str, Any] | None = None,
    target_type: str | None = None,
    target_name: str | None = None,
    config_diff_id: str | None = None,
    commit_model: str = "direct",
) -> dict[str, Any]:
    """Create a durable change plan; execution remains outside this V1 API."""
    transaction_id = f"chg_{uuid.uuid4().hex[:16]}"
    now = _now()
    result = {
        "id": transaction_id, "tenant_id": tenant_id, "session_id": session_id,
        "device_id": device_id, "ticket_id": ticket_id, "state": "draft",
        "risk_level": str(risk_level or "L3"), "diff": diff or {},
        "rollback_plan": rollback_plan or {}, "created_by": created_by,
        "target_type": str(target_type or "device")[:80], "target_name": str(target_name or "")[:200],
        "config_diff_id": config_diff_id, "verification_state": "pending", "rollback_state": "not_requested",
        "commit_model": str(commit_model or "direct")[:40],
        "created_at": now, "updated_at": now,
    }
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO pam_change_transactions
                (id, tenant_id, session_id, device_id, ticket_id, state, risk_level,
                 before_snapshot_id, after_snapshot_id, diff_json, rollback_plan_json,
                 created_by, target_type, target_name, config_diff_id,
                 verification_state, rollback_state, commit_model, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'draft', ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (transaction_id, tenant_id, session_id, device_id, ticket_id, result["risk_level"],
             json.dumps(result["diff"], ensure_ascii=False), json.dumps(result["rollback_plan"], ensure_ascii=False),
             created_by, result["target_type"], result["target_name"], result["config_diff_id"],
             result["verification_state"], result["rollback_state"], result["commit_model"], now, now),
        )
        conn.commit()
    return result


def record_session_intervention(*, tenant_id: str, session_id: str, action: str, actor_id: str, reason: str = "") -> dict[str, Any]:
    action_value = str(action or "").strip().lower()
    if action_value not in {"pause", "resume", "terminate", "notify"}:
        raise ValueError("unsupported intervention")
    result = {"id": f"int_{uuid.uuid4().hex[:16]}", "tenant_id": tenant_id, "session_id": session_id, "action": action_value, "actor_id": actor_id, "reason": str(reason or "")[:500], "created_at": _now()}
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO pam_session_interventions (id, tenant_id, session_id, action, actor_id, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            tuple(result.values()),
        )
        conn.commit()
    return result


def _parse_time(value: str | None, *, default: datetime) -> datetime:
    if not value:
        return default
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid ISO-8601 time") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _risk_level(score: int) -> str:
    score = max(0, min(int(score), 100))
    if score >= 90:
        return "L4"
    if score >= 70:
        return "L3"
    if score >= 30:
        return "L2"
    return "L1"


def _safe_action_list(values: Any, *, limit: int = 100) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        values = [values] if values else []
    result: list[str] = []
    for value in values:
        item = re.sub(r"[^A-Za-z0-9_.:/-]", "_", str(value or "").strip())[:120]
        if item and item not in result:
            result.append(item)
        if len(result) >= limit:
            break
    return result


def create_jit_grant(
    *,
    tenant_id: str,
    subject_user_id: str,
    scope: dict[str, Any] | None,
    allowed_actions: list[str] | None,
    denied_actions: list[str] | None,
    created_by: str,
    reason: str,
    starts_at: str | None = None,
    ends_at: str | None = None,
    break_glass: bool = False,
    mfa_verified: bool = False,
) -> dict[str, Any]:
    """Create a time-bounded, least-privilege grant without changing devices."""
    now = datetime.now(timezone.utc)
    starts = _parse_time(starts_at, default=now)
    ends = _parse_time(ends_at, default=starts + timedelta(hours=1))
    max_duration = timedelta(hours=4 if break_glass else 24)
    if ends <= starts or ends - starts > max_duration:
        raise ValueError("JIT grant duration is outside the allowed window")
    if break_glass and (not mfa_verified or not str(reason or "").strip()):
        raise ValueError("break-glass grants require MFA and an incident reason")
    allowed = _safe_action_list(allowed_actions)
    denied = _safe_action_list(denied_actions)
    if set(allowed) & set(denied):
        raise ValueError("an action cannot be both allowed and denied")
    grant_id = f"jit_{uuid.uuid4().hex[:16]}"
    result = {
        "id": grant_id,
        "tenant_id": tenant_id,
        "subject_user_id": subject_user_id,
        "scope": dict(scope or {}),
        "allowed_actions": allowed,
        "denied_actions": denied,
        "starts_at": starts.replace(microsecond=0).isoformat(),
        "ends_at": ends.replace(microsecond=0).isoformat(),
        "reason": str(reason or "")[:500],
        "created_by": created_by,
        "state": "active",
        "break_glass": bool(break_glass),
        "mfa_verified": bool(mfa_verified),
        "created_at": _now(),
    }
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO pam_jit_grants
                (id, tenant_id, subject_user_id, scope_json, allowed_actions_json,
                 denied_actions_json, starts_at, ends_at, reason, created_by,
                 state, break_glass, mfa_verified, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (
                grant_id, tenant_id, subject_user_id,
                json.dumps(result["scope"], ensure_ascii=False),
                json.dumps(allowed, ensure_ascii=False),
                json.dumps(denied, ensure_ascii=False), result["starts_at"], result["ends_at"],
                result["reason"], created_by, int(bool(break_glass)), int(bool(mfa_verified)), result["created_at"],
            ),
        )
        if break_glass:
            conn.execute(
                "INSERT INTO pam_break_glass_events (id, tenant_id, grant_id, subject_user_id, reason, mfa_verified, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"bg_{uuid.uuid4().hex[:16]}", tenant_id, grant_id, subject_user_id, result["reason"], int(bool(mfa_verified)), result["created_at"]),
            )
        conn.commit()
    return result


def revoke_jit_grant(grant_id: str, *, tenant_id: str, actor_id: str) -> dict[str, Any]:
    """Revoke a grant; the actor is retained in the reason-safe audit field."""
    with get_db_connection() as conn:
        row = conn.execute("SELECT id, tenant_id, state FROM pam_jit_grants WHERE id = ? AND tenant_id = ?", (grant_id, tenant_id)).fetchone()
        if not row:
            raise ValueError("JIT grant not found")
        if str(row[2]) != "active":
            raise ValueError("JIT grant is not active")
        conn.execute("UPDATE pam_jit_grants SET state = 'revoked', revoked_at = ? WHERE id = ? AND tenant_id = ?", (_now(), grant_id, tenant_id))
        conn.commit()
    return {"id": grant_id, "tenant_id": tenant_id, "state": "revoked", "revoked_by": actor_id, "revoked_at": _now()}


def check_jit_grant(*, grant_id: str, tenant_id: str, subject_user_id: str, action: str, at: str | None = None) -> dict[str, Any]:
    """Evaluate a grant with fail-closed defaults for expired or unknown records."""
    moment = _parse_time(at, default=datetime.now(timezone.utc))
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM pam_jit_grants WHERE id = ? AND tenant_id = ? AND subject_user_id = ?", (grant_id, tenant_id, subject_user_id)).fetchone()
    if not row:
        return {"allowed": False, "reason": "grant_not_found"}
    item = dict(row)
    starts = _parse_time(item.get("starts_at"), default=moment)
    ends = _parse_time(item.get("ends_at"), default=moment)
    if item.get("state") != "active" or moment < starts or moment > ends:
        return {"allowed": False, "reason": "grant_inactive_or_expired", "grant_id": grant_id}
    try:
        allowed = set(json.loads(item.get("allowed_actions_json") or "[]"))
        denied = set(json.loads(item.get("denied_actions_json") or "[]"))
    except (TypeError, ValueError):
        return {"allowed": False, "reason": "grant_policy_corrupt", "grant_id": grant_id}
    action = str(action or "").strip()
    result = action in allowed and action not in denied
    try:
        scope = json.loads(item.get("scope_json") or "{}")
    except (TypeError, ValueError):
        return {"allowed": False, "reason": "grant_scope_corrupt", "grant_id": grant_id}
    return {"allowed": result, "reason": "allowed" if result else "action_not_granted", "grant_id": grant_id, "scope": scope if isinstance(scope, dict) else {}}


def review_break_glass(*, grant_id: str, tenant_id: str, reviewed_by: str, accepted: bool, note: str = "") -> dict[str, Any]:
    state = "accepted" if accepted else "rejected"
    with get_db_connection() as conn:
        row = conn.execute("SELECT id FROM pam_break_glass_events WHERE grant_id = ? AND tenant_id = ?", (grant_id, tenant_id)).fetchone()
        if not row:
            raise ValueError("break-glass event not found")
        conn.execute(
            "UPDATE pam_break_glass_events SET post_review_state = ?, reviewed_by = ?, reviewed_at = ?, reason = substr(reason || ' Review: ' || ?, 1, 1000) WHERE grant_id = ? AND tenant_id = ?",
            (state, reviewed_by, _now(), str(note or "")[:500], grant_id, tenant_id),
        )
        conn.commit()
    return {"grant_id": grant_id, "tenant_id": tenant_id, "post_review_state": state, "reviewed_by": reviewed_by, "reviewed_at": _now()}


def evaluate_file_transfer_policy(*, file_name: str, direction: str, approved: bool = False, mfa_verified: bool = False) -> dict[str, Any]:
    """Return a decision for file transfer metadata; never accepts file bytes."""
    safe_name = str(file_name or "").replace("\\", "/").split("/")[-1].strip()[:255]
    invalid_path = not safe_name or safe_name in {".", ".."} or ".." in safe_name
    normalized_direction = str(direction or "").upper()
    if normalized_direction not in {"UPLOAD", "DOWNLOAD"}:
        raise ValueError("unsupported file transfer direction")
    sensitive = bool(re.search(r"(?i)(startup-config|running-config|vrpcfg|\.cfg$|\.conf$|firmware|image)", safe_name))
    decision = "ALLOW"
    reason = "metadata_only_policy"
    if invalid_path:
        decision, reason = "BLOCK", "unsafe_file_name"
    elif sensitive and not (approved and mfa_verified):
        decision, reason = "BLOCK", "sensitive_file_requires_approval_and_mfa"
    return {"file_name_safe": safe_name or "<invalid>", "direction": normalized_direction, "policy_decision": decision, "reason": reason, "sensitive": sensitive}


def record_file_transfer(
    *,
    tenant_id: str,
    session_id: str | None,
    actor_id: str,
    file_name: str,
    direction: str,
    content_hash: str,
    size_bytes: int = 0,
    approved: bool = False,
    mfa_verified: bool = False,
) -> dict[str, Any]:
    policy = evaluate_file_transfer_policy(file_name=file_name, direction=direction, approved=approved, mfa_verified=mfa_verified)
    safe_hash = re.sub(r"[^A-Fa-f0-9]", "", str(content_hash or ""))[:128]
    result = {
        "id": f"file_{uuid.uuid4().hex[:16]}", "tenant_id": tenant_id, "session_id": session_id,
        "actor_id": actor_id, "file_name_safe": policy["file_name_safe"], "direction": policy["direction"],
        "content_hash": safe_hash, "size_bytes": max(0, min(int(size_bytes or 0), 2**63 - 1)),
        "policy_decision": policy["policy_decision"], "reason": policy["reason"], "created_at": _now(),
    }
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO pam_file_transfer_events (id, tenant_id, session_id, direction, file_name_safe, content_hash, size_bytes, policy_decision, actor_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (result["id"], tenant_id, session_id, result["direction"], result["file_name_safe"], result["content_hash"], result["size_bytes"], result["policy_decision"], actor_id, result["created_at"]),
        )
        conn.commit()
    return result


def calculate_batch_risk(*, command_risk_score: int, asset_criticality: str = "normal", target_count: int = 1, topology_impact: int = 0, concurrency: int = 1) -> dict[str, Any]:
    asset_weight = {"low": 5, "normal": 15, "high": 25, "critical": 35}.get(str(asset_criticality or "normal").lower(), 15)
    count = max(1, min(int(target_count or 1), 10000))
    concurrency = max(1, min(int(concurrency or 1), 100))
    score = min(100, max(0, int(command_risk_score)) * 0.45 + asset_weight + min(30, count.bit_length() * 5) + min(20, max(0, int(topology_impact))) + min(10, concurrency))
    score = int(round(score))
    return {"risk_score": score, "risk_level": _risk_level(score), "dimensions": {"command": int(command_risk_score), "asset": asset_weight, "target_count": count, "topology_impact": max(0, int(topology_impact)), "concurrency": concurrency}}


def create_batch_operation(*, tenant_id: str, created_by: str, target_ids: list[str], command_risk_score: int, asset_criticality: str = "normal", topology_impact: int = 0, concurrency: int = 1, canary_count: int = 1, failure_threshold: float = 0.1, change_transaction_id: str | None = None, scheduled_at: str | None = None) -> dict[str, Any]:
    target_ids = _safe_action_list(target_ids, limit=10000)
    if not target_ids:
        raise ValueError("batch operation requires targets")
    if not 0 < float(failure_threshold) <= 1:
        raise ValueError("failure threshold must be between 0 and 1")
    risk = calculate_batch_risk(command_risk_score=command_risk_score, asset_criticality=asset_criticality, target_count=len(target_ids), topology_impact=topology_impact, concurrency=concurrency)
    now = _now()
    operation_id = f"batch_{uuid.uuid4().hex[:16]}"
    result = {"id": operation_id, "tenant_id": tenant_id, "created_by": created_by, "state": "pending_approval", "target_ids": target_ids, "max_targets": len(target_ids), "concurrency": max(1, min(int(concurrency), 100)), "canary_count": max(0, min(int(canary_count), len(target_ids))), "failure_threshold": float(failure_threshold), "command_risk_level": risk["risk_level"], "blast_radius": risk, "change_transaction_id": change_transaction_id, "scheduled_at": scheduled_at, "completed_count": 0, "failed_count": 0, "created_at": now, "updated_at": now}
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO pam_batch_operations (id, tenant_id, created_by, state, target_ids_json, max_targets, concurrency, canary_count, failure_threshold, command_risk_level, blast_radius_json, change_transaction_id, scheduled_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (operation_id, tenant_id, created_by, result["state"], json.dumps(target_ids), result["max_targets"], result["concurrency"], result["canary_count"], result["failure_threshold"], result["command_risk_level"], json.dumps(risk, ensure_ascii=False), change_transaction_id, scheduled_at, now, now),
        )
        conn.commit()
    return result


def update_batch_progress(*, operation_id: str, tenant_id: str, completed_count: int, failed_count: int) -> dict[str, Any]:
    with get_db_connection() as conn:
        row = conn.execute("SELECT max_targets, failure_threshold, state FROM pam_batch_operations WHERE id = ? AND tenant_id = ?", (operation_id, tenant_id)).fetchone()
        if not row:
            raise ValueError("batch operation not found")
        total = max(0, int(completed_count)) + max(0, int(failed_count))
        failure_rate = (max(0, int(failed_count)) / total) if total else 0.0
        state = str(row[2])
        stopped_reason = None
        if failure_rate > float(row[1] or 0.1):
            state, stopped_reason = "stopped", "failure_rate_threshold_exceeded"
        elif total >= int(row[0] or 0):
            state = "completed"
        conn.execute("UPDATE pam_batch_operations SET state = ?, completed_count = ?, failed_count = ?, stopped_reason = ?, updated_at = ? WHERE id = ? AND tenant_id = ?", (state, max(0, int(completed_count)), max(0, int(failed_count)), stopped_reason, _now(), operation_id, tenant_id))
        conn.commit()
    return {"id": operation_id, "tenant_id": tenant_id, "state": state, "completed_count": max(0, int(completed_count)), "failed_count": max(0, int(failed_count)), "failure_rate": round(failure_rate, 4), "stopped_reason": stopped_reason}


def create_deferred_action(*, tenant_id: str, session_id: str | None, command_event_id: str | None, action_code: str, execute_at: str, created_by: str, risk_level: str = "L3", reason: str = "") -> dict[str, Any]:
    when = _parse_time(execute_at, default=datetime.now(timezone.utc))
    if when <= datetime.now(timezone.utc):
        raise ValueError("deferred action must be scheduled in the future")
    if str(action_code or "").upper() in {"CREDENTIAL_INPUT", "DESTRUCTIVE_CHANGE"}:
        raise ValueError("credential and destructive actions cannot be deferred")
    result = {"id": f"def_{uuid.uuid4().hex[:16]}", "tenant_id": tenant_id, "session_id": session_id, "command_event_id": command_event_id, "action_code": re.sub(r"[^A-Za-z0-9_.:/-]", "_", str(action_code or "OTHER"))[:120], "execute_at": when.replace(microsecond=0).isoformat(), "state": "scheduled", "risk_level": str(risk_level or "L3"), "reason": str(reason or "")[:500], "created_by": created_by, "created_at": _now(), "updated_at": _now()}
    with get_db_connection() as conn:
        conn.execute("INSERT INTO pam_deferred_actions (id, tenant_id, session_id, command_event_id, action_code, execute_at, state, risk_level, reason, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", tuple(result.values()))
        conn.commit()
    return result


def detect_behavior_risk(*, tenant_id: str, user_id: str | None, session_id: str | None, metrics: dict[str, Any]) -> dict[str, Any]:
    rules = {
        "many_sessions": int(metrics.get("concurrent_sessions") or 0) >= 5,
        "off_hours": bool(metrics.get("off_hours")),
        "blocked_commands": int(metrics.get("blocked_commands") or 0) >= 3,
        "critical_asset": bool(metrics.get("critical_asset")),
        "bulk_download": int(metrics.get("downloads") or 0) >= 10,
        "many_writes": int(metrics.get("write_commands") or 0) >= 20,
    }
    score = min(100, sum(20 if key in {"critical_asset", "blocked_commands"} else 15 for key, matched in rules.items() if matched))
    result = {"id": f"beh_{uuid.uuid4().hex[:16]}", "tenant_id": tenant_id, "user_id": user_id, "session_id": session_id, "risk_level": _risk_level(score), "risk_score": score, "signals": {key: value for key, value in rules.items() if value}, "state": "open" if score >= 30 else "informational", "created_at": _now()}
    if score >= 30:
        with get_db_connection() as conn:
            conn.execute("INSERT INTO pam_behavior_flags (id, tenant_id, user_id, session_id, risk_level, risk_score, signals_json, state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (result["id"], tenant_id, user_id, session_id, result["risk_level"], score, json.dumps(result["signals"], ensure_ascii=False), result["state"], result["created_at"]))
            conn.commit()
    return result


def reconcile_tacacs_event(*, tenant_id: str, session_id: str | None, command_event_id: str | None, nexora_action: str, external_action: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    safe_nexora = re.sub(r"[^A-Za-z0-9_.:/ -]", "_", str(nexora_action or "").strip())[:200]
    safe_external = re.sub(r"[^A-Za-z0-9_.:/ -]", "_", str(external_action or "").strip())[:200]
    matched = safe_nexora.casefold() == safe_external.casefold()
    result = {"id": f"tac_{uuid.uuid4().hex[:16]}", "tenant_id": tenant_id, "session_id": session_id, "command_event_id": command_event_id, "nexora_action": safe_nexora, "external_action": safe_external, "matched": matched, "details": {"mismatch": not matched, "metadata": dict(metadata or {})}, "created_at": _now()}
    with get_db_connection() as conn:
        conn.execute("INSERT INTO pam_tacacs_reconciliations (id, tenant_id, session_id, command_event_id, nexora_action, external_action, matched, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (result["id"], tenant_id, session_id, command_event_id, safe_nexora, safe_external, int(matched), json.dumps(result["details"], ensure_ascii=False), result["created_at"]))
        conn.commit()
    return result


def create_rollback_checkpoint(*, tenant_id: str, change_transaction_id: str, device_id: str | None, checkpoint_type: str = "pre_change", snapshot_id: str | None = None, details: dict[str, Any] | None = None) -> dict[str, Any]:
    if checkpoint_type not in {"pre_change", "post_change", "health_check"}:
        raise ValueError("unsupported checkpoint type")
    now = _now()
    result = {"id": f"chk_{uuid.uuid4().hex[:16]}", "tenant_id": tenant_id, "change_transaction_id": change_transaction_id, "device_id": device_id, "checkpoint_type": checkpoint_type, "snapshot_id": snapshot_id, "health_state": "unknown", "verification_state": "pending", "rollback_state": "not_requested", "details": dict(details or {}), "created_at": now, "updated_at": now}
    with get_db_connection() as conn:
        conn.execute("INSERT INTO pam_rollback_checkpoints (id, tenant_id, change_transaction_id, device_id, checkpoint_type, snapshot_id, details_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (result["id"], tenant_id, change_transaction_id, device_id, checkpoint_type, snapshot_id, json.dumps(result["details"], ensure_ascii=False), now, now))
        conn.commit()
    return result


def verify_rollback_checkpoint(*, checkpoint_id: str, tenant_id: str, health_state: str, passed: bool, details: dict[str, Any] | None = None) -> dict[str, Any]:
    state = str(health_state or "unknown").upper()
    if state not in {"UP", "DEGRADED", "DOWN", "UNKNOWN"}:
        raise ValueError("unsupported health state")
    verification = "passed" if passed else "failed"
    rollback_state = "not_requested" if passed else "requested"
    with get_db_connection() as conn:
        row = conn.execute("SELECT id FROM pam_rollback_checkpoints WHERE id = ? AND tenant_id = ?", (checkpoint_id, tenant_id)).fetchone()
        if not row:
            raise ValueError("rollback checkpoint not found")
        conn.execute("UPDATE pam_rollback_checkpoints SET health_state = ?, verification_state = ?, rollback_state = ?, details_json = ?, updated_at = ? WHERE id = ? AND tenant_id = ?", (state, verification, rollback_state, json.dumps(dict(details or {}), ensure_ascii=False), _now(), checkpoint_id, tenant_id))
        conn.commit()
    return {"id": checkpoint_id, "tenant_id": tenant_id, "health_state": state, "verification_state": verification, "rollback_state": rollback_state, "rollback_execution": "not_started" if not passed else "not_required"}


def generate_session_summary(*, tenant_id: str, session_id: str, generated_by: str = "deterministic") -> dict[str, Any]:
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT e.canonical_action, e.risk_level, e.policy_decision,
                   e.accepted_state, e.execution_status
            FROM pam_command_events e
            JOIN pam_sessions s ON s.id = e.session_id AND s.tenant_id = ?
            WHERE e.session_id = ?
            """,
            (tenant_id, session_id),
        ).fetchall()
        summary = {"session_id": session_id, "command_count": len(rows), "configuration_command_count": 0, "high_risk_count": 0, "blocked_count": 0, "commands_by_action": {}, "final_verification": "unknown"}
        for row in rows:
            action = str(row[0] or "OTHER_COMMAND")
            summary["commands_by_action"][action] = int(summary["commands_by_action"].get(action, 0)) + 1
            if action == "CONFIG_CHANGE":
                summary["configuration_command_count"] += 1
            if str(row[1] or "") in {"L3", "L4"}:
                summary["high_risk_count"] += 1
            if str(row[2] or "") == "BLOCK" or str(row[4] or "") == "blocked":
                summary["blocked_count"] += 1
        summary["final_verification"] = "PASS" if rows and summary["blocked_count"] == 0 else "REVIEW"
        summary["generated_at"] = _now()
        summary_id = f"sum_{uuid.uuid4().hex[:16]}"
        conn.execute("INSERT INTO pam_session_summaries (id, tenant_id, session_id, summary_json, generated_by, created_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(tenant_id, session_id) DO UPDATE SET summary_json = excluded.summary_json, generated_by = excluded.generated_by, created_at = excluded.created_at", (summary_id, tenant_id, session_id, json.dumps(summary, ensure_ascii=False), generated_by, summary["generated_at"]))
        conn.commit()
    return {"id": summary_id, "tenant_id": tenant_id, **summary}


def explain_command_risk(*, command_event_id: str, tenant_id: str) -> dict[str, Any]:
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT e.canonical_action, e.risk_level, e.risk_dimensions_json,
                   e.policy_decision, e.confirmation_required
            FROM pam_command_events e
            JOIN pam_sessions s ON s.id = e.session_id AND s.tenant_id = ?
            WHERE e.id = ?
            """,
            (tenant_id, command_event_id),
        ).fetchone()
    if not row:
        raise ValueError("command event not found")
    try:
        dimensions = json.loads(row[2] or "{}")
    except (TypeError, ValueError):
        dimensions = {}
    reasons = []
    if row[0] in {"CONFIG_CHANGE", "DESTRUCTIVE_CHANGE"}:
        reasons.append("command_changes_device_state")
    if str(dimensions.get("asset_criticality", "normal")).lower() in {"high", "critical"}:
        reasons.append("asset_criticality_increases_impact")
    if dimensions.get("context") not in {"approved", "change_window"} and row[0] == "CONFIG_CHANGE":
        reasons.append("outside_approved_change_context")
    return {"command_event_id": command_event_id, "tenant_id": tenant_id, "risk_level": row[1], "policy_decision": row[3], "confirmation_required": bool(row[4]), "reasons": reasons or ["read_only_or_unclassified_command"], "dimensions": dimensions, "generated_by": "deterministic_policy_explanation"}


def queue_external_event(*, tenant_id: str, session_id: str | None, event_type: str, destination_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    destination = str(destination_type or "").lower()
    if destination not in {"syslog", "cef", "json", "webhook", "kafka", "api"}:
        raise ValueError("unsupported external event destination")
    forbidden = {"raw_command", "raw_output", "command_raw", "output_raw", "password", "secret", "token", "private_key"}
    safe_payload = {str(key): value for key, value in payload.items() if str(key).lower() not in forbidden}
    event_id = f"ext_{uuid.uuid4().hex[:16]}"
    created_at = _now()
    with get_db_connection() as conn:
        conn.execute("INSERT INTO pam_external_events (id, tenant_id, session_id, event_type, destination_type, payload_json, state, created_at) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)", (event_id, tenant_id, session_id, re.sub(r"[^A-Za-z0-9_.:/-]", "_", str(event_type or "audit"))[:100], destination, json.dumps(safe_payload, ensure_ascii=False, default=str), created_at))
        conn.commit()
    return {"id": event_id, "tenant_id": tenant_id, "session_id": session_id, "destination_type": destination, "state": "queued", "metadata_keys": sorted(safe_payload), "created_at": created_at}
