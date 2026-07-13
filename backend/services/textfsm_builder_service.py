import re
import io
from typing import Dict, Any, List, Optional

SEPARATOR_RE = re.compile(r"^[\s\-=_+|]{5,}$")

HEADER_KEYWORDS = {
    "interface",
    "port",
    "device",
    "neighbor",
    "peer",
    "vlan",
    "address",
    "mac",
    "ip",
    "status",
    "protocol",
    "state",
    "hostname",
    "uptime",
}

def normalize_column_name(name: str) -> str:
    """
    Convert a CLI column heading into a valid TextFSM variable name.
    """
    name = name.strip()
    name = re.sub(r"[\s\-/]+", "_", name)
    name = re.sub(r"[^A-Za-z0-9_]", "", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_").upper()

    if not name:
        return "DATA"

    if name[0].isdigit():
        name = f"FIELD_{name}"

    return name

def make_unique_columns(raw_columns: List[str]) -> List[str]:
    """
    Add numeric suffixes when duplicate column names exist.
    """
    result: List[str] = []
    counter: dict[str, int] = {}

    for raw_column in raw_columns:
        base_name = normalize_column_name(raw_column)
        counter[base_name] = counter.get(base_name, 0) + 1

        if counter[base_name] == 1:
            result.append(base_name)
        else:
            result.append(f"{base_name}_{counter[base_name]}")

    return result

def is_separator_line(line: str) -> bool:
    return bool(SEPARATOR_RE.fullmatch(line.strip()))

def split_header(line: str) -> List[str]:
    """
    First try splitting columns using two or more spaces.

    For headers containing only single spaces, automatic splitting is
    inherently ambiguous, so the whole line is returned as one column.
    """
    columns = [
        item.strip()
        for item in re.split(r"\s{2,}", line.strip())
        if item.strip()
    ]

    return columns or [line.strip()]

def header_score(lines: List[str], index: int) -> int:
    """
    Give each line a score indicating how likely it is to be a table header.
    """
    line = lines[index]
    stripped = line.strip()
    lower_line = stripped.lower()

    score = 0

    if index + 1 < len(lines) and is_separator_line(lines[index + 1]):
        score += 10

    # Multiple columns separated by at least two spaces.
    split_columns = re.split(r"\s{2,}", stripped)
    if len(split_columns) >= 2:
        score += 3

    matched_keywords = {
        keyword
        for keyword in HEADER_KEYWORDS
        if re.search(rf"\b{re.escape(keyword)}\b", lower_line)
    }
    score += min(len(matched_keywords), 4)

    # Data lines containing typical values should be less likely to be headers.
    if re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", stripped):
        score -= 4

    if re.search(
        r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b",
        stripped,
        re.IGNORECASE,
    ):
        score -= 4

    if re.search(r"\b(?:up|down|enabled|disabled)\b", lower_line):
        score -= 1

    return score

def find_header_index(lines: List[str]) -> Optional[int]:
    """
    Find the most likely table header.
    """
    if not lines:
        return None

    scored_lines = [
        (header_score(lines, index), index)
        for index in range(len(lines))
        if not is_separator_line(lines[index])
    ]

    if not scored_lines:
        return None

    best_score, best_index = max(scored_lines, key=lambda item: item[0])

    # Avoid treating an arbitrary text line as a table header.
    if best_score < 3:
        return None

    return best_index

def infer_value_regex(column_name: str, is_last: bool = False) -> str:
    """
    Infer a basic regex from the column name.
    These are intentionally permissive. The generated template should still
    be reviewed when processing complex vendor outputs.
    """
    upper_name = column_name.upper()

    if "IP" in upper_name and "ADDRESS" in upper_name:
        # Supports IPv4 and a broad subset of IPv6 text.
        return r"(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9A-Fa-f:]+)"

    if "MAC" in upper_name:
        return (
            r"(?:"
            r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}|"
            r"[0-9A-Fa-f]{2}(?:-[0-9A-Fa-f]{2}){5}|"
            r"[0-9A-Fa-f]{4}(?:\.[0-9A-Fa-f]{4}){2}"
            r")"
        )

    if upper_name in {"VLAN", "VLAN_ID", "ID", "PRIORITY", "METRIC"}:
        return r"(\d+)"

    if any(
        keyword in upper_name
        for keyword in ("DESCRIPTION", "NAME", "REASON", "MESSAGE")
    ):
        return r"(.+?)"

    if is_last:
        # The final column can safely consume the rest of the line.
        return r"(.+?)"

    return r"(\S+)"

def regex_escape_header(header_line: str) -> str:
    """
    Convert a literal header line into a flexible TextFSM skip pattern.
    """
    tokens = re.split(r"\s+", header_line.strip())
    return r"\s+".join(re.escape(token) for token in tokens)

def auto_generate_template(sample_output: str) -> Dict[str, Any]:
    """
    Analyze a tabular CLI output, generate a TextFSM template skeleton,
    and self-validate it using TextFSM to report parsing stats.
    """
    lines = [
        line.rstrip()
        for line in sample_output.splitlines()
        if line.strip()
    ]

    warnings: List[str] = []

    if not lines:
        template = (
            "# Auto-generated TextFSM template\n"
            "Value DUMMY (.*)\n"
            "\n"
            "Start\n"
            "  ^${DUMMY}$$ -> Record\n"
        )
        return {
            "template": template,
            "header_line": None,
            "header_index": None,
            "columns": ["DUMMY"],
            "warnings": ["The sample output is empty."],
            "records": [],
            "candidate_rows": 0,
            "matched_rows": 0,
            "match_rate": 0.0
        }

    header_index = find_header_index(lines)

    if header_index is None:
        warnings.append(
            "No reliable table header was detected. "
            "A single DATA field was generated."
        )
        header_line = None
        columns = ["DATA"]
    else:
        header_line = lines[header_index]
        raw_columns = split_header(header_line)
        columns = make_unique_columns(raw_columns)

        if len(columns) == 1:
            warnings.append(
                "Only one column was detected. The CLI header may use "
                "single-space separators or may not be tabular."
            )

    template_lines = [
        "# Auto-generated TextFSM template skeleton",
        "# Review the generated regexes before production use.",
    ]

    for index, column in enumerate(columns):
        value_regex = infer_value_regex(
            column_name=column,
            is_last=index == len(columns) - 1,
        )
        template_lines.append(f"Value {column} {value_regex}")

    template_lines.extend(["", "Start"])

    if header_line:
        escaped_header = regex_escape_header(header_line)
        template_lines.append(f"  ^\\s*{escaped_header}\\s*$$")

    template_lines.append(r"  ^\s*[-=_+|][\s\-=_+|]*$$")

    if columns == ["DATA"]:
        template_lines.append(r"  ^\s*${DATA}\s*$$ -> Record")
    else:
        parse_parts = []
        for index, column in enumerate(columns):
            if index == 0:
                parse_parts.append(f"^\\s*${{{column}}}")
            else:
                parse_parts.append(f"\\s+${{{column}}}")

        parse_line = "".join(parse_parts) + r"\s*$$ -> Record"
        template_lines.append(f"  {parse_line}")

    template_lines.append("")
    template = "\n".join(template_lines)

    # 1. Parse using TextFSM to self-validate
    records = []
    matched_rows = 0
    match_rate = 0.0
    try:
        import textfsm
        template_stream = io.StringIO(template)
        parser = textfsm.TextFSM(template_stream)
        parsed_rows = parser.ParseText(sample_output)
        headers = parser.header
        records = [dict(zip(headers, row)) for row in parsed_rows]
        matched_rows = len(parsed_rows)
    except Exception as exc:
        warnings.append(f"Auto-validation parse error: {exc}")

    # 2. Count candidate rows
    candidate_lines = []
    if header_index is not None:
        for idx in range(header_index + 1, len(lines)):
            line = lines[idx]
            if is_separator_line(line) or not line.strip():
                continue
            line_str = line.strip()
            if (line_str.startswith('<') and line_str.endswith('>')) or line_str.endswith('#') or line_str.endswith('>'):
                continue
            candidate_lines.append(line)

    candidate_rows = len(candidate_lines)
    if candidate_rows > 0:
        match_rate = round(matched_rows / candidate_rows, 3)
    else:
        match_rate = 1.0 if matched_rows > 0 else 0.0

    return {
        "template": template,
        "header_line": header_line,
        "header_index": header_index,
        "columns": columns,
        "warnings": warnings,
        "records": records,
        "candidate_rows": candidate_rows,
        "matched_rows": matched_rows,
        "match_rate": match_rate,
    }
