import re
from typing import Dict, Any, List

def auto_generate_template(sample_output: str) -> str:
    """
    Analyzes a sample CLI output (typically tabular data) and automatically
    generates a standard TextFSM template skeleton.
    """
    lines = [ln.strip() for ln in sample_output.splitlines() if ln.strip()]
    if not lines:
        return "Value DUMMY (.*)\n\nStart\n  ^${DUMMY} -> Record\n"

    # Find the header line. Usually it contains columns, or is followed by a line of hyphens/dashes.
    header_idx = -1
    for i, line in enumerate(lines):
        # If the next line is all dashes/hyphens
        if i + 1 < len(lines) and re.match(r'^[-=\s]{5,}$', lines[i+1]):
            header_idx = i
            break
        # Or if it looks like a typical header (e.g. starts with "Interface", "Port", "Device", etc.)
        if any(kw in line.lower() for kw in ('interface', 'port', 'device', 'neighbor', 'peer', 'vlan', 'address', 'mac address', 'ip address', 'mac-address', 'ip-address')):
            header_idx = i
            break

    if header_idx == -1:
        # Fallback to the first line as header if it has multiple tokens
        if len(lines[0].split()) >= 2:
            header_idx = 0
        else:
            header_idx = -1

    if header_idx != -1:
        header_line = lines[header_idx]
        # Split tokens by 2 or more spaces to preserve multi-word headers
        raw_columns = re.split(r'\s{2,}', header_line)
        columns = []
        for c in raw_columns:
            cleaned = re.sub(r'[^a-zA-Z0-9_]', '', c.strip().replace(' ', '_').replace('-', '_')).upper()
            if cleaned and cleaned not in columns:
                columns.append(cleaned)
        if not columns:
            columns = ["DATA"]
    else:
        columns = ["DATA"]

    # Generate variables section
    template_lines = [
        "# Auto-generated TextFSM Template skeleton",
        "# Adjust value regex definitions as needed (e.g. change \\S+ to \\d+ or .*)"
    ]
    for col in columns:
        template_lines.append(f"Value {col} (\\S+)")
    
    template_lines.append("")
    template_lines.append("Start")
    
    # Generate parsing line
    parse_parts = []
    for i, col in enumerate(columns):
        if i == 0:
            parse_parts.append(f"^\\s*${{{col}}}")
        else:
            parse_parts.append(f"\\s+${{{col}}}")
    
    parse_line = "".join(parse_parts) + " -> Record"
    template_lines.append(f"  {parse_line}")
    template_lines.append("")
    
    return "\n".join(template_lines)
