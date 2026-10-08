# Pinned LibreNMS hardware rule bundle

This directory holds the local LibreNMS rule snapshot used by Nexora's hardware discovery. Runtime collection reads these project files and does not fetch from GitHub.

- Repository: https://github.com/librenms/librenms
- Revision: `6c26b4fe4a40f7b392c19c36a44257212736e38c` (master, committed 2026-09-29T08:08:05+01:00)
- Network asset OS profiles: 136 across 25 asset vendors
- MIB source files: 217 curated files
- MIB data size: 33.1 MiB
- Exact file provenance and SHA-256: `source-manifest.json`

LibreNMS hardware rules are not all YAML. This bundle includes the upstream Comware OS implementation and sensor-discovery modules because LibreNMS defines Comware CPU, memory, temperature, and transceiver behavior in PHP. It also includes the pinned `Mempool`, `Number`, and common conversion helpers used by those rules. The Python collector is only the execution/metric-mapping layer for Nexora; the pinned upstream files are the rule source of truth. Comware wireless metrics without an upstream LibreNMS rule are not emitted by the LibreNMS hardware collection path.

Only LibreNMS MIB modules referenced by selected network OS identity and hardware definitions are included, plus the H3C Comware transceiver MIB. The bundle is not a full LibreNMS runtime or the complete MIB archive. DPtech has no matching LibreNMS OS profile in this upstream snapshot; its support remains limited to reviewed standard MIB coverage until LibreNMS publishes a profile.

Upstream file notices are retained. See `LICENSE.txt` and the copyright headers in individual source files.
