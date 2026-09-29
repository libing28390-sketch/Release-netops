# Pinned LibreNMS hardware source bundle

This directory holds the local LibreNMS source snapshot used by Nexora's hardware and optical-sensor discovery. Runtime collection reads these project files and does not fetch from GitHub.

- Repository: https://github.com/librenms/librenms
- Revision: `6c26b4fe4a40f7b392c19c36a44257212736e38c` (master, committed 2026-09-29T08:08:05+01:00)
- Network asset OS profiles: 136 across 25 asset vendors
- MIB source files: 217 curated files
- MIB data size: 33.1 MiB
- Exact file provenance and SHA-256: `source-manifest.json`

Only LibreNMS MIB modules referenced by the selected network OS identity and hardware sensor definitions are included, plus the H3C Comware transceiver MIB used by the Comware rule adapter in the shared hardware probe. The bundle is not the full LibreNMS MIB archive. DPtech has no matching LibreNMS OS profile in this upstream snapshot; its support must remain limited to reviewed standard MIB coverage until LibreNMS publishes a profile.

Upstream file notices are retained. See `UPSTREAM_LICENSE.txt` and any notices contained in individual source files.
