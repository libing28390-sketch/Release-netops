export function formatUptimeSeconds(value: unknown, language: 'zh' | 'en'): string {
  if (value === null || value === undefined || value === '') return '--';

  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 0) return '--';

  const total = Math.floor(seconds);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (language === 'zh') {
    return days > 0 ? `${days}天 ${hours}小时` : hours > 0 ? `${hours}小时 ${minutes}分钟` : `${minutes}分钟`;
  }
  return days > 0 ? `${days}d ${hours}h` : hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}
