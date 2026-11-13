import type { TableExportData } from '../components/ui/TableExportMenu';

export type MonitoringReportTab = 'interfaces' | 'devices' | 'outbound';

const unavailable = '—';

const asNumber = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};

const metric = (value: unknown, suffix = '', decimals = 1): string => {
  const number = asNumber(value);
  return number === null ? unavailable : `${number.toFixed(decimals)}${suffix}`;
};

const sampleTime = (value: unknown, language: 'zh' | 'en'): string => {
  if (typeof value !== 'string' || !value) return unavailable;
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? value : timestamp.toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US');
};

const qualityFor = (item: Record<string, any>, noValidSample: boolean, zh: boolean): string =>
  String(item.sample_quality || (noValidSample ? 'NO_DATA' : (zh ? '采样质量未知' : 'Sample quality unknown'))).toUpperCase();

export function buildMonitoringReportExportData(
  items: Array<Record<string, any>>,
  tab: MonitoringReportTab,
  language: 'zh' | 'en',
): TableExportData {
  const zh = language === 'zh';

  if (tab === 'interfaces') {
    return {
      headers: zh
        ? ['设备名称', '厂商', '管理 IP', '站点', '角色', '接口名称', '接口描述', '运行状态', '物理速率', '入方向流量', '出方向流量', '峰值带宽利用率', '错误包', '预警等级', '处置建议', '采样质量', '采样时间']
        : ['Device name', 'Vendor', 'Management IP', 'Site', 'Role', 'Interface', 'Description', 'Oper status', 'Physical speed', 'Inbound traffic', 'Outbound traffic', 'Peak bandwidth utilization', 'Errors', 'Alert level', 'Advice', 'Sample quality', 'Sample time'],
      rows: items.map((item) => {
        const maxUtil = asNumber(item.max_util);
        const noValidSample = String(item.sample_quality || '').toUpperCase() === 'NO_DATA'
          || String(item.risk_level || '').toUpperCase() === 'NO_DATA'
          || maxUtil === null;
        const level = noValidSample ? 'NO_DATA' : item.alert_level === 'CRITICAL'
          ? (zh ? '严重' : 'Critical')
          : item.alert_level === 'WARNING' ? (zh ? '预警' : 'Warning') : '';
        return [
          item.hostname || '', item.vendor || '', item.ip_address || '', item.site_name || '', item.role || '',
          item.interface_name || '', item.description || '', item.oper_status || '', item.speed_str ?? unavailable,
          item.in_bps_str ?? unavailable, item.out_bps_str ?? unavailable,
          maxUtil === null ? unavailable : `${maxUtil.toFixed(1)}%`,
          Number(item.total_errors || 0).toFixed(0), level,
          noValidSample ? (zh ? '无有效采样，暂不可评估' : 'No valid sample; assessment unavailable') : (item.advice || ''),
          qualityFor(item, noValidSample, zh), sampleTime(item.sample_time, language),
        ];
      }),
    };
  }

  if (tab === 'devices') {
    return {
      headers: zh
        ? ['设备名称', '管理 IP', '厂商', '平台', '站点', '角色', '在线状态', 'CPU 使用率', '内存利用率', '运行温度', '风险等级', '评估建议', '采样质量', '采样时间']
        : ['Hostname', 'Management IP', 'Vendor', 'Platform', 'Site', 'Role', 'Online status', 'CPU usage', 'Memory usage', 'Temperature', 'Risk level', 'Assessment advice', 'Sample quality', 'Sample time'],
      rows: items.map((item) => {
        const cpu = asNumber(item.cpu_usage);
        const mem = asNumber(item.memory_usage);
        const noValidSample = String(item.sample_quality || '').toUpperCase() === 'NO_DATA'
          || String(item.risk_level || '').toUpperCase() === 'NO_DATA'
          || (cpu === null && mem === null);
        return [
          item.hostname || '', item.ip_address || '', item.vendor || '', item.platform || '', item.site_name || '', item.role || '',
          item.status || '', metric(cpu, '%'), metric(mem, '%'), item.temperature_str ?? unavailable,
          noValidSample ? 'NO_DATA' : (item.risk_level || (zh ? '正常' : 'Normal')),
          noValidSample ? (zh ? '无有效采样，暂不可评估' : 'No valid sample; assessment unavailable') : (item.advice || ''),
          qualityFor(item, noValidSample, zh), sampleTime(item.sample_time, language),
        ];
      }),
    };
  }

  return {
    headers: zh
      ? ['探针名称', '运营商', '探测地址', '协议类型', '启用状态', '实时延迟', '丢包率', '链路健康等级']
      : ['Probe name', 'ISP', 'Target address', 'Protocol', 'Active status', 'Latency', 'Packet loss', 'Link health'],
    rows: items.map((item) => [
      item.name || '', item.isp || '', item.target || '', item.target_type || '', item.active_str || '',
      metric(item.latency_ms, ' ms'), metric(item.packet_loss, '%'), item.health_grade ?? unavailable,
    ]),
  };
}
