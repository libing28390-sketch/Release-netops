import { useCallback, useEffect, useMemo, useState } from 'react';

const FAVORITES_STORAGE_PREFIX = 'nexora_access_favorites';
const FAVORITES_CHANGED_EVENT = 'nexora:access-favorites-changed';

const storageKeyFor = (username: string) => (
  `${FAVORITES_STORAGE_PREFIX}:${encodeURIComponent(username.trim() || 'anonymous')}`
);

const readFavoriteIds = (key: string): string[] => {
  try {
    const raw = localStorage.getItem(key);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return Array.from(new Set(parsed.map((value) => String(value).trim()).filter(Boolean)));
  } catch {
    return [];
  }
};

const writeFavoriteIds = (key: string, ids: string[]) => {
  try {
    localStorage.setItem(key, JSON.stringify(ids));
    window.dispatchEvent(new Event(FAVORITES_CHANGED_EVENT));
  } catch {
    // Browser storage can be disabled or quota-limited. The in-memory state
    // still gives the user a useful session-local result in that case.
  }
};

/**
 * Per-user device favorites for the terminal-access module.
 *
 * Favorites are intentionally scoped by the authenticated username so a
 * shared workstation does not leak one operator's shortcuts to another.
 */
export const useAccessFavorites = (username?: string) => {
  const storageKey = useMemo(() => storageKeyFor(username || ''), [username]);
  const [favoriteDeviceIds, setFavoriteDeviceIds] = useState<string[]>(() => readFavoriteIds(storageKey));

  useEffect(() => {
    setFavoriteDeviceIds(readFavoriteIds(storageKey));
  }, [storageKey]);

  useEffect(() => {
    const refresh = () => setFavoriteDeviceIds(readFavoriteIds(storageKey));
    const handleStorage = (event: StorageEvent) => {
      if (event.key === storageKey) refresh();
    };
    window.addEventListener('storage', handleStorage);
    window.addEventListener(FAVORITES_CHANGED_EVENT, refresh);
    return () => {
      window.removeEventListener('storage', handleStorage);
      window.removeEventListener(FAVORITES_CHANGED_EVENT, refresh);
    };
  }, [storageKey]);

  const toggleFavorite = useCallback((deviceId: string) => {
    const normalizedId = String(deviceId || '').trim();
    if (!normalizedId) return;

    setFavoriteDeviceIds((current) => {
      const next = current.includes(normalizedId)
        ? current.filter((id) => id !== normalizedId)
        : [normalizedId, ...current];
      writeFavoriteIds(storageKey, next);
      return next;
    });
  }, [storageKey]);

  const isFavorite = useCallback((deviceId: string) => (
    favoriteDeviceIds.includes(String(deviceId || '').trim())
  ), [favoriteDeviceIds]);

  return { favoriteDeviceIds, toggleFavorite, isFavorite };
};

export default useAccessFavorites;
