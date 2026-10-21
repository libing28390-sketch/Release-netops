export interface RackSiteLabelSource {
  site_id?: string;
  site_code?: string;
  site_name?: string;
  datacenter?: string;
}

export interface RackSiteDirectoryEntry {
  id: string;
  site_code?: string;
  site_name?: string;
}

export function getRackSiteLabel(
  rack: RackSiteLabelSource | undefined,
  sitesById: ReadonlyMap<string, RackSiteDirectoryEntry>,
): string {
  if (!rack) return '';

  const site = rack.site_id ? sitesById.get(rack.site_id) : undefined;
  return site?.site_name
    || rack.site_name
    || site?.site_code
    || rack.site_code
    || rack.datacenter
    || rack.site_id
    || '';
}
