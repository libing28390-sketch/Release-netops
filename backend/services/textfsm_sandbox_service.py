"""Run TextFSM parsing outside the API process.

The worker intentionally accepts only template text and command output.  It
does not receive a path, command, import name, or network target from the
caller.  The parent process owns all size and timeout limits.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


class TextFSMSandboxError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _byte_length(value: str) -> int:
    return len(str(value or "").encode("utf-8", errors="ignore"))


def _worker() -> int:
    try:
        payload = json.load(sys.stdin)
        template = str(payload.get("template") or "")
        output = str(payload.get("output") or "")
        from core.textfsm import parse_with_template_content

        records = parse_with_template_content(template, output)
        if not isinstance(records, list):
            records = []
        print(json.dumps({"success": True, "records": records}, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), flush=True)
        return 1


def parse_template_in_sandbox(
    template_content: str,
    output: str,
    *,
    timeout_seconds: int = 30,
    max_template_bytes: int = 256_000,
    max_output_bytes: int = 2_000_000,
    max_records: int = 1_000,
    max_fields: int = 128,
) -> list[dict[str, Any]]:
    """Parse template content in a short-lived, bounded child process."""
    template_content = str(template_content or "")
    output = str(output or "")
    if _byte_length(template_content) > max_template_bytes:
        raise TextFSMSandboxError("TEMPLATE_LIMIT_EXCEEDED", "Parser template exceeds the size limit")
    if _byte_length(output) > max_output_bytes:
        raise TextFSMSandboxError("OUTPUT_LIMIT_EXCEEDED", "Command output exceeds the parser limit")

    backend_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(backend_root) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    command = [sys.executable, "-m", "services.textfsm_sandbox_service", "--worker"]
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(backend_root),
            env=env,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        stdout, _stderr = proc.communicate(
            input=json.dumps({"template": template_content, "output": output}, ensure_ascii=False),
            timeout=max(1, min(int(timeout_seconds or 30), 120)),
        )
    except subprocess.TimeoutExpired as exc:
        if os.name == "nt":
            # Popen.kill() only guarantees the worker process is terminated on
            # Windows. taskkill /T also removes any descendants it spawned.
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            proc.kill()
        proc.communicate()
        raise TextFSMSandboxError("TEMPLATE_TIMEOUT", "Parser sandbox timed out") from exc
    except OSError as exc:
        raise TextFSMSandboxError("TEMPLATE_SANDBOX_UNAVAILABLE", "Parser sandbox could not be started") from exc

    stdout = (stdout or "").strip()
    if _byte_length(stdout) > max_output_bytes:
        raise TextFSMSandboxError("TEMPLATE_LIMIT_EXCEEDED", "Parser sandbox response exceeds the size limit")
    try:
        response = json.loads(stdout or "{}")
    except json.JSONDecodeError as exc:
        raise TextFSMSandboxError("TEMPLATE_SANDBOX_FAILED", "Parser sandbox returned invalid data") from exc
    if proc.returncode != 0 or not response.get("success"):
        raise TextFSMSandboxError("TEMPLATE_NOT_MATCHED", "Parser template failed")

    records = response.get("records") or []
    if not isinstance(records, list) or len(records) > max_records:
        raise TextFSMSandboxError("RECORD_LIMIT_EXCEEDED", "Parser returned too many records")
    for record in records:
        if not isinstance(record, dict) or len(record) > max_fields:
            raise TextFSMSandboxError("FIELD_LIMIT_EXCEEDED", "Parser returned too many fields")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--worker", action="store_true")
    args, _ = parser.parse_known_args()
    return _worker() if args.worker else 2


if __name__ == "__main__":
    raise SystemExit(main())
