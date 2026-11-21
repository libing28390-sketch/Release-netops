import { describe, expect, it } from 'vitest';
import {
  buildPlaybookMarkdownReport,
  classifyCommandBlock,
  parseStructuredInspectionOutput,
} from './playbookOutputParser';

describe('playbookOutputParser', () => {
  it('parses Linux one-click structured metrics and findings', () => {
    const sample = [
      '主机名: devops | 系统: Ubuntu 24.04.4 LTS | 内核: 6.8.0-101-generic',
      'CPU核数: 2 | 运行天数: 0 天 | 综合评级: FAIL',
      '巡检结论:  [FAIL] RO_MOUNTS=1',
      '--- STRUCTURED_METRICS ---',
      'OVERALL_STATUS=FAIL',
      'CPU_UTIL=12.70',
      'MEM_UTIL=37.95',
      'DISK_UTIL=65',
      'RO_MOUNTS=1',
      'NTP_STATE=NA',
    ].join('\n');

    const parsed = parseStructuredInspectionOutput(sample);
    expect(parsed.hasStructuredData).toBe(true);
    expect(parsed.overallStatus).toBe('FAIL');
    expect(parsed.hostMeta.length).toBeGreaterThanOrEqual(3);
    expect(parsed.findings).toEqual([{ severity: 'FAIL', text: 'RO_MOUNTS=1' }]);
    const ro = parsed.metrics.find((m) => m.key === 'RO_MOUNTS');
    expect(ro?.tone).toBe('fail');
    const cpu = parsed.metrics.find((m) => m.key === 'CPU_UTIL');
    expect(cpu?.tone).toBe('ok');
    expect(cpu?.unit).toBe('%');
  });

  it('extracts headline KPIs from H3C Comware CLI output', () => {
    const sample = [
      '# display version',
      'H3C Comware Software, Version 7.1.064, Alpha 7165',
      'H3C WX5540H-HCL uptime is 0 weeks, 1 day, 10 hours, 54 minutes',
      '# display cpu-usage',
      '      23% in last 1 minute',
      '# display memory',
      'Mem:        770180    359804    410376         0      2992    155396       53.6%',
    ].join('\n');

    const parsed = parseStructuredInspectionOutput(sample);
    expect(parsed.hasStructuredData).toBe(true);
    expect(parsed.overallStatus).toBe('PASS');
    expect(parsed.metrics.find((m) => m.key === 'CPU_UTIL')?.value).toBe('23');
    expect(parsed.metrics.find((m) => m.key === 'MEM_UTIL')?.value).toBe('46.4');
  });

  it('classifies command blocks and generates markdown report', () => {
    expect(classifyCommandBlock('display fan', 'Fan 1: Fault')).toBe('fail');
    expect(classifyCommandBlock('display version', 'H3C Comware Software')).toBe('ok');

    const summary = parseStructuredInspectionOutput('--- STRUCTURED_METRICS ---\nOVERALL_STATUS=PASS\nCPU_UTIL=10\n');
    const md = buildPlaybookMarkdownReport({
      taskName: '实测_Linux一键深度巡检',
      hostname: 'ubuntu-nexora',
      ipAddress: '192.168.204.128',
      platform: 'ubuntu',
      status: 'success',
      summary,
      blocks: [{ command: 'oneclick_server_inspect', output: 'OK' }],
      zh: true,
    });
    expect(md).toContain('# 巡检执行报告: 实测_Linux一键深度巡检');
    expect(md).toContain('| CPU 使用率 | 10% | OK |');
  });
});
