export const formatResourcePercent = (value: number | null | undefined) => {
  if (value == null || !Number.isFinite(value)) return '--';
  return `${Math.round(value)}%`;
};

export const formatCompactResourcePercent = (value: number | null | undefined) => {
  if (value == null || !Number.isFinite(value)) return '--';
  return String(Math.round(value));
};
