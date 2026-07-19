from __future__ import annotations

import re


INTERFACE_ALIASES = [
    ("tengigabitethernet", "te"),
    ("tengigeethernet", "te"),
    ("twentyfivegige", "tw"),
    ("twentyfivegigabitethernet", "tw"),
    ("fortygigabitethernet", "fo"),
    ("fortyge", "fo"),
    ("hundredgigabitethernet", "hu"),
    ("hundredge", "hu"),
    ("gigabitethernet", "gi"),
    ("gige", "gi"),
    ("fastethernet", "fa"),
    ("xgigabitethernet", "xge"),
    ("25gige", "tw"),
    ("40gige", "fo"),
    ("100gige", "hu"),
    ("ethernet", "eth"),
    ("eth-trunk", "eth-trunk"),
    ("bridge-aggregation", "bagg"),
    ("port-channel", "po"),
    ("portchannel", "po"),
    ("bundle-ether", "be"),
    ("loopback", "lo"),
    ("management", "mgmt"),
    ("mgmteth", "mgmt"),
    ("meth", "mgmt"),
    ("vlanif", "vlanif"),
    ("vlan", "vl"),
]


def normalize_interface_name(value: str | None) -> str:
    """Return a stable, vendor-neutral interface key used for matching."""
    if not value:
        return ""
    # Some LLDP/TextFSM records append a presentation suffix (for example
    # ``GigabitEthernet3/0 Interface``).  It is not part of the interface
    # identity and must be removed before whitespace is compacted; otherwise
    # the stale suffix becomes part of the normalized key and creates a
    # duplicate topology edge.
    raw = str(value).strip().replace("\u200b", "")
    raw = re.sub(r"\s+interface\s*$", "", raw, flags=re.IGNORECASE)
    raw = raw.lower().replace(" ", "")
    for source, target in INTERFACE_ALIASES:
        if raw.startswith(source):
            raw = raw.replace(source, target, 1)
            break

    # Cisco IOS and Comware/Huawei frequently mix long names with short
    # aliases in opposite directions of the same LLDP adjacency.  Keep one
    # canonical key so Et0/1 == Ethernet0/1 and GE2/0 ==
    # GigabitEthernet2/0.  These checks are intentionally digit-gated so an
    # already canonical `eth...`/`gi...` value is not rewritten again.
    if raw.startswith("et") and len(raw) > 2 and raw[2].isdigit():
        raw = "eth" + raw[2:]
    elif raw.startswith("e") and len(raw) > 1 and raw[1].isdigit():
        raw = "eth" + raw[1:]
    elif raw.startswith("ge") and len(raw) > 2 and raw[2].isdigit():
        raw = "gi" + raw[2:]

    if raw.startswith("ethernet"):
        raw = raw.replace("ethernet", "eth", 1)
    return raw
