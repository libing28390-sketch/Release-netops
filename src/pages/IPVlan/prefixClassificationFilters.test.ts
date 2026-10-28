import { describe, expect, it } from 'vitest';
import {
  buildPrefixClassificationSummaryQuery,
  buildPrefixListQuery,
  togglePrefixClassificationFilter,
} from './prefixClassificationFilters';

describe('IPAM prefix classification filters', () => {
  it('selects a card category and clears it when the same card is clicked again', () => {
    expect(togglePrefixClassificationFilter('all', 'conflict')).toBe('conflict');
    expect(togglePrefixClassificationFilter('conflict', 'conflict')).toBe('all');
    expect(togglePrefixClassificationFilter('conflict', 'stale')).toBe('stale');
  });

  it('sends the selected category with list pagination and current base filters', () => {
    const query = buildPrefixListQuery({
      q: '10.255',
      site: 'site-wh-dc-01',
      status: 'active',
      family: 'ipv4',
      page: 2,
      pageSize: 10,
      classification: 'conflict',
    });

    expect(query.toString()).toBe('q=10.255&site=site-wh-dc-01&status=active&family=ipv4&page=2&page_size=10&classification=conflict');
  });

  it('scopes card totals to current page filters without collapsing totals to the selected card', () => {
    const query = buildPrefixClassificationSummaryQuery({
      q: '10.255',
      site: 'site-wh-dc-01',
      status: 'active',
      family: 'ipv4',
    });

    expect(query.toString()).toBe('q=10.255&site=site-wh-dc-01&status=active&family=ipv4');
    expect(query.has('classification')).toBe(false);
  });
});
