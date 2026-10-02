import { describe, expect, it } from 'vitest';
import { readExplicitTableData } from '../../ui/TableExportMenu';
import { buildMetricProfileExportData, type MetricOidProfile } from './MetricProfileList';
import type { ModelPresetItem } from '../PresetProfilesModal';

const profile = (index: number, overrides: Partial<MetricOidProfile> = {}): MetricOidProfile => ({
  profile_id: `internal-profile-${index}`,
  vendor: 'Cisco',
  model: `C2960-${index}`,
  cpu_oid: '1.3.6.1.4.1.9.1.1',
  memory_oid: '1.3.6.1.4.1.9.1.2',
  configured: true,
  verification_status: 'verified',
  device_count: 0,
  platforms: ['cisco_ios'],
  metric_keys: ['cpu', 'memory'],
  ...overrides,
});

describe('SNMP metric profile export', () => {
  it('keeps visible profile attributes in separate columns and exports every filtered row', () => {
    const data = buildMetricProfileExportData(
      Array.from({ length: 25 }, (_, index) => profile(index, {
        model_pattern: `C2960-.*-${index}`,
        software_version_scope: [`15.${index}`],
      })),
      [],
      { vendorFilter: 'Cisco', statusFilter: 'verified', activeTab: 'custom', search: '2960', zh: true },
    );
    const normalized = readExplicitTableData(data);

    expect(normalized.headers).toEqual(['厂商', '模板来源', '分类', '型号', '型号匹配模式', '平台', '软件版本范围', '采集指标']);
    expect(normalized.rows).toHaveLength(25);
    expect(normalized.rows[0]).toEqual(['Cisco', '自定义模板', '-', 'C2960-0', 'C2960-.*-0', 'cisco_ios', '15.0', 'CPU 使用率, 内存使用率']);
    expect(normalized.rows[0].join(' ')).not.toContain('internal-profile');
  });

  it('keeps preset vendor, category, model, platform, and versions distinct', () => {
    const presets: ModelPresetItem[] = [
      { family_id: 'family-1', vendor: 'Cisco', model: 'C9200-24T', category: 'Campus Switch', description: '', metric_definitions: { cpu: {}, memory: {} }, platforms: ['cisco_ios'], model_pattern: 'C9200-.*', software_version_scope: ['17.9'] },
      { family_id: 'family-1', vendor: 'Cisco', model: 'C9200-48T', category: 'Campus Switch', description: '', metric_definitions: { cpu: {}, memory: {} }, platforms: ['cisco_ios'], model_pattern: 'C9200-.*', software_version_scope: ['17.9'] },
    ];

    const normalized = readExplicitTableData(buildMetricProfileExportData(
      [], presets,
      { vendorFilter: '', statusFilter: 'all', activeTab: 'presets', search: 'C9200', zh: true },
    ));

    expect(normalized.headers).toEqual(['厂商', '模板来源', '分类', '型号', '型号匹配模式', '平台', '软件版本范围', '采集指标']);
    expect(normalized.rows).toEqual([['思科', '官方预置', '园区网交换机', 'C9200-24T, C9200-48T', 'C9200-.*', 'cisco_ios', '17.9', 'CPU 使用率, 内存使用率']]);
  });
});
