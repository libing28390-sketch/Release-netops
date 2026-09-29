# LibreNMS OS hardware capability source matrix

Pinned source: `6c26b4fe4a40f7b392c19c36a44257212736e38c`. This matrix covers 136 OS detection profiles; 122 hardware discovery YAML files are present in the curated bundle.

Each row is a static source audit. `OID numeric/bundle/missing/none` counts definitions whose primary OID source is explicit numeric syntax, references MIB modules present in the curated bundle, references a module missing from the bundle, or has no statically resolvable source. A bundled module does not prove the named symbol exists in the imported MIB node index or responds on a device. `static poll candidate` only means source shape, function allowlist, and skip operator grammar pass static checks; it is not a successful runtime poll.

`processors/mempools/sensors` are definition counts. `user_func supported/unsupported` and `skip supported/unsupported` count definitions containing those features. `states/limits` count definitions with explicit state mappings/state names or threshold fields. `port/index` counts definitions marked `entPhysicalIndex_measured: ports` and indexed `num_oid` templates; it does not imply a resolved IF-MIB association. Device identity, hardware presence, and runtime coverage remain per-device capabilities.

| OS key | Asset vendor | Definitions | Processor / memory / sensors | OID numeric / bundle / missing / none | user_func supported / unsupported | skip supported / unsupported | states / limits | port-measured / indexed | Static poll candidate |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| acano | Cisco | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| acs | Cisco | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| acsw | Cisco | — | 0/0/0 | — | 0/0 | 0/0 | 0/0 | 0/0 | no discovery YAML |
| airos-af-ltu | Ubiquiti | 6 | 1/0/5 | 6/0/0/0 | 0/0 | 0/0 | 3/0 | 0/6 | static poll candidate 6/6 |
| airos-af | Ubiquiti | 5 | 1/0/4 | 5/0/0/0 | 0/0 | 0/0 | 2/0 | 0/5 | static poll candidate 5/5 |
| airos-af60 | Ubiquiti | 6 | 1/0/5 | 6/0/0/0 | 0/0 | 0/0 | 3/0 | 0/6 | static poll candidate 6/6 |
| airos | Ubiquiti | 4 | 1/0/3 | 4/0/0/0 | 0/0 | 2/0 | 1/0 | 0/4 | static poll candidate 4/4 |
| allied-tq | Allied Telesis | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| allied | Allied Telesis | — | 0/0/0 | — | 0/0 | 0/0 | 0/0 | 0/0 | no discovery YAML |
| aos | Alcatel-Lucent Enterprise | 3 | 1/0/2 | 3/0/0/0 | 0/0 | 2/0 | 2/0 | 0/3 | static poll candidate 3/3 |
| aos6 | Alcatel-Lucent Enterprise | 11 | 1/1/9 | 10/1/0/0 | 0/0 | 2/0 | 4/5 | 5/10 | static poll candidate 11/11 |
| aos7 | Alcatel-Lucent Enterprise | 16 | 1/1/14 | 15/1/0/0 | 0/0 | 10/0 | 7/7 | 6/15 | static poll candidate 16/16 |
| apic | Cisco | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| arista-mos | Arista | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| arista_eos | Arista | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| aruba-instant | Aruba | 3 | 0/1/2 | 2/1/0/0 | 0/0 | 0/0 | 2/0 | 0/2 | static poll candidate 3/3 |
| arubaos-cx | Aruba | 15 | 0/0/15 | 15/0/0/0 | 2/0 | 1/0 | 6/6 | 5/15 | static poll candidate 15/15 |
| arubaos | Aruba | 4 | 1/1/2 | 3/1/0/0 | 0/0 | 0/0 | 0/0 | 0/3 | static poll candidate 4/4 |
| asa | Cisco | 13 | 0/0/13 | 13/0/0/0 | 0/0 | 1/0 | 3/0 | 0/13 | static poll candidate 13/13 |
| asyncos | Cisco | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| awplus | Allied Telesis | 13 | 1/0/12 | 13/0/0/0 | 2/0 | 3/0 | 4/8 | 5/13 | static poll candidate 13/13 |
| boss | Extreme Networks | 1 | 0/1/0 | 0/1/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | static poll candidate 1/1 |
| broadworks | Cisco | 22 | 0/0/22 | 22/0/0/0 | 0/0 | 0/0 | 1/0 | 0/22 | static poll candidate 22/22 |
| cat1900 | Cisco | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| catos | Cisco | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| ciena-rls | Ciena | 12 | 0/0/12 | 12/0/0/0 | 0/0 | 1/0 | 4/2 | 0/12 | static poll candidate 12/12 |
| ciena-saos | Ciena | 14 | 0/0/14 | 14/0/0/0 | 0/0 | 11/0 | 4/5 | 6/14 | static poll candidate 14/14 |
| ciena-sds | Ciena | 63 | 4/0/59 | 63/0/0/0 | 0/0 | 32/0 | 44/15 | 12/63 | static poll candidate 63/63 |
| ciena-waveserver | Ciena | 7 | 0/0/7 | 7/0/0/0 | 0/0 | 6/0 | 4/3 | 0/7 | static poll candidate 7/7 |
| cimc | Cisco | 19 | 0/0/19 | 19/0/0/0 | 0/0 | 3/0 | 9/2 | 0/19 | static poll candidate 19/19 |
| cips | Cisco | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| ciscoepc | Cisco | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| ciscome1200 | Cisco | — | 0/0/0 | — | 0/0 | 0/0 | 0/0 | 0/0 | no discovery YAML |
| ciscosat | Cisco | 2 | 0/0/2 | 2/0/0/0 | 0/0 | 1/0 | 1/0 | 0/2 | static poll candidate 2/2 |
| ciscosb | Cisco | 6 | 1/0/5 | 6/0/0/0 | 0/0 | 4/0 | 2/3 | 0/6 | static poll candidate 6/6 |
| ciscosce | Cisco | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| ciscospa | Cisco | — | 0/0/0 | — | 0/0 | 0/0 | 0/0 | 0/0 | no discovery YAML |
| ciscosrp | Cisco | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| ciscowap | Cisco | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| ciscowlc | Cisco | 2 | 1/1/0 | 1/1/0/0 | 0/0 | 0/0 | 0/0 | 0/1 | static poll candidate 2/2 |
| clearpass | Aruba | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| comware | H3C | 3 | 0/0/3 | 3/0/0/0 | 0/0 | 1/0 | 2/0 | 0/3 | static poll candidate 3/3 |
| cyan | Ciena | — | 0/0/0 | — | 0/0 | 0/0 | 0/0 | 0/0 | no discovery YAML |
| dcn-software | DCN | 2 | 1/1/0 | 1/1/0/0 | 0/0 | 0/0 | 0/0 | 0/1 | static poll candidate 2/2 |
| dell-compellent | Dell | 26 | 0/0/26 | 26/0/0/0 | 0/0 | 0/0 | 15/3 | 0/26 | static poll candidate 26/26 |
| dell-laser | Dell | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| dell-ome-m | Dell | 16 | 0/0/16 | 16/0/0/0 | 0/0 | 0/0 | 9/0 | 0/16 | static poll candidate 16/16 |
| dell-os10 | Dell | 5 | 0/0/5 | 5/0/0/0 | 0/0 | 0/0 | 3/0 | 0/5 | static poll candidate 5/5 |
| dell-powervault | Dell | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| dell-rcs | Dell | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| dell-rpdu | Dell | 10 | 0/0/10 | 10/0/0/0 | 0/0 | 0/0 | 3/0 | 0/10 | static poll candidate 10/10 |
| dell-sonic | Dell | — | 0/0/0 | — | 0/0 | 0/0 | 0/0 | 0/0 | no discovery YAML |
| dell-ups | Dell | 2 | 0/0/2 | 2/0/0/0 | 0/0 | 0/0 | 1/1 | 0/2 | static poll candidate 2/2 |
| dlink-dgs1250 | D-Link | 16 | 1/1/14 | 15/1/0/0 | 0/0 | 1/0 | 8/6 | 0/15 | static poll candidate 16/16 |
| dlink | D-Link | 9 | 2/2/5 | 7/2/0/0 | 0/0 | 0/0 | 3/1 | 0/7 | static poll candidate 9/9 |
| dlinkap | D-Link | — | 0/0/0 | — | 0/0 | 0/0 | 0/0 | 0/0 | no discovery YAML |
| dnos | Dell | 24 | 2/1/21 | 23/1/0/0 | 0/0 | 16/0 | 6/0 | 0/23 | static poll candidate 24/24 |
| drac | Dell | 43 | 0/0/43 | 43/0/0/0 | 0/0 | 4/0 | 24/3 | 0/43 | static poll candidate 43/43 |
| edgecos | Edgecore | — | 0/0/0 | — | 0/0 | 0/0 | 0/0 | 0/0 | no discovery YAML |
| edgeos-ep | Ubiquiti | 15 | 1/0/14 | 15/0/0/0 | 0/0 | 0/0 | 5/2 | 0/15 | static poll candidate 15/15 |
| edgeos | Ubiquiti | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| edgeosolt | Ubiquiti | 7 | 0/0/7 | 7/0/0/0 | 0/0 | 0/0 | 2/2 | 0/7 | static poll candidate 7/7 |
| edgeswitch | Ubiquiti | 6 | 0/1/5 | 5/1/0/0 | 0/0 | 0/0 | 3/0 | 0/5 | static poll candidate 6/6 |
| equallogic | Dell | — | 0/0/0 | — | 0/0 | 0/0 | 0/0 | 0/0 | no discovery YAML |
| ewc | Extreme Networks | 1 | 1/0/0 | 1/0/0/0 | 0/0 | 0/0 | 0/0 | 0/1 | static poll candidate 1/1 |
| exalink-fusion | Cisco | 6 | 0/0/6 | 6/0/0/0 | 0/0 | 0/0 | 1/1 | 0/6 | static poll candidate 6/6 |
| exos | Extreme Networks | 4 | 0/0/4 | 4/0/0/0 | 0/0 | 1/0 | 4/0 | 0/4 | static poll candidate 4/4 |
| extremeware | Extreme Networks | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| fabos | Brocade | 8 | 1/1/6 | 7/1/0/0 | 0/0 | 3/0 | 1/2 | 0/7 | static poll candidate 8/8 |
| fiberhome-switch | FiberHome | 7 | 1/1/5 | 6/1/0/0 | 0/0 | 0/0 | 2/2 | 0/6 | static poll candidate 7/7 |
| fiberhome | FiberHome | 5 | 1/1/3 | 4/1/0/0 | 0/0 | 2/0 | 2/1 | 0/4 | static poll candidate 5/5 |
| fluidfs | Dell | 19 | 0/0/19 | 19/0/0/0 | 0/0 | 0/0 | 10/0 | 0/9 | static poll candidate 19/19 |
| fs-ruijie | Ruijie | 10 | 1/1/8 | 9/1/0/0 | 0/0 | 5/0 | 3/3 | 0/9 | static poll candidate 10/10 |
| ftd | Cisco | 9 | 0/0/9 | 9/0/0/0 | 0/0 | 1/0 | 1/0 | 0/9 | static poll candidate 9/9 |
| fxos | Cisco | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| huawei-optixrtn | Huawei | 10 | 0/0/10 | 10/0/0/0 | 0/0 | 0/0 | 5/2 | 0/10 | static poll candidate 10/10 |
| huawei-smu | Huawei | 22 | 0/0/22 | 22/0/0/0 | 0/0 | 0/0 | 7/0 | 0/22 | static poll candidate 22/22 |
| huaweiups | Huawei | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| ibmc | Huawei | 9 | 1/0/8 | 9/0/0/0 | 0/0 | 3/0 | 5/0 | 0/9 | static poll candidate 9/9 |
| ios | Cisco | 7 | 0/0/7 | 7/0/0/0 | 0/0 | 0/0 | 2/1 | 0/7 | static poll candidate 7/7 |
| iosxe | Cisco | 9 | 0/0/9 | 9/0/0/0 | 0/0 | 2/0 | 2/1 | 0/9 | static poll candidate 9/9 |
| iosxr | Cisco | 6 | 0/0/6 | 6/0/0/0 | 0/0 | 1/0 | 5/0 | 0/6 | static poll candidate 6/6 |
| ironware | Brocade | 21 | 0/2/19 | 19/2/0/0 | 0/0 | 5/0 | 6/0 | 0/19 | static poll candidate 21/21 |
| ise | Cisco | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| jetstream | TP-Link | 15 | 1/1/13 | 14/1/0/0 | 2/0 | 4/0 | 4/6 | 10/14 | static poll candidate 15/15 |
| juniper-mss | Juniper | 2 | 1/1/0 | 1/1/0/0 | 0/0 | 0/0 | 0/0 | 0/1 | static poll candidate 2/2 |
| juniperex2500os | Juniper | — | 0/0/0 | — | 0/0 | 0/0 | 0/0 | 0/0 | no discovery YAML |
| junos | Juniper | 30 | 2/2/26 | 28/2/0/0 | 0/0 | 13/0 | 5/9 | 16/28 | static poll candidate 30/30 |
| junose | Juniper | 1 | 1/0/0 | 1/0/0/0 | 0/0 | 1/0 | 0/0 | 0/1 | static poll candidate 1/1 |
| jwos | Juniper | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| mypoweros | Maipu | 2 | 1/1/0 | 1/1/0/0 | 0/0 | 0/0 | 0/0 | 0/1 | static poll candidate 2/2 |
| nokia-1830 | Nokia | 27 | 0/0/27 | 27/0/0/0 | 0/0 | 0/0 | 8/1 | 13/27 | static poll candidate 27/27 |
| nokia-isam | Nokia | 6 | 1/1/4 | 5/1/0/0 | 0/0 | 0/0 | 3/1 | 0/5 | static poll candidate 6/6 |
| nos | Brocade | 2 | 1/1/0 | 2/0/0/0 | 0/0 | 0/0 | 0/0 | 0/1 | static poll candidate 2/2 |
| nxos | Cisco | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions (conservative YAML repair) |
| oceanstor | Huawei | 6 | 0/0/6 | 6/0/0/0 | 0/0 | 1/0 | 4/0 | 0/6 | static poll candidate 6/6 |
| omnipcx | Alcatel-Lucent Enterprise | 4 | 0/0/4 | 4/0/0/0 | 0/0 | 0/0 | 2/2 | 0/3 | static poll candidate 4/4 |
| ons | Cisco | 2 | 0/0/2 | 2/0/0/0 | 0/0 | 0/0 | 0/2 | 0/2 | static poll candidate 2/2 |
| pixos | Cisco | — | 0/0/0 | — | 0/0 | 0/0 | 0/0 | 0/0 | no discovery YAML |
| powerconnect | Dell | 1 | 0/1/0 | 1/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | static poll candidate 1/1 |
| powervault | Dell | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| primeinfrastructure | Cisco | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| procurve | Aruba | 13 | 1/2/10 | 11/2/0/0 | 0/0 | 3/0 | 6/2 | 0/11 | static poll candidate 13/13 |
| radlan | Allied Telesis | 1 | 1/0/0 | 1/0/0/0 | 0/0 | 0/0 | 0/0 | 0/1 | static poll candidate 1/1 |
| raisecom-ros | Raisecom | 7 | 1/1/5 | 6/1/0/0 | 0/0 | 3/0 | 2/3 | 3/6 | static poll candidate 7/7 |
| raisecom | Raisecom | 11 | 1/1/9 | 10/1/0/0 | 0/0 | 3/0 | 3/6 | 3/10 | static poll candidate 11/11 |
| routeros | MikroTik | 27 | 0/0/27 | 27/0/0/0 | 0/0 | 13/0 | 6/0 | 5/27 | static poll candidate 27/27 |
| ruckuswireless-hotzone | Ruckus | 2 | 1/1/0 | 1/1/0/0 | 0/0 | 0/0 | 0/0 | 0/1 | static poll candidate 2/2 |
| ruckuswireless-sz | Ruckus | — | 0/0/0 | — | 0/0 | 0/0 | 0/0 | 0/0 | no discovery YAML |
| ruckuswireless-unleashed | Ruckus | 2 | 1/1/0 | 1/1/0/0 | 0/0 | 0/0 | 0/0 | 0/1 | static poll candidate 2/2 |
| ruckuswireless | Ruckus | 2 | 1/1/0 | 1/1/0/0 | 0/0 | 0/0 | 0/0 | 0/1 | static poll candidate 2/2 |
| ruijie | Ruijie | 12 | 1/1/10 | 11/1/0/0 | 0/0 | 4/0 | 3/3 | 0/11 | static poll candidate 12/12 |
| sanos | Cisco | — | 0/0/0 | — | 0/0 | 0/0 | 0/0 | 0/0 | no discovery YAML |
| screenos | Juniper | 2 | 1/1/0 | 1/1/0/0 | 0/0 | 0/0 | 0/0 | 0/1 | static poll candidate 2/2 |
| serveriron | Brocade | 1 | 0/1/0 | 0/1/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | static poll candidate 1/1 |
| slxos | Extreme Networks | 5 | 1/1/3 | 4/1/0/0 | 0/0 | 2/0 | 1/0 | 0/4 | static poll candidate 5/5 |
| smartax-mdu | Huawei | — | 0/0/0 | — | 0/0 | 0/0 | 0/0 | 0/0 | no discovery YAML |
| smartax | Huawei | 16 | 0/1/15 | 15/1/0/0 | 0/0 | 7/0 | 5/0 | 0/15 | static poll candidate 16/16 |
| srlinux | Nokia | 8 | 1/1/6 | 7/1/0/0 | 0/0 | 4/0 | 3/0 | 0/7 | static poll candidate 8/8 |
| stellar | Alcatel-Lucent Enterprise | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| swos | MikroTik | 33 | 0/0/33 | 33/0/0/0 | 0/0 | 3/0 | 5/1 | 5/33 | static poll candidate 33/33 |
| timos | Nokia | 75 | 1/1/73 | 74/1/0/0 | 5/0 | 15/0 | 20/17 | 11/74 | static poll candidate 75/75 |
| tplink | TP-Link | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| ucos | Cisco | 3 | 0/0/3 | 3/0/0/0 | 0/0 | 0/0 | 3/0 | 0/3 | static poll candidate 3/3 |
| unifi-usp | Ubiquiti | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| unifi | Ubiquiti | 1 | 0/1/0 | 0/0/1/0 | 0/0 | 0/0 | 0/0 | 0/0 | static poll candidate 0/1 (`frogfoot-resources-mib` unresolved) |
| viptela | Cisco | 1 | 0/1/0 | 0/1/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | static poll candidate 1/1 |
| voss | Extreme Networks | 4 | 1/1/2 | 3/1/0/0 | 0/0 | 0/0 | 1/1 | 0/3 | static poll candidate 4/4 |
| vrp | Huawei | 43 | 1/0/42 | 43/0/0/0 | 2/0 | 28/0 | 12/5 | 10/43 | static poll candidate 43/43 |
| waas | Cisco | 1 | 0/0/1 | 1/0/0/0 | 0/0 | 0/0 | 1/0 | 0/1 | static poll candidate 1/1 |
| wavence | Nokia | 4 | 0/0/4 | 4/0/0/0 | 0/0 | 0/0 | 0/0 | 0/4 | static poll candidate 4/4 |
| xos | Extreme Networks | 5 | 1/1/3 | 4/1/0/0 | 0/0 | 0/0 | 0/1 | 0/4 | static poll candidate 5/5 |
| yunshan | Huawei | 38 | 1/0/37 | 38/0/0/0 | 0/0 | 23/0 | 11/4 | 2/38 | static poll candidate 38/38 |
| zxa10 | ZTE | 11 | 1/1/9 | 10/1/0/0 | 0/0 | 5/0 | 3/1 | 0/10 | static poll candidate 11/11 |
| zxdsl | ZTE | 0 | 0/0/0 | 0/0/0/0 | 0/0 | 0/0 | 0/0 | 0/0 | no hardware definitions |
| zxr10 | ZTE | 2 | 1/1/0 | 1/1/0/0 | 0/0 | 0/0 | 0/0 | 0/1 | static poll candidate 2/2 |

Profiles without a matching discovery YAML are listed with zero definitions. The UniFi `unifi` mempool rule references `FROGFOOT-RESOURCES-MIB`, which is absent from the pinned bundle; its two memory OIDs are unsupported until that source MIB is added and verified. The importer and probe preserve this as unsupported and do not invent replacement OIDs.
