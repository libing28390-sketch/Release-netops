# Pinned LibreNMS hardware rule bundle

This directory holds the local LibreNMS rule snapshot used by Nexora's hardware discovery. Runtime collection reads these project files and does not fetch from GitHub.

- Repository: https://github.com/librenms/librenms
- Revision: `6c26b4fe4a40f7b392c19c36a44257212736e38c` (master, committed 2026-09-29T08:08:05+01:00)
- Network asset OS profiles: 136 across 25 asset vendors
- OS detection YAML files: 136/136 profiles
- OS hardware discovery YAML files: 122/136 profiles; 14 upstream profiles have no discovery YAML in this pinned snapshot
- Discovery YAML files with no CPU, memory-pool, or sensor definitions recognized by Nexora's current parser: 31/122; the other 91 have at least one parsed hardware definition
- MIB manifest records: 2,357 bundle mappings
- Unique pinned MIB files: 2,356 (2,340 vendor-subtree files plus 16 upstream root dependencies)
- MIB data size: 164,073,012 bytes (156.5 MiB; sum of manifest `size_bytes`, including shared-scope copies)
- File provenance, bundle paths, upstream paths, and SHA-256: `source-manifest.json`

The hardware collection runtime reads the pinned upstream YAML files under `resources/definitions/os_detection/` and `resources/definitions/os_discovery/`. Nexora's Python parser evaluates those definitions and performs the SNMP requests; it does not execute LibreNMS PHP modules. PHP adapters and Laravel helpers are not bundled because they are not runtime dependencies. This YAML-backed path is not the full LibreNMS runtime, and the presence of an OS profile does not prove parity with LibreNMS PHP behavior or complete hardware coverage. Fourteen profiles have no upstream discovery YAML; a further 31 discovery YAML files currently yield no CPU, memory-pool, or sensor definitions in Nexora's parser. Neither case falls back to Nexora vendor-specific OIDs.

The bundle contains MIB files from 35 distinct upstream `mibs/` vendor directories, grouped into 23 Nexora vendor-scope directories, plus the `standard` directory. The 35 upstream directory names are source paths, not 35 Nexora-supported vendors: several upstream trees are shared or mapped to an existing platform vendor (for example, HP ProCurve to Aruba and Fiberstore to Ruijie). The manifest separately lists 26 Nexora asset-vendor names and the 25 vendors with upstream OS profiles. Arista and Edgecore have OS profiles but no vendor-specific MIB directory in this bundle; DPtech is in the asset-vendor list but has neither an upstream OS profile nor a vendor-specific MIB directory. The bundle also includes 16 MIB dependencies stored at the upstream `mibs/` root. This is not the full LibreNMS runtime or repository, and this bundle makes no claim of LibreNMS hardware-rule coverage for DPtech.

Shared directory mappings follow the existing profiles: Nokia `aos6`, `aos7`, and `stellar` files are grouped under Alcatel-Lucent Enterprise while the remaining Nokia tree stays under Nokia; `NORTEL-OPTICAL-*` files are grouped under Ciena while other Nortel files use Extreme Networks; the Radlan tree uses Alcatel-Lucent Enterprise, with `RADLAN-rndMng` also mapped to Allied Telesis. Root `UPS-MIB` retains its Huawei scope.

Each MIB record in `source-manifest.json` separates the exact upstream `upstream_path` from its local `bundle_path`. `platform_vendor_scope` is Nexora's offline-index grouping; it does not identify the upstream MIB owner or determine which hardware rules run. The structured `mib_scope_mappings` records the HP ProCurve tree (`mibs/hp` / `procurve`) packaged under Aruba and the Fiberstore tree (`mibs/fs` / `fs-ruijie`) packaged under Ruijie; the notes also describe other legacy shared-directory mappings. These records describe archive placement, not a claim that every included MIB is directly referenced by a discovery YAML.

This manifest covers OS identity and hardware-sensor inputs. It does not establish source provenance for the separate interface-monitoring/exporter path. In the current code, unprovenanced `snmp_exporter` modules are not emitted; do not read the hardware YAML coverage or MIB folder count as proof that interface counters are being collected.

The fixed bundle importer accepts only `bundle_path` entries listed in the manifest. Unlisted local files, such as test placeholders, are ignored; caller-supplied MIB directories continue to use the normal recursive scan. Manifest SHA-256 and size values describe the bundled files. `.gitattributes` marks the pinned YAML and MIB paths `-text`, preserving the exact upstream bytes in Git objects on Windows and Linux so the recorded hashes remain verifiable. Upstream file notices are retained. See `LICENSE.txt` and the copyright headers in individual source files.
