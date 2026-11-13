export const formatResourcePercent = (value: number | null | undefined) => {
  if (value == null || !Number.isFinite(value)) return '--';
  return `${Math.round(value)}%`;
};

export const formatCompactResourcePercent = (value: number | null | undefined) => {
  if (value == null || !Number.isFinite(value)) return '--';
  return String(Math.round(value));
};

/** Display MAC addresses consistently as xxxx-xxxx-xxxx. */
export const formatMacAddress = (value: unknown): string => {
  const raw = String(value ?? '').trim();
  const compact = raw.replace(/[^0-9a-f]/gi, '');
  if (compact.length !== 12) return raw;
  const normalized = compact.toLowerCase();
  return [0, 4, 8].map(index => normalized.slice(index, index + 4)).join('-');
};
