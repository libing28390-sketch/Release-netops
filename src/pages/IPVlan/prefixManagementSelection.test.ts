import { describe, expect, it } from 'vitest';
import { areAllVisiblePrefixIdsSelected, toggleVisiblePrefixSelection } from './prefixManagementSelection';

describe('IPAM visible prefix selection', () => {
  it('selects visible page rows while preserving selections from other pages', () => {
    const next = toggleVisiblePrefixSelection(new Set(['page-1-row']), ['page-2-a', 'page-2-b']);

    expect(next).toEqual(new Set(['page-1-row', 'page-2-a', 'page-2-b']));
    expect(areAllVisiblePrefixIdsSelected(next, ['page-2-a', 'page-2-b'])).toBe(true);
  });

  it('clears only currently visible rows when all of them are already selected', () => {
    const next = toggleVisiblePrefixSelection(new Set(['page-1-row', 'page-2-a', 'page-2-b']), ['page-2-a', 'page-2-b']);

    expect(next).toEqual(new Set(['page-1-row']));
    expect(areAllVisiblePrefixIdsSelected(next, ['page-2-a', 'page-2-b'])).toBe(false);
  });
});
