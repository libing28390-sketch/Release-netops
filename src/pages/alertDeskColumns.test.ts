import { describe, expect, it } from 'vitest';
import {
  ALERT_DESK_COLUMN_DEFS,
  ALERT_DESK_COLUMN_STORAGE_KEY,
  defaultAlertDeskColumnVisibility,
  loadAlertDeskColumnVisibility,
  normalizeAlertDeskColumnVisibility,
  setAlertDeskColumnVisibility,
} from './alertDeskColumns';

describe('alert desk columns', () => {
  it('defaults to the key incident-handling columns and hides secondary details', () => {
    const columns = defaultAlertDeskColumnVisibility();

    expect(columns).toMatchObject({ title: true, hostname: true, ipAddress: true, severity: true, workflow: true, assignee: true });
    expect(columns).toMatchObject({ metricType: false, occurrences: false, interface: false, site: false });
  });

  it('loads saved choices while filling fields added in a later version from defaults', () => {
    const storage = {
      getItem: (key: string) => key === ALERT_DESK_COLUMN_STORAGE_KEY ? JSON.stringify({ title: false, message: true }) : null,
      setItem: () => undefined,
    };

    expect(loadAlertDeskColumnVisibility(storage)).toMatchObject({ title: false, message: true, hostname: true, metricType: false });
  });

  it('keeps at least one data column visible', () => {
    const onlyTitle = normalizeAlertDeskColumnVisibility(Object.fromEntries(
      ALERT_DESK_COLUMN_DEFS.map(({ key }) => [key, key === 'title']),
    ));

    expect(setAlertDeskColumnVisibility(onlyTitle, 'title', false)).toBe(onlyTitle);
    expect(setAlertDeskColumnVisibility(onlyTitle, 'hostname', true).hostname).toBe(true);
  });
});
