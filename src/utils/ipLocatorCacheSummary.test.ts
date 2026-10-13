import { describe, expect, it } from 'vitest';
import { summarizeLocatorCache } from './ipLocatorCacheSummary';

describe('summarizeLocatorCache', () => {
  it('reports Redis use when any evidence came from Redis, even with mixed sources', () => {
    expect(summarizeLocatorCache([
      { source: 'postgres' },
      { source: 'negative_redis' },
      { source: 'cli' },
    ], '2026-09-12T14:27:59+08:00')).toEqual({
      redisUsage: 'used',
      dataUpdatedAt: '2026-09-12T14:27:59+08:00',
    });
  });

  it('reports Redis not used when all recorded sources are PostgreSQL or CLI', () => {
    expect(summarizeLocatorCache([
      { source: 'postgres' },
      { source: 'cli' },
    ], '2026-09-13T10:57:07+08:00').redisUsage).toBe('not_used');
  });

  it('does not treat the query time as the data update time', () => {
    expect(summarizeLocatorCache([{ source: 'redis' }], null, null, {
      cacheEnabled: true,
    })).toEqual({ redisUsage: 'used', dataUpdatedAt: null });
  });

  it('uses an explicitly reported legacy cache timestamp when evidence time is absent', () => {
    expect(summarizeLocatorCache(undefined, null, '2026-09-12T14:27:59+08:00', {
      cacheEnabled: true,
    })).toEqual({
      redisUsage: 'unknown',
      dataUpdatedAt: '2026-09-12T14:27:59+08:00',
    });
  });

  it('reports forced refresh as not using Redis when provenance is unavailable', () => {
    expect(summarizeLocatorCache(undefined, null, null, {
      forceRefresh: true,
    }).redisUsage).toBe('not_used');
  });
});
