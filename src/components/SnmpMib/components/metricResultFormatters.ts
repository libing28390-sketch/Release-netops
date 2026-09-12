export interface MetricResultValue {
  value?: unknown;
  raw_value?: unknown;
  unit?: string;
}

const formatRawAtom = (value: unknown): string => {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
};

const parseSeconds = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value >= 0 ? value : null;
  }

  const raw = String(value ?? '').trim();
  if (!raw) return null;

  const numeric = raw.match(/^([0-9]+(?:\.[0-9]+)?)\s*(?:s|sec|secs|second|seconds)?$/i);
  if (numeric) return Number(numeric[1]);

  const clock = raw.match(/^(?:(\d+)\s*days?,?\s*)?(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:\.(\d+))?$/i);
  if (clock) {
    const [, dayValue, hourValue, minuteValue, secondValue, fraction] = clock;
    const seconds = (
      Number(dayValue || 0) * 86400
      + Number(hourValue || 0) * 3600
      + Number(minuteValue || 0) * 60
      + Number(secondValue || 0)
    );
    const fractionValue = fraction ? Number(`0.${fraction}`) : 0;
    return seconds + fractionValue;
  }

  const duration = raw.match(/^(?:(\d+)\s*d(?:ays?)?\s*)?(?:(\d+)\s*h(?:ours?)?\s*)?(?:(\d+)\s*m(?:in(?:utes?)?)?\s*)?(?:(\d+)\s*s(?:ec(?:onds?)?)?\s*)?$/i);
  if (duration && duration.slice(1).some(Boolean)) {
    const [, days, hours, minutes, seconds] = duration;
    return Number(days || 0) * 86400
      + Number(hours || 0) * 3600
      + Number(minutes || 0) * 60
      + Number(seconds || 0);
  }

  return null;
};

const formatDuration = (seconds: number, zh: boolean): string => {
  const total = Math.max(0, Math.round(seconds));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;

  if (zh) {
    return [
      days ? `${days}天` : '',
      hours ? `${hours}小时` : '',
      minutes ? `${minutes}分钟` : '',
      remainder || total === 0 ? `${remainder}秒` : '',
    ].filter(Boolean).join(' ');
  }

  return [
    days ? `${days}d` : '',
    hours ? `${hours}h` : '',
    minutes ? `${minutes}m` : '',
    remainder || total === 0 ? `${remainder}s` : '',
  ].filter(Boolean).join(' ');
};

export const formatUptime = (value: unknown, zh: boolean): string => {
  const seconds = parseSeconds(value);
  return seconds === null ? formatRawAtom(value) : formatDuration(seconds, zh);
};

const isSecondsUnit = (unit?: string) => {
  const normalized = String(unit || '').trim().toLowerCase();
  return !normalized || ['s', 'sec', 'secs', 'second', 'seconds'].includes(normalized);
};

export const formatMetricValue = (key: string, detail: MetricResultValue, zh: boolean): string => {
  if (detail.value === true) return zh ? '正常' : 'Normal';
  if (detail.value === false) return zh ? '异常' : 'Abnormal';
  if (detail.value === null || detail.value === undefined || detail.value === '') return '—';

  if (key === 'uptime' && isSecondsUnit(detail.unit)) {
    return formatUptime(detail.value, zh);
  }

  return `${formatRawAtom(detail.value)}${detail.unit ? ` ${detail.unit}` : ''}`;
};

export const formatRawValue = (value: unknown): string => {
  if (Array.isArray(value)) return value.map(formatRawAtom).join(', ');
  return formatRawAtom(value);
};

const rawList = (value: unknown): unknown[] | null => {
  if (Array.isArray(value)) return value;
  if (typeof value !== 'string' || !/[\n,]/.test(value)) return null;

  const parts = value.split(/[\n,]+/).map(item => item.trim()).filter(Boolean);
  return parts.length > 1 ? parts : null;
};

export const summarizeRawValue = (value: unknown, zh: boolean): string => {
  const items = rawList(value);
  if (!items) return formatRawValue(value);
  if (!items.length) return '—';

  const counts = new Map<string, number>();
  for (const item of items) {
    const label = formatRawAtom(item);
    counts.set(label, (counts.get(label) || 0) + 1);
  }

  const groups = Array.from(counts.entries())
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]));
  const preview = groups.slice(0, 3).map(([label, count]) => (
    count > 1 ? `${label} × ${count}${zh ? '项' : ' items'}` : label
  ));
  const hidden = groups.length - preview.length;
  if (hidden > 0) preview.push(zh ? `另 ${hidden} 种` : `${hidden} more`);
  return preview.join(zh ? '；' : ', ');
};
