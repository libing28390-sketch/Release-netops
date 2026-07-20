# Huawei/H3C platform-variant fixture batch

This batch adds three official-documentation fixtures. The fixture metadata records the vendor URL, platform, model family, and command. The NTC built-in directory remains read-only.

| Platform key | Official command | Custom template | Fixture |
| --- | --- | --- | --- |
| `huawei_vrp` (VRP5) | `display environment` | `huawei_vrp_display_environment.textfsm` | S5700 / VRP 5.130, V200R003 |
| `hp_comware` (Comware5) | `display fan verbose` | `hp_comware_display_fan_verbose.textfsm` | S12500 |
| `h3c_comware9` (Comware9) | `display link-aggregation verbose` | `h3c_comware9_display_link_aggregation_verbose.textfsm` | MSR5680-X3 / R9141P16 |

Official sources:

- Huawei VRP5 temperature example: <https://info.support.huawei.com/network/ptmngsys/Web/tsrev_s/en/content/s/21_edesk_Fan_Failure/edesk_Fan_Failure_edesk002.html>
- H3C Comware5 fan example: <https://www.h3c.com/en/Support/Resource_Center/HK/Switches/H3C_S12500/H3C_S12500_Series_Switches/Technical_Documents/Quick_Starts/FAQ/H3C_S12500_FAQ-R1825P01-6W100/201310/800507_294551_0.htm>
- H3C Comware9 link aggregation example: <https://www.h3c.com/en/d_202503/2372923_294551_0.htm>

The parser tests assert both template identity and parsed fields. Comware9 is kept as an explicit platform key and is not allowed to silently select the Comware7 or Cisco template family. Its live SSH driver maps to the existing H3C/HP Comware transport while preserving the parser/catalog platform key.

Focused verification:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_textfsm_official_huawei_h3c_platform_variants.py backend/tests/test_operational_data_catalog.py -q
```
