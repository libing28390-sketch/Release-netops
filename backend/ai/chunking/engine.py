"""Deterministic, structure-aware chunking for network operations knowledge.

The first version of the knowledge base split text by character count.  This
module deliberately keeps parsing and chunking independent from the database
and the embedding provider so that the behaviour can be tested with fixtures.
It is conservative: headings provide context, code/table blocks are preserved,
and Parent/Child is only introduced where a semantic section is large enough
to benefit from it.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+(?:[-./][A-Za-z0-9_]+)*")
_SENTENCE_RE = re.compile(r"(?<=[。！？!?；;.!?])\s+|\n{2,}")

_CLI_LANGUAGES = {
    "bash",
    "cisco",
    "cli",
    "cmd",
    "command",
    "h3c",
    "huawei",
    "junos",
    "network",
    "shell",
    "textfsm",
}
_OUTPUT_LANGUAGES = {"output", "console", "terminal", "textfsm-output"}
_WARNING_MARKERS = ("warning", "caution", "注意", "警告", "风险")
_NOTE_MARKERS = ("note", "tip", "说明", "提示")
_TROUBLESHOOTING_MARKERS = (
    "troubleshoot",
    "故障",
    "排障",
    "排查",
    "现象",
    "原因",
    "解决方案",
    "symptom",
    "cause",
    "solution",
    "symptoms",
    "causes",
    "resolution",
    "症状",
    "处理",
)
_CONFIG_MARKERS = (
    "配置",
    "configuration",
    "configure",
    "部署",
    "开通",
    "启用",
    "setup",
)
_VERIFICATION_MARKERS = (
    "验证",
    "检查",
    "查看",
    "verify",
    "verification",
    "check",
    "show",
    "display",
)
_COMMAND_MARKERS = (
    "命令",
    "command",
    "参数",
    "syntax",
    "语法",
    "视图",
    "view",
)


def _clean_text(value: str) -> str:
    value = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in value.split("\n")]
    return "\n".join(lines).strip()


def _normalised_hash(value: str) -> str:
    normalized = "\n".join(line.strip() for line in _clean_text(value).splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def estimate_token_count(text: str) -> int:
    """Estimate tokens without adding a model-specific dependency.

    The estimate is intentionally conservative for Chinese and CLI content:
    CJK characters count approximately one token, Latin/number runs count in
    four-character pieces, and punctuation is counted in small groups.  The
    engine accepts an injected tokenizer, so this function can be replaced by
    the production embedding model's tokenizer later without changing the
    chunking contract.
    """

    value = _clean_text(text)
    if not value:
        return 0
    cjk = len(_CJK_RE.findall(value))
    latin = sum(max(1, math.ceil(len(match.group(0)) / 4)) for match in _LATIN_TOKEN_RE.finditer(value))
    punctuation = sum(1 for char in value if not char.isspace() and not _CJK_RE.match(char) and not char.isalnum() and char != "_")
    return max(1, cjk + latin + math.ceil(punctuation / 4))


@dataclass(frozen=True)
class ChunkingConfig:
    """Initial V2 budgets; values are token counts, not character counts."""

    target_tokens: Mapping[str, int] = field(
        default_factory=lambda: {
            "command": 220,
            "command_reference": 300,
            "concept": 600,
            "configuration": 360,
            "procedure": 360,
            "verification": 240,
            "troubleshooting": 450,
            "command_output": 450,
            "table": 450,
            "warning": 180,
            "faq": 300,
            "code": 350,
        }
    )
    max_tokens: Mapping[str, int] = field(
        default_factory=lambda: {
            "command": 500,
            "command_reference": 500,
            "concept": 1000,
            "configuration": 1800,
            "procedure": 1500,
            "verification": 600,
            "troubleshooting": 1800,
            "command_output": 900,
            "table": 1000,
            "warning": 400,
            "faq": 800,
            "code": 900,
        }
    )
    min_tokens: int = 100
    overlap_ratio: float = 0.10
    parent_min_blocks: int = 2

    def target(self, chunk_type: str) -> int:
        return int(self.target_tokens.get(chunk_type, self.target_tokens.get("concept", 600)))

    def maximum(self, chunk_type: str) -> int:
        return int(self.max_tokens.get(chunk_type, self.max_tokens.get("concept", 1000)))


@dataclass
class _Block:
    block_type: str
    text: str
    heading_path: tuple[str, ...]
    start_line: int
    end_line: int
    language: str = ""
    atomic: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def tokens(self) -> int:
        return estimate_token_count(self.text)


@dataclass
class Chunk:
    """A database-independent chunk representation."""

    chunk_id: str
    chunk_role: str
    chunk_type: str
    raw_content: str
    embedding_content: str
    heading_path: tuple[str, ...]
    token_count: int
    content_hash: str
    ordinal: int
    parent_chunk_id: str | None = None
    source_locator: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    is_retrieval_candidate: bool = True
    oversize_reason: str | None = None

    @property
    def content(self) -> str:
        """Compatibility alias used by the existing API/UI."""

        return self.raw_content

    def to_dict(self) -> dict[str, Any]:
        result = {
            "id": self.chunk_id,
            "chunk_id": self.chunk_id,
            "chunk_role": self.chunk_role,
            "chunk_type": self.chunk_type,
            "content": self.raw_content,
            "raw_content": self.raw_content,
            "embedding_content": self.embedding_content,
            "heading_path": list(self.heading_path),
            "token_count": self.token_count,
            "content_hash": self.content_hash,
            "ordinal": self.ordinal,
            "parent_chunk_id": self.parent_chunk_id,
            "source_locator": dict(self.source_locator),
            "metadata": dict(self.metadata),
            "is_retrieval_candidate": self.is_retrieval_candidate,
            "oversize_reason": self.oversize_reason,
            "section": " > ".join(self.heading_path) if self.heading_path else "General Overview",
        }
        return result


class ChunkingValidationError(ValueError):
    """Raised when a generated chunk set violates V2 invariants."""


class ChunkingEngine:
    """Build deterministic chunks from normalized Markdown or plain text."""

    def __init__(
        self,
        config: ChunkingConfig | None = None,
        token_counter: Callable[[str], int] | None = None,
    ) -> None:
        self.config = config or ChunkingConfig()
        self._token_counter = token_counter or estimate_token_count

    def chunk(
        self,
        markdown_text: str,
        *,
        document_identity: str = "document",
        document_metadata: Mapping[str, Any] | None = None,
        target_tokens_override: int | None = None,
    ) -> list[Chunk]:
        blocks = self._parse_blocks(markdown_text)
        if not blocks:
            return []

        groups: list[list[_Block]] = []
        current_key: tuple[str, ...] | None = None
        current: list[_Block] = []
        for block in blocks:
            key = self._parent_path(block.heading_path)
            if current and key != current_key:
                groups.append(current)
                current = []
            current_key = key
            current.append(block)
        if current:
            groups.append(current)

        result: list[Chunk] = []
        ordinal = 0
        for group in groups:
            chunk_type = self._infer_chunk_type(group)
            parent_path = self._parent_path(group[0].heading_path)
            parent_text = self._render_blocks(group, parent_path)
            group_tokens = self._token_counter(parent_text)
            maximum = self.config.maximum(chunk_type)
            should_split = self._needs_parent_child(group, chunk_type, group_tokens, maximum)

            if not should_split:
                chunk = self._make_chunk(
                    role="standalone",
                    chunk_type=chunk_type,
                    blocks=group,
                    parent_chunk_id=None,
                    ordinal=ordinal,
                    document_identity=document_identity,
                    document_metadata=document_metadata,
                    target_tokens_override=target_tokens_override,
                )
                result.append(chunk)
                ordinal += 1
                continue

            parent = self._make_chunk(
                role="parent",
                chunk_type=chunk_type,
                blocks=group,
                parent_chunk_id=None,
                ordinal=ordinal,
                document_identity=document_identity,
                document_metadata=document_metadata,
                target_tokens_override=target_tokens_override,
                force_retrieval_candidate=False,
                oversize_reason="parent_context" if group_tokens > maximum else None,
            )
            result.append(parent)
            ordinal += 1

            child_blocks = self._split_oversized_blocks(group, chunk_type)
            packs = self._pack_blocks(child_blocks, chunk_type, target_tokens_override)
            for pack in packs:
                child = self._make_chunk(
                    role="child",
                    chunk_type=chunk_type,
                    blocks=pack,
                    parent_chunk_id=parent.chunk_id,
                    ordinal=ordinal,
                    document_identity=document_identity,
                    document_metadata=document_metadata,
                    target_tokens_override=target_tokens_override,
                )
                result.append(child)
                ordinal += 1

        self.validate(result)
        return result

    def validate(self, chunks: Sequence[Chunk]) -> None:
        ids = {chunk.chunk_id for chunk in chunks}
        if len(ids) != len(chunks):
            raise ChunkingValidationError("chunk ids must be unique")
        for chunk in chunks:
            if not chunk.raw_content.strip():
                raise ChunkingValidationError("empty chunk content")
            if _HEADING_RE.fullmatch(chunk.raw_content.strip()):
                raise ChunkingValidationError("heading-only chunk is not allowed")
            if chunk.token_count <= 0:
                raise ChunkingValidationError("chunk token_count must be positive")
            if chunk.chunk_role == "child" and chunk.parent_chunk_id not in ids:
                raise ChunkingValidationError("child chunk has no parent")
            if chunk.raw_content.count("```") % 2 != 0 or chunk.raw_content.count("~~~") % 2 != 0:
                raise ChunkingValidationError("unclosed code fence")

    def _parse_blocks(self, markdown_text: str) -> list[_Block]:
        lines = _clean_text(markdown_text).splitlines()
        blocks: list[_Block] = []
        heading_stack: list[tuple[int, str]] = []
        buffer: list[str] = []
        buffer_start = 1
        in_fence = False
        fence_char = ""
        fence_length = 0
        fence_language = ""
        fence_start = 0

        def current_path() -> tuple[str, ...]:
            return tuple(item[1] for item in heading_stack)

        def flush_buffer(end_line: int) -> None:
            nonlocal buffer, buffer_start
            text = _clean_text("\n".join(buffer))
            if text:
                blocks.append(self._classify_text_block(text, current_path(), buffer_start, end_line))
            buffer = []

        index = 0
        while index < len(lines):
            line = lines[index]
            line_number = index + 1
            fence_match = _FENCE_RE.match(line)
            if in_fence:
                buffer.append(line)
                if fence_match and fence_match.group(1)[0] == fence_char and len(fence_match.group(1)) >= fence_length:
                    in_fence = False
                    code_text = _clean_text("\n".join(buffer))
                    blocks.append(
                        self._classify_code_block(
                            code_text,
                            current_path(),
                            fence_start,
                            line_number,
                            fence_language,
                        )
                    )
                    buffer = []
                index += 1
                continue

            if fence_match:
                flush_buffer(line_number - 1)
                in_fence = True
                fence_char = fence_match.group(1)[0]
                fence_length = len(fence_match.group(1))
                fence_language = fence_match.group(2).strip().split()[0].lower() if fence_match.group(2).strip() else ""
                fence_start = line_number
                buffer = [line]
                index += 1
                continue

            heading_match = _HEADING_RE.match(line)
            if heading_match:
                flush_buffer(line_number - 1)
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip().strip("#").strip()
                heading_stack = [item for item in heading_stack if item[0] < level]
                heading_stack.append((level, title))
                index += 1
                continue

            if self._is_table_start(lines, index):
                flush_buffer(line_number - 1)
                table_start = line_number
                table_lines = [line]
                index += 1
                while index < len(lines) and "|" in lines[index] and lines[index].strip():
                    table_lines.append(lines[index])
                    index += 1
                blocks.append(
                    _Block(
                        block_type="table",
                        text=_clean_text("\n".join(table_lines)),
                        heading_path=current_path(),
                        start_line=table_start,
                        end_line=index,
                        atomic=True,
                    )
                )
                continue

            if not line.strip():
                flush_buffer(line_number - 1)
            else:
                if not buffer:
                    buffer_start = line_number
                buffer.append(line)
            index += 1

        if in_fence:
            # Keep malformed input visible for the validator rather than
            # silently dropping the code block.
            code_text = _clean_text("\n".join(buffer))
            blocks.append(self._classify_code_block(code_text, current_path(), fence_start, len(lines), fence_language))
        else:
            flush_buffer(len(lines))
        return blocks

    @staticmethod
    def _is_table_start(lines: Sequence[str], index: int) -> bool:
        if index + 1 >= len(lines):
            return False
        first = lines[index].strip()
        second = lines[index + 1].strip()
        return "|" in first and bool(_TABLE_SEPARATOR_RE.match(second))

    def _classify_text_block(self, text: str, path: tuple[str, ...], start: int, end: int) -> _Block:
        lowered = f"{' '.join(path)} {text}".lower()
        first = text.splitlines()[0].strip().lower() if text.splitlines() else ""
        path_title = path[-1].lower() if path else ""
        if first.startswith(">") and any(marker in f"{path_title} {first}" for marker in _WARNING_MARKERS):
            return _Block("warning", text, path, start, end, atomic=True)
        if any(marker in f"{path_title} {first}" for marker in _WARNING_MARKERS) and len(text) <= 1200:
            return _Block("warning", text, path, start, end, atomic=True)
        if any(marker in f"{path_title} {first}" for marker in _NOTE_MARKERS) and len(text) <= 1200:
            return _Block("note", text, path, start, end, atomic=True)
        if re.match(r"^(?:\d+[.)]|[-*])\s+", text) and any(marker in lowered for marker in _CONFIG_MARKERS + ("步骤", "step", "procedure")):
            return _Block("procedure_step", text, path, start, end, atomic=True)
        return _Block("paragraph", text, path, start, end)

    def _classify_code_block(
        self,
        text: str,
        path: tuple[str, ...],
        start: int,
        end: int,
        language: str,
    ) -> _Block:
        lowered = f"{' '.join(path)} {text}".lower()
        lines = [line.strip() for line in text.splitlines() if line.strip() and not _FENCE_RE.match(line)]
        if language in _OUTPUT_LANGUAGES or any(line.startswith(("<", "[", "Neighbor", "State:", "OSPF Process")) for line in lines):
            kind = "command_output"
        elif language in _CLI_LANGUAGES or self._looks_like_cli(lines, lowered):
            kind = "cli_configuration" if len(lines) > 1 else "cli_command"
        else:
            kind = "code"
        return _Block(kind, text, path, start, end, language=language, atomic=True)

    @staticmethod
    def _looks_like_cli(lines: Sequence[str], lowered: str) -> bool:
        if not lines:
            return False
        cli_prefixes = (
            "display ",
            "show ",
            "system-view",
            "configure terminal",
            "interface ",
            "router ",
            "ospf ",
            "bgp ",
            "vlan ",
            "undo ",
            "no ",
        )
        return any(line.lower().startswith(cli_prefixes) for line in lines) or "命令" in lowered

    @staticmethod
    def _parent_path(path: tuple[str, ...]) -> tuple[str, ...]:
        if not path:
            return ("General Overview",)
        return path[:2] if len(path) >= 2 else path[:1]

    def _infer_chunk_type(self, blocks: Sequence[_Block]) -> str:
        path_text = " ".join(" ".join(block.heading_path) for block in blocks).lower()
        content = "\n".join(block.text for block in blocks)
        lowered = f"{path_text} {content}".lower()
        kinds = {block.block_type for block in blocks}
        if "table" in kinds:
            return "table"
        if "command_output" in kinds:
            return "command_output"
        if "warning" in kinds or "note" in kinds:
            return "warning"
        if "cli_command" in kinds and len(blocks) == 1:
            return "command"
        if any(marker in lowered for marker in _TROUBLESHOOTING_MARKERS):
            return "troubleshooting"
        if "cli_configuration" in kinds:
            return "configuration"
        if any(marker in lowered for marker in _VERIFICATION_MARKERS) and not any(marker in lowered for marker in _CONFIG_MARKERS):
            return "verification"
        if any(marker in lowered for marker in _COMMAND_MARKERS):
            return "command_reference"
        if any(marker in lowered for marker in _CONFIG_MARKERS):
            return "configuration"
        return "concept"

    def _needs_parent_child(self, blocks: Sequence[_Block], chunk_type: str, tokens: int, maximum: int) -> bool:
        parent_types = {"command_reference", "configuration", "procedure", "troubleshooting", "table"}
        return tokens > maximum or (chunk_type in parent_types and len(blocks) >= self.config.parent_min_blocks)

    def _split_oversized_blocks(self, blocks: Sequence[_Block], chunk_type: str) -> list[_Block]:
        result: list[_Block] = []
        for block in blocks:
            maximum = self.config.maximum(chunk_type)
            if block.tokens <= maximum:
                result.append(block)
                continue
            if block.block_type == "table":
                result.extend(self._split_table_block(block, maximum))
            elif block.block_type in {"cli_configuration", "command_output", "code"}:
                result.extend(self._split_line_block(block, maximum))
            else:
                result.extend(self._split_sentence_block(block, maximum))
        return result

    def _split_table_block(self, block: _Block, maximum: int) -> list[_Block]:
        lines = block.text.splitlines()
        if len(lines) <= 2:
            return self._split_line_block(block, maximum)
        header = lines[:2]
        result: list[_Block] = []
        current = list(header)
        start = block.start_line
        for line in lines[2:]:
            candidate = "\n".join(current + [line])
            if len(current) > 2 and self._token_counter(candidate) > maximum:
                result.append(_Block("table", _clean_text("\n".join(current)), block.heading_path, start, start + len(current) - 1, atomic=True))
                start += len(current) - 2
                current = list(header)
            current.append(line)
        if len(current) > 2:
            result.append(_Block("table", _clean_text("\n".join(current)), block.heading_path, start, block.end_line, atomic=True))
        return result or [block]

    def _split_line_block(self, block: _Block, maximum: int) -> list[_Block]:
        lines = block.text.splitlines()
        opening = lines[0] if lines and _FENCE_RE.match(lines[0]) else ""
        closing = lines[-1] if len(lines) > 1 and _FENCE_RE.match(lines[-1]) else ""
        body_lines = lines[1:-1] if opening and closing else lines
        result: list[_Block] = []
        current: list[str] = []
        start = block.start_line
        for line in body_lines:
            candidate_lines = ([opening] if opening else []) + current + [line] + ([closing] if closing else [])
            candidate = "\n".join(candidate_lines)
            if current and self._token_counter(candidate) > maximum:
                packed = ([opening] if opening else []) + current + ([closing] if closing else [])
                result.append(_Block(block.block_type, _clean_text("\n".join(packed)), block.heading_path, start, start + len(current) - 1, language=block.language, atomic=False, metadata={"oversize_reason": "line_boundary"}))
                start += len(current)
                current = []
            current.append(line)
        if current:
            packed = ([opening] if opening else []) + current + ([closing] if closing else [])
            result.append(_Block(block.block_type, _clean_text("\n".join(packed)), block.heading_path, start, block.end_line, language=block.language, atomic=False, metadata={"oversize_reason": "line_boundary"}))
        return result

    def _split_sentence_block(self, block: _Block, maximum: int) -> list[_Block]:
        sentences = [part.strip() for part in _SENTENCE_RE.split(block.text) if part.strip()]
        if len(sentences) <= 1:
            return self._split_line_block(block, maximum)
        result: list[_Block] = []
        current: list[str] = []
        start = block.start_line
        for sentence in sentences:
            candidate = " ".join(current + [sentence])
            if current and self._token_counter(candidate) > maximum:
                result.append(_Block("paragraph", " ".join(current), block.heading_path, start, block.end_line, atomic=False, metadata={"oversize_reason": "sentence_boundary"}))
                overlap = current[-1] if self.config.overlap_ratio > 0 and len(current) > 1 else ""
                current = [overlap] if overlap else []
                start = block.start_line
            current.append(sentence)
        if current:
            result.append(_Block("paragraph", " ".join(current), block.heading_path, start, block.end_line, atomic=False, metadata={"oversize_reason": "sentence_boundary"}))
        return result

    def _pack_blocks(self, blocks: Sequence[_Block], chunk_type: str, target_override: int | None) -> list[list[_Block]]:
        target = int(target_override or self.config.target(chunk_type))
        maximum = self.config.maximum(chunk_type)
        packs: list[list[_Block]] = []
        current: list[_Block] = []
        for block in blocks:
            candidate_tokens = self._token_counter(self._render_blocks([*current, block], block.heading_path))
            limit = maximum if not current else max(target, maximum)
            path_changed = bool(current and block.heading_path != current[-1].heading_path)
            parent_semantic = chunk_type in {"command_reference", "configuration", "procedure", "troubleshooting", "table"}
            if current and (candidate_tokens > limit or (parent_semantic and path_changed)):
                packs.append(current)
                current = []
            current.append(block)
        if current:
            packs.append(current)
        return packs

    def _render_blocks(self, blocks: Sequence[_Block], heading_path: Sequence[str]) -> str:
        prefix = " > ".join(item for item in heading_path if item)
        parts: list[str] = []
        if prefix:
            parts.append(prefix)
        for block in blocks:
            local_path = tuple(block.heading_path[len(heading_path):]) if len(block.heading_path) > len(heading_path) else ()
            if local_path:
                parts.append(" > ".join(local_path))
            parts.append(block.text)
        return _clean_text("\n\n".join(parts))

    def _make_chunk(
        self,
        *,
        role: str,
        chunk_type: str,
        blocks: Sequence[_Block],
        parent_chunk_id: str | None,
        ordinal: int,
        document_identity: str,
        document_metadata: Mapping[str, Any] | None,
        target_tokens_override: int | None,
        force_retrieval_candidate: bool | None = None,
        oversize_reason: str | None = None,
    ) -> Chunk:
        heading_path = self._parent_path(blocks[0].heading_path)
        raw_content = self._render_blocks(blocks, heading_path)
        token_count = self._token_counter(raw_content)
        content_hash = _normalised_hash(raw_content)
        identity = "|".join(
            [
                str(document_identity),
                role,
                chunk_type,
                parent_chunk_id or "",
                ",".join(heading_path),
                str(blocks[0].start_line),
                str(blocks[-1].end_line),
                content_hash,
            ]
        )
        chunk_id = f"chk_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"
        metadata = dict(document_metadata or {})
        metadata.update(
            {
                "chunk_role": role,
                "chunk_type": chunk_type,
                "heading_path": list(heading_path),
                "language": blocks[0].language if blocks[0].language else metadata.get("language", "zh-CN"),
                "commands": self._extract_commands(blocks),
            }
        )
        embedding_content = self._build_embedding_content(raw_content, heading_path, chunk_type, metadata)
        source_locator = {
            "line_start": min(block.start_line for block in blocks),
            "line_end": max(block.end_line for block in blocks),
        }
        retrieval_candidate = force_retrieval_candidate if force_retrieval_candidate is not None else True
        if role == "parent":
            retrieval_candidate = False
        return Chunk(
            chunk_id=chunk_id,
            chunk_role=role,
            chunk_type=chunk_type,
            raw_content=raw_content,
            embedding_content=embedding_content,
            heading_path=heading_path,
            token_count=token_count,
            content_hash=content_hash,
            ordinal=ordinal,
            parent_chunk_id=parent_chunk_id,
            source_locator=source_locator,
            metadata=metadata,
            is_retrieval_candidate=retrieval_candidate,
            oversize_reason=oversize_reason or next((block.metadata.get("oversize_reason") for block in blocks if block.metadata.get("oversize_reason")), None),
        )

    @staticmethod
    def _extract_commands(blocks: Sequence[_Block]) -> list[str]:
        commands: list[str] = []
        for block in blocks:
            if block.block_type not in {"cli_command", "cli_configuration", "command_output"}:
                continue
            for line in block.text.splitlines():
                stripped = line.strip().strip("`")
                if not stripped or stripped.startswith(("<", "#", "```")):
                    continue
                if re.match(r"^(?:display|show|system-view|interface|router|ospf|bgp|vlan|undo|no|ip|ipv6)\b", stripped, re.I):
                    if stripped not in commands:
                        commands.append(stripped)
        return commands[:20]

    @staticmethod
    def _build_embedding_content(raw_content: str, heading_path: Sequence[str], chunk_type: str, metadata: Mapping[str, Any]) -> str:
        lines = [
            f"vendor: {metadata.get('vendor', 'all')}",
            f"platform: {metadata.get('platform') or 'platform-neutral'}",
            f"version: {metadata.get('verified_version') or metadata.get('version') or 'unspecified'}",
            f"type: {chunk_type}",
            f"path: {' > '.join(heading_path) if heading_path else 'General Overview'}",
        ]
        for field in (
            "document_category", "product_family", "product_series", "product_model",
            "os_family", "os_generation", "software_train", "software_release",
            "cli_platform", "feature_domain", "feature", "subfeature",
            "risk_level", "verification_level", "rag_priority",
        ):
            value = metadata.get(field)
            if value not in (None, "", [], {}):
                lines.append(f"{field}: {value}")
        commands = metadata.get("commands") or []
        if commands:
            lines.append(f"commands: {'; '.join(commands)}")
        lines.append(raw_content)
        return "\n".join(lines)
