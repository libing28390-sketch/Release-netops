from __future__ import annotations


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
    raw = str(value).strip().lower().replace(" ", "").replace("\u200b", "")
    for source, target in INTERFACE_ALIASES:
        if raw.startswith(source):
            raw = raw.replace(source, target, 1)
            break
    if raw.startswith("ethernet"):
        raw = raw.replace("ethernet", "eth", 1)
    return raw
