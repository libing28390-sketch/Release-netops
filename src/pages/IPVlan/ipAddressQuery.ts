export interface IPAddressInventoryFilterInput {
  siteId: string;
  prefixId: string;
  search: string;
  statusFilter: string;
  typeFilter: string;
  purposeFilter: string;
  isMatrixView: boolean;
}

/** Shared list/export filters for registered records and read-only observations. */
export function buildIPAddressInventoryQuery(input: IPAddressInventoryFilterInput): URLSearchParams {
  const params = new URLSearchParams({
    site_id: input.siteId,
    registered_only: 'false',
  });
  if (input.prefixId) params.set('prefix_id', input.prefixId);
  if (input.search.trim()) params.set('q', input.search.trim());

  const includeTableFilters = !input.isMatrixView || input.statusFilter !== 'available';
  if (includeTableFilters && input.statusFilter !== 'all') params.set('status', input.statusFilter);
  if (includeTableFilters && input.typeFilter !== 'all') params.set('device_type', input.typeFilter);
  if (includeTableFilters && input.purposeFilter !== 'all') params.set('purpose', input.purposeFilter);
  return params;
}
