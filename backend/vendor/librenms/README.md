# Pinned LibreNMS source bundle

This directory contains the local LibreNMS rule and MIB snapshot used by Nexora. Runtime collection is performed by Nexora's Python services; the collector never executes PHP and does not fetch rules from GitHub.

- Upstream repository: https://github.com/librenms/librenms
- Pinned revision: `6c26b4fe4a40f7b392c19c36a44257212736e38c` (2026-09-29)
- OS profiles: 136 across 25 upstream-profile vendors
- OS identity YAML: 136/136 profiles
- Hardware discovery YAML: 122/136 profiles; 14 profiles have no upstream hardware discovery YAML
- Hardware YAML parsed by the current Python rule parser: 912 sensor definitions, 54 processor definitions, and 46 memory-pool definitions
- Profiles with at least one parsed hardware definition: 91/136
- Profiles with a hardware discovery YAML but no recognized processor, memory-pool, or sensor definition: 31/122
- MIB manifest mappings: 2,360; unique upstream MIB paths: 2,359
- Rule YAML files: 258; pinned adapter source files: 29
- Manifest location: [`source-manifest.json`](source-manifest.json)

The repository also retains 12 historical Cisco test placeholders (`TEST-MIB-0` through `TEST-MIB-11`). They are empty fixtures, are not upstream LibreNMS inputs, and are intentionally excluded from the manifest and collection.

The current parser maps standard hardware classes for temperature (53 profiles), fan speed (20), fan state (31), power measurements (27), power-supply state (29), voltage (29), current (25), optical dBm (26), and other upstream gauges. These counts describe profiles with a parsed definition, not a guarantee that every device model implements every OID. Polling records incomplete walks, unsupported user functions, invalid values, and absent OIDs as partial/unsupported/missing instead of inventing a value. There is no blanket fallback to guessed vendor OIDs.

The fixed YAML inputs are read from `resources/definitions/os_detection/` and `resources/definitions/os_discovery/`. Nexora parses and polls supported definitions in Python. The inventory includes upstream CPU and memory definitions as well as temperature, fan, power, voltage, current, optical power and component-state definitions. Metrics are normalized and exposed through the Nexora hardware inventory and Grafana exporter. Other upstream gauges without a canonical unit are retained as generic values with their declared unit.

System uptime is read from the standard SNMP `SNMPv2-MIB::sysUpTime` counter, converted from centiseconds to seconds, and displayed through the monitoring API/UI and Grafana. It is not a hardware sensor rule.

## Comware and vendor-specific sources

The Comware Python adapter verifies the pinned LibreNMS `LibreNMS/OS/Comware.php` and sensor-discovery sources, then uses their pinned MIB inputs for chassis/transceiver temperature, optical receive/transmit power, transceiver voltage, and bias current. It also consumes the pinned Comware YAML for processor/memory definitions, fan and power-supply states, and supported power readings. LibreNMS uses MIB-backed Comware sensor discovery in its PHP runtime; Nexora ports the supported OIDs, index handling, sentinel filtering and unit conversion into Python.

The system uptime path is independent of the hardware YAML path. Interface counters are a separate SNMP exporter path and are not proven by the presence of this hardware bundle.

## Wireless source coverage

MIB availability alone does not create a poll rule. A wireless feature is supported only where Nexora has an exact, source-verified Python adapter or a parsed YAML definition. Wireless samples are tagged with their source and OS profile; AP counts, AP/client counts, radio/client readings, and component states remain distinct.

The legacy Huawei, H3C, Ruijie, Cisco, Aruba, and Ruckus wireless SNMP Exporter catalog variants are disabled and removed from active collection plans/assignments. Python executes the adapters synchronized with the pinned LibreNMS sources. Comware remains a documented exception: LibreNMS ships HH3C-DOT11 MIB definitions but its Comware OS class has no wireless discovery rule, so the local Python MIB adapter is not presented as an upstream LibreNMS wireless rule.

The pinned [`LibreNMS/Modules/Wireless.php`](LibreNMS/Modules/Wireless.php) is the generic discovery/polling dispatcher. It selects wireless sensor types, then calls a vendor OS class only when that class implements the matching wireless discovery interface. It contains the dispatch mechanism, not vendor OIDs or AP table definitions. The manifest pins this dispatcher alongside each upstream OS rule so the Python provenance check covers both the generic entry point and the vendor implementation.

The pinned LibreNMS OS classes with wireless AP/client discovery methods in the current MIB vendor bundle are: `airos`, `aruba-instant`, `arubaos`, `ciscowlc`, `ios`, `iosxe`, `ewc`, `routeros`, `ruckuswireless`, `ruckuswireless-hotzone`, `ruckuswireless-sz`, `ruckuswireless-unleashed`, `stellar`, `unifi`, and `vrp`. Nexora's Python adapters implement all 20 rule keys declared by the pinned wireless dispatcher, including Stellar's custom `apClientWlanService` walk and its per-SSID and total-client aggregation. LibreNMS registers Stellar client sensors with empty standard OIDs because its polling method performs that custom walk; this does not mean the sensors are unpolled. IOS-XE's pinned `Iosxe` class extends `Ciscowlc`, so it legitimately inherits Cisco WLC AP/client discovery; both classes are pinned as adapter sources.

AP/radio detail is a narrower capability than AP/client metrics. The pinned sources that enumerate AP/radio records are Cisco WLC (`LibreNMS/OS/Ciscowlc.php`), Huawei VRP (`LibreNMS/OS/Vrp.php`), and the Aruba controller poller (`includes/polling/aruba-controller.inc.php`). Aruba Instant (`LibreNMS/OS/ArubaInstant.php`) also discovers AP entities and radio measurements, while Extreme EWC (`LibreNMS/OS/Ewc.php`) exposes AP client counts and per-AP/radio telemetry. Their exact MIB source files and dependencies, including the previously omitted EWC DOT11 extension MIB, are pinned and SHA-verified. Aggregate counts and client rows remain distinct from AP inventory and radio state.

The Python wireless adapters also cover upstream radio-only rules from the existing Cisco, Ubiquiti, and Nokia MIB buckets: Cisco SAT errors/RSSI/SNR, Ubiquiti AirFiber/AirFiber LTU/AirFiber 60 frequency, distance, power, quality, rate and signal readings, and Nokia TiMOS cellular channel/RSSI/RSRP/RSRQ/SNR. These are radio/cellular measurements, not Wi-Fi AP inventory. Nokia Wavence's RF power sensors come from its pinned OS discovery YAML and use the regular Python YAML poller. Yunshan's pinned YAML defines Huawei WLAN redundancy states but not AP/client counts.

This wireless inventory is limited to vendor MIB inputs already present in this bundle; each adapter's MIB paths are validated against `source-manifest.json`. No additional vendor MIB directories or outside-vendor rules are introduced. `LibreNMS/Modules/Wireless.php` remains the generic dispatcher, while each OS class supplies its own rule. Comware has no upstream wireless discovery interface, so H3C AP/radio continues through the separately labeled Nexora Python MIB adapter based on the bundled H3C MIB definitions.

The Python adapters reproduce the supported discovery/polling OIDs, indexes, units, value conversions, aggregation and state mappings. They do not run LibreNMS's alert engine; some upstream `WirelessSensor` warning/limit thresholds are therefore not evaluated as NetOps wireless alerts.

## Hardware definition gaps

The 14 profiles without a hardware discovery YAML are: `acsw`, `allied`, `ciscome1200`, `ciscospa`, `cyan`, `dell-sonic`, `dlinkap`, `edgecos`, `equallogic`, `juniperex2500os`, `pixos`, `ruckuswireless-sz`, `sanos`, and `smartax-mdu`.

The 31 profiles with a discovery YAML but no processor, memory-pool, or sensor definition recognized by the current parser are: `acano`, `acs`, `allied-tq`, `apic`, `arista-mos`, `arista_eos`, `asyncos`, `cat1900`, `catos`, `cips`, `ciscoepc`, `ciscosce`, `ciscosrp`, `ciscowap`, `clearpass`, `dell-laser`, `dell-powervault`, `dell-rcs`, `edgeos`, `extremeware`, `fxos`, `huaweiups`, `ise`, `jwos`, `nxos`, `powervault`, `primeinfrastructure`, `stellar`, `tplink`, `unifi-usp`, and `zxdsl`. These 45 cases are not claimed as hardware-collection coverage. The `airos` profile also has a partial YAML condition requiring a reviewed identity adapter.

## Bundle and scope notes

The manifest records exact upstream paths, local bundle paths, SHA-256 hashes, source files, and MIB module references. The pinned MIB snapshot maps 2,360 bundle entries to 2,359 unique upstream paths; shared upstream files can be packaged under distinct Nexora vendor scopes. It contains files from 36 upstream `mibs/` vendor directories, grouped into 23 Nexora vendor-scope directories, plus standard/root dependencies. These directory counts are archive layout, not a claim that every MIB in a directory is used by a poller.

Shared directory mappings include HP ProCurve under Aruba, Fiberstore under Ruijie, and the existing Nokia, Nortel, Radlan, and root UPS mappings. `platform_vendor_scope` is an offline-index grouping and does not identify the upstream MIB owner or decide which rules execute. This bundle is not the full LibreNMS runtime and makes no hardware-rule coverage claim for asset vendors without a pinned upstream OS profile, including DPtech.

All manifest-listed YAML, MIB, and adapter files are hash-checked by the source policy. `.gitattributes` marks the pinned paths `-text` so upstream bytes and recorded hashes remain stable across Windows and Linux. PHP files in this bundle are read-only, pinned source references; all executable polling and supported adaptations are Python.
