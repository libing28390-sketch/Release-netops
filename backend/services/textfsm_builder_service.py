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

_STANDARD_FIELDS_MAPPING = {
    'INTF': 'INTERFACE',
    'LOCAL_INTERFACE': 'INTERFACE',
    'IFNAME': 'INTERFACE',
    'IP': 'IP_ADDRESS',
    'IPADDR': 'IP_ADDRESS',
    'IP_ADDR': 'IP_ADDRESS',
    'ADDRESS': 'IP_ADDRESS',
    'MAC': 'MAC_ADDRESS',
    'MACADDR': 'MAC_ADDRESS',
    'HARDWARE_ADDRESS': 'MAC_ADDRESS',
    'STATE': 'STATUS',
    'LINK_STATUS': 'STATUS',
    'OPER_STATUS': 'STATUS',
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

    if name in _STANDARD_FIELDS_MAPPING:
        name = _STANDARD_FIELDS_MAPPING[name]

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

    # 尝试进行 Key-Value 格式检测
    kv_pairs = None
    if header_index is None:
        kv_pairs = []
        # 捕获组 (?P<sep>...) 用来精确还原分隔符
        kv_pattern = re.compile(
            r'^\s*(?P<key>[A-Za-z0-9_\-\.\s]+?)\s*(?P<sep>:|Is:|Is\s*:|=)\s*(?P<value>.+?)\s*$'
        )
        for line in lines:
            line_str = line.strip()
            if line_str.startswith('#') or line_str.startswith('---'):
                continue
            if re.match(r'^[\s\-=_+|]{5,}$', line_str):
                continue
            # 优先提取并标准化时间戳为 RECORD_TIME 列
            time_pat = re.compile(r'(\d{4}[-/]\d{2}[-/]\d{2}(?:\s+\d{2}:\d{2}:\d{2})?(?:\s*[+-]\d{2}:?\d{2})?)')
            time_match = time_pat.search(line_str)
            if time_match:
                extracted_time = time_match.group(1)
                idx = line_str.find(extracted_time)
                key = line_str[:idx].strip().strip(':').strip('=').strip()
                if not key:
                    key = "RECORD_TIME"
                else:
                    if any(keyword in key.lower() for keyword in ('time', 'statistics at', 'date', 'at')):
                        key = "RECORD_TIME"
                
                if not any(item[0] == key for item in kv_pairs):
                    kv_pairs.append((key, "", extracted_time, line_str))
                continue
            m = kv_pattern.match(line_str)
            if m:
                key = m.group('key').strip()
                sep = m.group('sep').strip()
                val = m.group('value').strip()
                # 键名必须包含字母，且词数合理（排除日志或长文本句）
                if re.search(r'[A-Za-z]', key) and len(key.split()) <= 6:
                    kv_pairs.append((key, sep, val, line_str))
                    
        if len(kv_pairs) < 2:
            kv_pairs = None

    def escape_textfsm_regex(text: str) -> str:
        escaped = re.sub(r'([.\^$*+?{}|()\[\]\\])', r'\\\1', text)
        escaped = re.sub(r'\s+', r'\\s+', escaped)
        return escaped

    if kv_pairs:
        # Key-Value 模板构建逻辑
        columns = []
        column_map = {}
        for key, sep, val, original_line in kv_pairs:
            col_name = normalize_column_name(key)
            for suffix in ('_IS', '_ARE', '_WAS', '_VALUE', '_RATE', '_PERCENT'):
                if col_name.endswith(suffix):
                    col_name = col_name[:-len(suffix)]
            if not col_name:
                col_name = "DATA"
                
            base_col = col_name
            idx = 1
            while col_name in column_map:
                idx += 1
                col_name = f"{base_col}_{idx}"
                
            if col_name == "RECORD_TIME":
                val_regex = r"(\d{4}[-/]\d{2}[-/]\d{2}(?:\s+\d{2}:\d{2}:\d{2})?(?:\s*[+-]\d{2}:?\d{2})?)"
                left_part = original_line.split(val)[0]
                val_match_str = escape_textfsm_regex(left_part) + val_regex
            else:
                val_clean = val.strip()
                num_match = re.search(r'(\d+(?:\.\d+)?)', val_clean)
                if num_match:
                    extracted_num = num_match.group(1)
                    left_part, right_part = val_clean.split(extracted_num, 1)
                    val_regex = r"(\d+(?:\.\d+)?)"
                    val_match_str = escape_textfsm_regex(left_part) + val_regex + escape_textfsm_regex(right_part)
                else:
                    val_regex = r"(.+?)"
                    val_match_str = val_regex
                
            columns.append(col_name)
            column_map[col_name] = {
                'key': key,
                'sep': sep,
                'val': val,
                'val_regex': val_regex,
                'val_match_str': val_match_str,
                'original_line': original_line
            }

        template_lines = [
            "# Auto-generated TextFSM template skeleton (Key-Value Format)",
            "# Review the generated regexes before production use.",
        ]
        for col in columns:
            template_lines.append(f"Value {col} {column_map[col]['val_regex']}")
            
        template_lines.extend(["", "Start"])
        
        for idx, col in enumerate(columns):
            info = column_map[col]
            if col == "RECORD_TIME":
                val_pattern = info['val_match_str'].replace(info['val_regex'], f"${{{col}}}")
                rule_line = f"  ^\\s*{val_pattern}\\s*$$"
            else:
                escaped_key = escape_textfsm_regex(info['key'])
                escaped_sep = escape_textfsm_regex(info['sep'])
                val_pattern = info['val_match_str'].replace(info['val_regex'], f"${{{col}}}")
                rule_line = f"  ^\\s*{escaped_key}\\s*{escaped_sep}\\s*{val_pattern}\\s*$$"
            
            if idx == len(columns) - 1:
                rule_line += " -> Record"
            template_lines.append(rule_line)
            
        template_lines.append("")
        template = "\n".join(template_lines)
        
        records = []
        matched_rows = 0
        match_rate = 0.0
        try:
            import textfsm
            import io
            fsm = textfsm.TextFSM(io.StringIO(template))
            records = fsm.ParseTextToDicts(sample_output)
            matched_rows = len(records)
            match_rate = 1.0 if matched_rows > 0 else 0.0
        except Exception as e:
            warnings.append(f"Self-validation failed: {e}")
            
        return {
            "template": template,
            "header_line": None,
            "header_index": None,
            "columns": columns,
            "warnings": warnings,
            "records": records,
            "candidate_rows": 1,
            "matched_rows": matched_rows,
            "match_rate": match_rate
        }

    # 兜底表格形式生成
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
