# Topology graph visualization

Read this reference when changing graph layout, interaction, or rendering performance. Check the current component and product acceptance criteria before extending behavior.

- Keep L2, L3, WAN tunnel, and aggregation views distinct where the product exposes those layers.
- Preserve existing layout modes and interactions. Hierarchical Core-to-Aggregation-to-Access and force-directed layouts are available patterns, not a requirement to add both to every change.
- For graphs with hundreds of nodes or edges, benchmark before changing the rendering path. Consider viewport culling, level-of-detail labels, and throttled zoom/pan handling where measurements justify them.
- Monitoring status indicators should update without causing a full graph relayout when the existing rendering model supports that separation.

The primary implementation is `src/components/TopologyGraph.tsx`; page integration is in `src/pages/TopologyPage.tsx`.
