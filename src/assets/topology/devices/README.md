# Topology device icon catalog

Store topology artwork by device category:

- `switches/` — L2/L3 switches; runtime uses `switch.svg`.
- `routers/` — routers and gateways.
- `firewalls/` — firewalls and security appliances.
- `servers/` — physical or virtual servers.
- `wireless/` — wireless controllers and access points.
- `generic/` — fallback artwork for unknown device types.

The topology canvas uses SVG assets and renders them at a controlled CSS size. PNG variants can stay beside the SVG for export, thumbnails, or external consumers. Do not change the runtime master filename unless the import in `TopologyGraph.tsx` is updated as well.

Runtime canonical filenames:

- `switches/switch.svg`
- `routers/router.svg`
- `firewalls/firewall.svg`
- `wireless/wireless.svg`
