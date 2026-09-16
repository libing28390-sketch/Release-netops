from __future__ import annotations

import re


INTERFACE_ALIASES = [
    # 100G vendor spellings.  H3C/Comware commonly reports ``HGE`` while
    # Huawei reports ``100GE`` and Cisco reports ``HundredGigE``/``Hu``.
    ("hundredgigabitethernet", "hu"),
    ("hundred-gigabitethernet", "hu"),
    ("hundredge", "hu"),
    ("100gigabitethernet", "hu"),
    ("100gige", "hu"),
    ("hundredgige", "hu"),
    ("100ge", "hu"),
    ("hge", "hu"),
    # 40G vendor spellings.  FGE/40GE/FortyGigE are the same physical
    # interface family and must compare equal during LLDP/LAG matching.
    ("fortygigabitethernet", "fo"),
    ("forty-gigabitethernet", "fo"),
    ("fortyge", "fo"),
    ("40gigabitethernet", "fo"),
    ("40gige", "fo"),
    ("fortygige", "fo"),
    ("40ge", "fo"),
    ("fge", "fo"),
    # 25G vendor spellings.
    ("twentyfivegigabitethernet", "tw"),
    ("twenty-five-gigabitethernet", "tw"),
    ("twentyfivegige", "tw"),
    ("25gigabitethernet", "tw"),
    ("25gige", "tw"),
    ("25ge", "tw"),
    # 10G vendor spellings.  H3C uses XGE, while LLDP and some command
    # outputs use Ten-GigabitEthernet or 10GE for the same port.
    ("tengigabitethernet", "te"),
    ("ten-gigabitethernet", "te"),
    ("tengige", "te"),
    ("tengigeethernet", "te"),
    ("10gigabitethernet", "te"),
    ("10gige", "te"),
    ("10ge", "te"),
    ("xgigabitethernet", "te"),
    ("xge", "te"),
    ("gigabitethernet", "gi"),
    ("gige", "gi"),
    ("fastethernet", "fa"),
    ("ethernet", "eth"),
    ("eth-trunk", "eth-trunk"),
    ("bridge-aggregation", "bagg"),
    ("route-aggregation", "ragg"),
    ("port-channel", "po"),
    ("portchannel", "po"),
    ("bundle-ether", "be"),
    ("loopback", "lo"),
    ("loop", "lo"),
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

    # SVI names are formatted differently by Cisco, Huawei and H3C. H3C may
    # report the same interface as ``Vlan8`` in the brief table and
    # ``Vlan-interface8`` in the IP inventory/configuration output.
    svi_match = re.fullmatch(r"vlan(?:if|[-_]?interface)?[-_ ]*(\d+)", raw, flags=re.IGNORECASE)
    if svi_match:
        return f"vlan{svi_match.group(1)}"

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


def interface_nominal_speed_mbps(value: str | None) -> int:
    """Return the nominal port capacity implied by a canonical interface name.

    This is only a fallback when a collector has not populated negotiated
    speed yet.  It covers the common vendor-neutral families used by LLDP and
    topology rendering; an empty result means the name is not sufficient to
    infer capacity.
    """
    normalized = normalize_interface_name(value)
    for prefix, speed_mbps in (
        ("hu", 100_000),
        ("fo", 40_000),
        ("tw", 25_000),
        ("te", 10_000),
        ("gi", 1_000),
        ("fa", 100),
    ):
        if normalized.startswith(prefix) and len(normalized) > len(prefix) and normalized[len(prefix)].isdigit():
            return speed_mbps
    return 0
