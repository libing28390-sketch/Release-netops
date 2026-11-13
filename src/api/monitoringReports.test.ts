import { describe, expect, it } from 'vitest';
import { monitoringReportExportEndpoints } from './monitoringReports';

describe('monitoring report export endpoints', () => {
  it('uses the registered monitoring API routes for every report preset', () => {
    expect(monitoringReportExportEndpoints).toEqual({
      interfaces: '/api/monitoring/export/interfaces',
      devices: '/api/monitoring/export/devices',
      outbound: '/api/monitoring/export/outbound',
    });
  });
});
