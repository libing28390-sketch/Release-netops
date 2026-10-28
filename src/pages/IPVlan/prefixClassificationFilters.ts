export const PREFIX_CLASSIFICATION_FILTERS = [
  'all',
  'auto',
  'manual',
  'unclassified',
  'mixed',
  'conflict',
  'reuse',
  'stale',
] as const;

export type PrefixClassificationFilter = typeof PREFIX_CLASSIFICATION_FILTERS[number];
export type PrefixClassificationCategory = Exclude<PrefixClassificationFilter, 'all'>;

export interface PrefixListQueryState {
  q: string;
  site: string;
  status: string;
  family: string;
  page: number;
  pageSize: number;
  classification: PrefixClassificationFilter;
}

export interface PrefixClassificationSummaryQueryState {
  q: string;
  site: string;
  status: string;
  family: string;
}

export function togglePrefixClassificationFilter(
  current: PrefixClassificationFilter,
  selected: PrefixClassificationCategory,
): PrefixClassificationFilter {
  return current === selected ? 'all' : selected;
}

export function buildPrefixListQuery(state: PrefixListQueryState): URLSearchParams {
  return new URLSearchParams({
    q: state.q,
    site: state.site,
    status: state.status,
    family: state.family,
    page: String(state.page),
    page_size: String(state.pageSize),
    classification: state.classification,
  });
}

export function buildPrefixClassificationSummaryQuery(
  state: PrefixClassificationSummaryQueryState,
): URLSearchParams {
  return new URLSearchParams({
    q: state.q,
    site: state.site,
    status: state.status,
    family: state.family,
  });
}
