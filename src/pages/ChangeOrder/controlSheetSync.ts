export interface ControlSheetDraft {
  change_time_start: string;
  change_time_end: string;
  implementer_id: string;
  implementer_username: string;
  co_reviewer_id: string;
  co_reviewer_username: string;
  device_ips: string;
  pre_check: string;
  execution: string;
  post_verify: string;
  business_verify: string;
  rollback_plan: string;
  [key: string]: unknown;
}

export interface ControlSheetPrimaryValues {
  scheduledStart: string;
  scheduledEnd: string;
  targetIps: string[];
  rollbackPlan: string;
}

export interface ControlSheetMirrorConflict {
  field: 'change_time' | 'device_ips' | 'rollback_plan';
  label: string;
  existingValue: string;
  primaryValue: string;
}

const asText = (value: unknown): string => (value == null ? '' : String(value));

const normalizeDateTime = (value: unknown): string => {
  const text = asText(value).trim();
  const match = text.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?(?:Z)?$/i);
  return match ? `${match[1]}T${match[2]}` : text.replace(/\s+/g, ' ').toLowerCase();
};

const splitIps = (value: unknown): string[] => {
  const values = Array.isArray(value) ? value : asText(value).split(/[\n,]+/);
  return values
    .map((item) => asText(item).trim().toLowerCase())
    .filter(Boolean);
};

const normalizeIps = (value: unknown): string[] => [...new Set(splitIps(value))].sort();

const normalizeText = (value: unknown): string => asText(value).replace(/\r\n?/g, '\n').trim();

const formatChangeWindow = (start: unknown, end: unknown): string => {
  const startValue = asText(start).trim();
  const endValue = asText(end).trim();
  if (!startValue && !endValue) return '';
  return `${startValue || '—'} – ${endValue || '—'}`;
};

export const getControlSheetMirrorConflicts = (
  controlSheet: Partial<ControlSheetDraft> | null | undefined,
  primaryValues: ControlSheetPrimaryValues,
): ControlSheetMirrorConflict[] => {
  const sheet = controlSheet || {};
  const conflicts: ControlSheetMirrorConflict[] = [];
  const existingStart = asText(sheet.change_time_start);
  const existingEnd = asText(sheet.change_time_end);
  const primaryStart = asText(primaryValues.scheduledStart);
  const primaryEnd = asText(primaryValues.scheduledEnd);

  if (
    (existingStart.trim() || existingEnd.trim()) &&
    (normalizeDateTime(existingStart) !== normalizeDateTime(primaryStart) ||
      normalizeDateTime(existingEnd) !== normalizeDateTime(primaryEnd))
  ) {
    conflicts.push({
      field: 'change_time',
      label: '变更时间窗口',
      existingValue: formatChangeWindow(existingStart, existingEnd),
      primaryValue: formatChangeWindow(primaryStart, primaryEnd),
    });
  }

  const existingIps = splitIps(sheet.device_ips);
  if (existingIps.length > 0) {
    const existingNormalizedIps = normalizeIps(existingIps);
    const primaryNormalizedIps = normalizeIps(primaryValues.targetIps);
    if (JSON.stringify(existingNormalizedIps) !== JSON.stringify(primaryNormalizedIps)) {
      conflicts.push({
        field: 'device_ips',
        label: '涉及设备 IP',
        existingValue: existingIps.join(', '),
        primaryValue: splitIps(primaryValues.targetIps).join(', '),
      });
    }
  }

  const existingRollback = asText(sheet.rollback_plan);
  if (
    normalizeText(existingRollback) &&
    normalizeText(existingRollback) !== normalizeText(primaryValues.rollbackPlan)
  ) {
    conflicts.push({
      field: 'rollback_plan',
      label: '回退方案',
      existingValue: existingRollback.trim(),
      primaryValue: asText(primaryValues.rollbackPlan).trim(),
    });
  }

  return conflicts;
};

export const synchronizeControlSheetMirrors = (
  controlSheet: Partial<ControlSheetDraft> | null | undefined,
  primaryValues: ControlSheetPrimaryValues,
): ControlSheetDraft => ({
  ...(controlSheet || {}),
  change_time_start: asText(primaryValues.scheduledStart),
  change_time_end: asText(primaryValues.scheduledEnd),
  device_ips: splitIps(primaryValues.targetIps).join('\n'),
  rollback_plan: asText(primaryValues.rollbackPlan),
}) as ControlSheetDraft;
