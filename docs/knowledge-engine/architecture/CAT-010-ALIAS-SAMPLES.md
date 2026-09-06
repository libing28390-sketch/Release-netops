# CAT-010 Alias Samples

CAT-010 validates the representative alias strings that operators and source documents are expected to use:

| Input | Kind | Expected result |
|---|---|---|
| `CE68` | prefix | Huawei CE6800 model candidates; clarify |
| `CE688` | prefix | CE6881/CE6885 candidates; clarify |
| `CE6885` | prefix | full SKU confirmation required |
| `CE6885-48YS8CQ` | exact | unique only after active review |
| `C9300` | prefix | Catalyst 9300 model candidates; clarify |
| `Catalyst93` | prefix | Catalyst 9300 model candidates; clarify |
| `C9300-48P` | exact | unique only after active review |

All rows target a concrete product model ID. Prefix rows intentionally collide and receive conflict fields; exact rows remain draft until CAT-011 review. No alias selects a platform, credential or network write command.

Final Conclusion: PASS
