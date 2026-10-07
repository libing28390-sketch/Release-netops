export interface TopologyGraphNodeRef {
  id: string;
}

export interface TopologyGraphLinkRef {
  source_device_id: string;
  target_device_id: string;
}

/** The canvas uses one visual rule: mutual evidence is solid, otherwise dashed. */
export const getTopologyLinkEvidenceDash = (link: {
  evidence_status?: string;
  reverse_confirmed?: boolean;
  metadata?: { reverse_seen?: boolean };
}): string => {
  const status = String(link.evidence_status || '').trim().toLowerCase();
  const confirmedBothWays = status === 'bidirectional_confirmed'
    || Boolean(link.reverse_confirmed || link.metadata?.reverse_seen);
  return confirmedBothWays ? '' : '6,5';
};

/**
 * Resolve link endpoints for D3 without merging rows. The API read model owns
 * link identity and de-duplication; the canvas must render every link row that
 * survives the active device filters.
 */
export const buildTopologyGraphLinks = <
  TNode extends TopologyGraphNodeRef,
  TLink extends TopologyGraphLinkRef,
>(
  nodes: TNode[],
  links: TLink[],
): Array<TLink & { source: TNode; target: TNode }> => {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const resolvedLinks: Array<TLink & { source: TNode; target: TNode }> = [];

  links.forEach((link) => {
    const source = nodeById.get(link.source_device_id);
    const target = nodeById.get(link.target_device_id);
    if (!source || !target) return;
    resolvedLinks.push({ ...link, source, target });
  });

  return resolvedLinks;
};
