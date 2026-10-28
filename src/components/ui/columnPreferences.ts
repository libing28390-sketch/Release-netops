export interface ColumnPreferenceDefinition<Key extends string = string> {
  key: Key;
  defaultVisible: boolean;
  required?: boolean;
  isAction?: boolean;
}

type ColumnPreferenceStorage = Pick<Storage, 'getItem' | 'setItem'>;

function getBrowserStorage(): ColumnPreferenceStorage | undefined {
  if (typeof window === 'undefined') return undefined;
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

export function normalizeVisibleColumnKeys<Key extends string>(
  definitions: readonly ColumnPreferenceDefinition<Key>[],
  value: unknown,
): Key[] {
  const rawKeys = Array.isArray(value) ? value : [];
  const saved = new Set(rawKeys.filter((key): key is Key => typeof key === 'string'));
  definitions.forEach((definition) => {
    if (definition.required) saved.add(definition.key);
  });
  const hasVisibleDataColumn = definitions.some((definition) => !definition.isAction && saved.has(definition.key));
  if (!hasVisibleDataColumn && definitions.length > 0) {
    const fallback = definitions.find((definition) => !definition.isAction && definition.defaultVisible)
      || definitions.find((definition) => !definition.isAction)
      || definitions[0];
    saved.add(fallback.key);
  }
  return definitions.filter((definition) => saved.has(definition.key)).map((definition) => definition.key);
}

export function loadVisibleColumnKeys<Key extends string>(
  storageKey: string,
  definitions: readonly ColumnPreferenceDefinition<Key>[],
  storage = getBrowserStorage(),
): Key[] {
  const defaults = definitions.filter((definition) => definition.defaultVisible || definition.required).map((definition) => definition.key);
  if (!storage) return normalizeVisibleColumnKeys(definitions, defaults);
  try {
    const saved = storage.getItem(storageKey);
    return normalizeVisibleColumnKeys(definitions, saved ? JSON.parse(saved) : defaults);
  } catch {
    return normalizeVisibleColumnKeys(definitions, defaults);
  }
}

export function saveVisibleColumnKeys<Key extends string>(
  storageKey: string,
  definitions: readonly ColumnPreferenceDefinition<Key>[],
  visibleKeys: readonly Key[],
  storage = getBrowserStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(storageKey, JSON.stringify(normalizeVisibleColumnKeys(definitions, visibleKeys)));
  } catch {
    // Continue using the in-memory selection if local storage is unavailable.
  }
}
