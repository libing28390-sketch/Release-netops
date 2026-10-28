export interface RegisteredIPAddressFilterInput {
  siteId: string;
  prefixId: string;
  search: string;
  statusFilter: string;
  typeFilter: string;
  purposeFilter: string;
  isMatrixView: boolean;
}

/** Shared list/export filters for the formal IPAM address ledger. */
export function buildRegisteredIPAddressFilterQuery(input: RegisteredIPAddressFilterInput): URLSearchParams {
  const params = new URLSearchParams({
    site_id: input.siteId,
    registered_only: 'true',
  });
  if (input.prefixId) params.set('prefix_id', input.prefixId);
  if (input.search.trim()) params.set('q', input.search.trim());

  const includeTableFilters = !input.isMatrixView || input.statusFilter !== 'available';
  if (includeTableFilters && input.statusFilter !== 'all') params.set('status', input.statusFilter);
  if (includeTableFilters && input.typeFilter !== 'all') params.set('device_type', input.typeFilter);
  if (includeTableFilters && input.purposeFilter !== 'all') params.set('purpose', input.purposeFilter);
  return params;
}
