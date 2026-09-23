export type LocatorRedisUsage = 'used' | 'not_used' | 'unknown';

export interface LocatorCacheProvenance {
  source?: string | null;
}

export interface LocatorCacheSummary {
  redisUsage: LocatorRedisUsage;
  dataUpdatedAt: string | null;
}

export function summarizeLocatorCache(
  provenance: readonly LocatorCacheProvenance[] | null | undefined,
  evidenceCollectedAt?: string | null,
  legacyCachedAt?: string | null,
  options: { cacheEnabled?: boolean; forceRefresh?: boolean } = {},
): LocatorCacheSummary {
  let redisUsage: LocatorRedisUsage = 'unknown';

  if (Array.isArray(provenance) && provenance.length > 0) {
    redisUsage = provenance.some((entry) => String(entry.source || '').toLowerCase().includes('redis'))
      ? 'used'
      : 'not_used';
  } else if (options.forceRefresh || options.cacheEnabled === false) {
    redisUsage = 'not_used';
  }

  const evidenceTime = String(evidenceCollectedAt || '').trim();
  const legacyCacheTime = String(legacyCachedAt || '').trim();
  const dataUpdatedAt = evidenceTime && !Number.isNaN(Date.parse(evidenceTime))
    ? evidenceTime
    : legacyCacheTime && !Number.isNaN(Date.parse(legacyCacheTime))
      ? legacyCacheTime
      : null;

  return { redisUsage, dataUpdatedAt };
}
