import { describe, expect, it } from 'vitest';
import {
  getControlSheetMirrorConflicts,
  synchronizeControlSheetMirrors,
  type ControlSheetDraft,
} from './controlSheetSync';

const primaryValues = {
  scheduledStart: '2026-10-24T09:30',
  scheduledEnd: '2026-10-24T10:30',
  targetIps: ['10.0.0.1', '10.0.0.2'],
  rollbackPlan: 'Restore the previous configuration.',
};

const emptyDraft: ControlSheetDraft = {
  change_time_start: '',
  change_time_end: '',
  implementer_id: '',
  implementer_username: '',
  co_reviewer_id: '',
  co_reviewer_username: '',
  device_ips: '',
  pre_check: '',
  execution: '',
  post_verify: '',
  business_verify: '',
  rollback_plan: '',
};

describe('control sheet mirror synchronization', () => {
  it('reports conflicts for the three mirrored fields with readable values', () => {
    const conflicts = getControlSheetMirrorConflicts({
      ...emptyDraft,
      change_time_start: '2026-10-24 08:30:00',
      change_time_end: '2026-10-24 10:30:00',
      device_ips: '10.0.0.3, 10.0.0.1',
      rollback_plan: 'Keep the old configuration.',
    }, primaryValues);

    expect(conflicts.map((conflict) => conflict.field)).toEqual([
      'change_time',
      'device_ips',
      'rollback_plan',
    ]);
    expect(conflicts).toEqual([
      {
        field: 'change_time',
        label: '变更时间窗口',
        existingValue: '2026-10-24 08:30:00 – 2026-10-24 10:30:00',
        primaryValue: '2026-10-24T09:30 – 2026-10-24T10:30',
      },
      {
        field: 'device_ips',
        label: '涉及设备 IP',
        existingValue: '10.0.0.3, 10.0.0.1',
        primaryValue: '10.0.0.1, 10.0.0.2',
      },
      {
        field: 'rollback_plan',
        label: '回退方案',
        existingValue: 'Keep the old configuration.',
        primaryValue: 'Restore the previous configuration.',
      },
    ]);
  });

  it('treats alternate date separators, second precision, and IP ordering as equivalent', () => {
    const conflicts = getControlSheetMirrorConflicts({
      ...emptyDraft,
      change_time_start: '2026-10-24 09:30:59',
      change_time_end: '2026-10-24 10:30:00',
      device_ips: '10.0.0.2\n10.0.0.1,10.0.0.1',
      rollback_plan: 'Restore the previous configuration.',
    }, primaryValues);

    expect(conflicts).toEqual([]);
  });

  it('synchronizes only mirror fields and preserves the other control sheet values', () => {
    const original = {
      ...emptyDraft,
      implementer_id: '12',
      implementer_username: 'operator',
      co_reviewer_id: '34',
      co_reviewer_username: 'reviewer',
      pre_check: 'Check current routes.',
      execution: 'Manually apply the approved steps.',
      post_verify: 'Check route convergence.',
      business_verify: 'Confirm the service works.',
    };

    expect(synchronizeControlSheetMirrors(original, primaryValues)).toEqual({
      ...original,
      change_time_start: primaryValues.scheduledStart,
      change_time_end: primaryValues.scheduledEnd,
      device_ips: '10.0.0.1\n10.0.0.2',
      rollback_plan: primaryValues.rollbackPlan,
    });
  });

  it('does not report conflicts for empty legacy mirrors and synchronizes the rollback plan', () => {
    expect(getControlSheetMirrorConflicts(emptyDraft, primaryValues)).toEqual([]);

    expect(synchronizeControlSheetMirrors(emptyDraft, primaryValues)).toMatchObject({
      change_time_start: primaryValues.scheduledStart,
      change_time_end: primaryValues.scheduledEnd,
      device_ips: '10.0.0.1\n10.0.0.2',
      rollback_plan: primaryValues.rollbackPlan,
    });
  });

  it('normalizes rollback line endings and surrounding whitespace before comparing', () => {
    expect(getControlSheetMirrorConflicts({
      ...emptyDraft,
      rollback_plan: '  Restore the previous configuration.\r\n  ',
    }, primaryValues)).toEqual([]);
  });
});
