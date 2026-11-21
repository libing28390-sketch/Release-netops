export type MetricTone = 'ok' | 'warn' | 'fail' | 'neutral';

export interface StructuredMetricItem {
  key: string;
  labelZh: string;
  labelEn: string;
  value: string;
  unit?: string;
  tone: MetricTone;
}

export interface StructuredFinding {
  severity: 'FAIL' | 'WARN' | 'PASS';
  text: string;
}

export interface ParsedInspectionSummary {
  hasStructuredData: boolean;
  overallStatus: 'PASS' | 'WARN' | 'FAIL' | 'UNKNOWN';
  hostMeta: { labelZh: string; labelEn: string; value: string }[];
  metrics: StructuredMetricItem[];
  findings: StructuredFinding[];
}

const METRIC_META: Record<
  string,
  { labelZh: string; labelEn: string; unit?: string; warnAt?: number; failAt?: number; zeroOnly?: boolean }
> = {
  CPU_UTIL: { labelZh: 'CPU 使用率', labelEn: 'CPU Usage', unit: '%', warnAt: 80, failAt: 92 },
  MEM_UTIL: { labelZh: '内存使用率', labelEn: 'Memory Usage', unit: '%', warnAt: 85, failAt: 95 },
  DISK_UTIL: { labelZh: '磁盘最大占用', labelEn: 'Max Disk Usage', unit: '%', warnAt: 80, failAt: 90 },
  INODE_UTIL: { labelZh: 'Inode 最大占用', labelEn: 'Max Inode Usage', unit: '%', warnAt: 80, failAt: 90 },
  IOWAIT: { labelZh: 'IO Wait', labelEn: 'IO Wait', unit: '%', warnAt: 15, failAt: 30 },
  RO_MOUNTS: { labelZh: '只读挂载', labelEn: 'RO Mounts', zeroOnly: true },
  ZOMBIE_PROCS: { labelZh: '僵尸进程', labelEn: 'Zombie Procs', warnAt: 5, failAt: 20 },
  OOM_24H: { labelZh: '24h OOM', labelEn: '24h OOM', zeroOnly: true },
  TCP_ESTAB: { labelZh: 'TCP 活跃连接', labelEn: 'TCP Established' },
  TCP_CLOSE_WAIT: { labelZh: 'CLOSE_WAIT', labelEn: 'CLOSE_WAIT', warnAt: 100, failAt: 500 },
  NET_ERR_DELTA: { labelZh: '网卡错/丢包', labelEn: 'NIC Err/Drop', warnAt: 1, failAt: 50 },
  CORE_DUMPS: { labelZh: 'CoreDump', labelEn: 'Core Dumps', warnAt: 1, failAt: 5 },
  NTP_STATE: { labelZh: 'NTP 同步', labelEn: 'NTP Sync' },
};

function evaluateMetricTone(key: string, rawVal: string): MetricTone {
  const meta = METRIC_META[key];
  const val = rawVal.trim();
  if (!val || val === 'NA' || val === 'N/A' || val === '--') return 'neutral';
  const num = Number(val.replace(/%$/, ''));
  if (key === 'NTP_STATE') {
    const lower = val.toLowerCase();
    if (lower === 'yes' || lower === 'synced' || lower === 'ok' || lower === 'normal') return 'ok';
    if (lower === 'no' || lower === 'unsynced' || lower === 'fail') return 'warn';
    return 'neutral';
  }
  if (!Number.isNaN(num) && meta) {
    if (meta.zeroOnly) return num > 0 ? 'fail' : 'ok';
    if (meta.failAt !== undefined && num >= meta.failAt) return 'fail';
    if (meta.warnAt !== undefined && num >= meta.warnAt) return 'warn';
    return 'ok';
  }
  return 'neutral';
}

export function classifyCommandBlock(command: string, output: string): 'ok' | 'warn' | 'fail' {
  const text = String(output || '');
  const lower = text.toLowerCase();
  if (
    text.includes('__ERROR__') ||
    text.includes('% Unrecognized') ||
    text.includes('% Invalid input') ||
    text.includes('Authentication failed') ||
    /\bCRITICAL\b/.test(text) ||
    /\[FAIL\]/.test(text) ||
    /\bOVERALL_STATUS=FAIL\b/.test(text)
  ) {
    return 'fail';
  }
  const cmdLower = String(command || '').toLowerCase();
  if (/(fan|power|environment|alarm)/.test(cmdLower)) {
    if (/\b(fault|failed|abnormal|alarm)\b/i.test(text)) return 'fail';
  }
  if (/\bWARNING\b/.test(text) || /\[WARN\]/.test(text) || /\bOVERALL_STATUS=WARN\b/.test(text) || lower.includes('traceback')) {
    return 'warn';
  }
  return 'ok';
}

export function parseStructuredInspectionOutput(rawOutput: string): ParsedInspectionSummary {
  const text = String(rawOutput || '');
  const metrics: StructuredMetricItem[] = [];
  const findings: StructuredFinding[] = [];
  const hostMeta: { labelZh: string; labelEn: string; value: string }[] = [];
  let overallStatus: 'PASS' | 'WARN' | 'FAIL' | 'UNKNOWN' = 'UNKNOWN';

  // 1. Extract Linux one-click host header metadata
  const hostLine = text.match(/主机名:\s*([^|\r\n]+)\|\s*系统:\s*([^|\r\n]+)\|\s*内核:\s*([^\r\n]+)/);
  if (hostLine) {
    hostMeta.push(
      { labelZh: '主机名', labelEn: 'Hostname', value: hostLine[1].trim() },
      { labelZh: '操作系统', labelEn: 'OS', value: hostLine[2].trim() },
      { labelZh: '内核', labelEn: 'Kernel', value: hostLine[3].trim() },
    );
  }
  const uptimeLine = text.match(/CPU核数:\s*([^|\r\n]+)\|\s*运行天数:\s*([^|\r\n]+)/);
  if (uptimeLine) {
    hostMeta.push(
      { labelZh: 'CPU 核数', labelEn: 'CPU Cores', value: uptimeLine[1].trim() },
      { labelZh: '运行时长', labelEn: 'Uptime', value: uptimeLine[2].trim() },
    );
  }

  // 2. Extract [FAIL] / [WARN] / [PASS] findings
  const findingMatches = text.matchAll(/\[(FAIL|WARN|PASS)\]\s*([^\r\n|]+)/g);
  for (const m of findingMatches) {
    const sev = m[1] as 'FAIL' | 'WARN' | 'PASS';
    const detail = m[2].trim();
    if (detail) findings.push({ severity: sev, text: detail });
  }

  // 3. Parse --- STRUCTURED_METRICS --- block
  const smIdx = text.indexOf('--- STRUCTURED_METRICS ---');
  if (smIdx >= 0) {
    const section = text.slice(smIdx + '--- STRUCTURED_METRICS ---'.length);
    for (const rawLine of section.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line || line.startsWith('---')) continue;
      const eq = line.indexOf('=');
      if (eq <= 0) continue;
      const key = line.slice(0, eq).trim();
      const val = line.slice(eq + 1).trim();
      if (key === 'OVERALL_STATUS') {
        const up = val.toUpperCase();
        if (up === 'PASS' || up === 'WARN' || up === 'FAIL') overallStatus = up;
        continue;
      }
      const meta = METRIC_META[key];
      metrics.push({
        key,
        labelZh: meta?.labelZh || key,
        labelEn: meta?.labelEn || key,
        value: val,
        unit: meta?.unit && val !== 'NA' && val !== 'N/A' ? meta.unit : undefined,
        tone: evaluateMetricTone(key, val),
      });
    }
  }

  // 4. Lightweight CLI KPI extraction for network devices (H3C / Huawei / Cisco)
  if (metrics.length === 0) {
    const uptimeMatch = text.match(/uptime is\s+([^\r\n]+)/i);
    if (uptimeMatch) {
      hostMeta.push({ labelZh: '运行时长', labelEn: 'Uptime', value: uptimeMatch[1].trim() });
    }
    const verMatch = text.match(/(?:H3C Comware Software|Huawei Versatile Routing Platform|Cisco IOS)[^\r\n]*/i);
    if (verMatch) {
      hostMeta.push({ labelZh: '系统版本', labelEn: 'Version', value: verMatch[0].trim() });
    }
    const cpu1m = text.match(/(\d+(?:\.\d+)?)%\s+in last 1 minute/i) || text.match(/CPU utilization for five seconds:[^;]*;\s*one minute:\s*(\d+)%/i);
    if (cpu1m) {
      const val = cpu1m[1];
      metrics.push({
        key: 'CPU_UTIL',
        labelZh: 'CPU (1分钟)',
        labelEn: 'CPU (1m)',
        value: val,
        unit: '%',
        tone: evaluateMetricTone('CPU_UTIL', val),
      });
    }
    const memFree = text.match(/Mem:\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+(\d+(?:\.\d+)?)%/i);
    if (memFree) {
      const freePct = Number(memFree[1]);
      if (!Number.isNaN(freePct)) {
        const usedPct = Math.max(0, Math.min(100, +(100 - freePct).toFixed(1)));
        metrics.push({
          key: 'MEM_UTIL',
          labelZh: '内存使用率',
          labelEn: 'Memory Usage',
          value: String(usedPct),
          unit: '%',
          tone: evaluateMetricTone('MEM_UTIL', String(usedPct)),
        });
      }
    }
    const tempMatches = [...text.matchAll(/(?:Inflow|Outflow|Hotspot|Sensor)\s+\d+\s+(\d+)\s+\d+\s+(\d+)\s+(\d+)/gi)];
    if (tempMatches.length > 0) {
      const maxTemp = Math.max(...tempMatches.map((m) => Number(m[1])));
      const warnLimit = Math.min(...tempMatches.map((m) => Number(m[2])));
      const alarmLimit = Math.min(...tempMatches.map((m) => Number(m[3])));
      metrics.push({
        key: 'TEMPERATURE',
        labelZh: '最高温度',
        labelEn: 'Max Temp',
        value: String(maxTemp),
        unit: '°C',
        tone: maxTemp >= alarmLimit ? 'fail' : maxTemp >= warnLimit ? 'warn' : 'ok',
      });
    }
  }

  // Sort findings: FAIL first, then WARN, then PASS
  const order = { FAIL: 0, WARN: 1, PASS: 2 };
  findings.sort((a, b) => order[a.severity] - order[b.severity]);

  if (overallStatus === 'UNKNOWN') {
    if (findings.some((f) => f.severity === 'FAIL') || metrics.some((m) => m.tone === 'fail')) {
      overallStatus = 'FAIL';
    } else if (findings.some((f) => f.severity === 'WARN') || metrics.some((m) => m.tone === 'warn')) {
      overallStatus = 'WARN';
    } else if (metrics.length > 0 || findings.length > 0) {
      overallStatus = 'PASS';
    }
  }

  return {
    hasStructuredData: metrics.length > 0 || findings.length > 0 || hostMeta.length > 0,
    overallStatus,
    hostMeta,
    metrics,
    findings,
  };
}

export function buildPlaybookMarkdownReport(params: {
  taskName: string;
  hostname: string;
  ipAddress: string;
  platform?: string;
  status: string;
  startedAt?: string;
  summary: ParsedInspectionSummary;
  blocks: { command: string; output: string }[];
  zh: boolean;
}): string {
  const { taskName, hostname, ipAddress, platform, status, startedAt, summary, blocks, zh } = params;
  const lines: string[] = [
    `# ${zh ? '巡检执行报告' : 'Inspection Execution Report'}: ${taskName || hostname}`,
    '',
    `- **${zh ? '目标设备' : 'Device'}**: ${hostname} (\`${ipAddress || '-'}\`)`,
    `- **${zh ? '平台' : 'Platform'}**: ${platform || '-'}`,
    `- **${zh ? '执行状态' : 'Status'}**: ${status}`,
    `- **${zh ? '执行时间' : 'Executed At'}**: ${startedAt || new Date().toISOString()}`,
    `- **${zh ? '健康结论' : 'Health Rating'}**: ${summary.overallStatus}`,
    '',
  ];

  if (summary.findings.length > 0) {
    lines.push(`## ${zh ? '关键巡检结论' : 'Key Findings'}`, '');
    for (const f of summary.findings) {
      lines.push(`- **[${f.severity}]** ${f.text}`);
    }
    lines.push('');
  }

  if (summary.metrics.length > 0) {
    lines.push(`## ${zh ? '核心指标摘要' : 'Key Metrics'}`, '');
    lines.push(`| ${zh ? '指标' : 'Metric'} | ${zh ? '当前值' : 'Value'} | ${zh ? '状态' : 'Status'} |`);
    lines.push('| :--- | :--- | :--- |');
    for (const m of summary.metrics) {
      const label = zh ? m.labelZh : m.labelEn;
      const val = `${m.value}${m.unit || ''}`;
      lines.push(`| ${label} | ${val} | ${m.tone.toUpperCase()} |`);
    }
    lines.push('');
  }

  lines.push(`## ${zh ? '命令原始回显' : 'Command Outputs'}`, '');
  for (const blk of blocks) {
    lines.push(`### \`${blk.command || 'system'}\``, '', '```text', blk.output || '', '```', '');
  }

  return lines.join('\n');
}

export function triggerTextDownload(content: string, filename: string, mimeType = 'text/plain;charset=utf-8'): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
