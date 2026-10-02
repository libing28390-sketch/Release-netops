import type { TableExportData } from '../components/ui/TableExportMenu';

export interface BackupRunExportRecord {
  id?: string;
  trigger?: string | null;
  author?: string | null;
  status?: string | null;
  started_at?: string | null;
  total_devices?: number | null;
  success_count?: number | null;
  failed_count?: number | null;
  skipped_count?: number | null;
  site_summary?: Array<{
    site: string;
    success: number;
    failed: number;
    skipped: number;
    unknown: number;
  }>;
}

export function buildBackupRunExportData(
  runs: BackupRunExportRecord[],
  language: string,
  formatTime: (value: string) => string,
): TableExportData {
  const zh = language === 'zh';
  const siteDetails = (run: BackupRunExportRecord) => run.site_summary || [];
  const statusLabel = (run: BackupRunExportRecord) => {
    const failed = Number(run.failed_count || 0);
    const unknown = siteDetails(run).reduce((sum, site) => sum + Number(site.unknown || 0), 0);
    const status = String(run.status || '').toLowerCase();
    return status === 'completed' && failed === 0 && unknown === 0
      ? (zh ? '成功' : 'Success')
      : status === 'partial' || failed > 0 || unknown > 0
        ? (zh ? '需关注' : 'Attention')
        : status || '--';
  };

  return {
    headers: zh
      ? ['开始时间', '触发方式', '执行人', '站点', '站点结果', '状态', '成功设备数', '失败设备数', '未知设备数', '跳过设备数', '设备总数']
      : ['Started', 'Trigger', 'Operator', 'Sites', 'Site Results', 'Status', 'Successful Devices', 'Failed Devices', 'Unknown Devices', 'Skipped Devices', 'Total Devices'],
    rows: runs.map((run) => {
      const sites = siteDetails(run);
      const siteResults = sites.map((site) => {
        const attention = Number(site.failed || 0) + Number(site.unknown || 0);
        return attention > 0
          ? `${zh ? '异常' : 'Attention'} ${attention}`
          : `${zh ? '成功' : 'Success'} ${site.success}`;
      });
      return [
        formatTime(run.started_at || ''),
        run.trigger || '--',
        run.author || '--',
        sites.map((site) => site.site).join(', ') || '--',
        siteResults.join('; ') || '--',
        statusLabel(run),
        Number(run.success_count || 0),
        Number(run.failed_count || 0),
        sites.reduce((sum, site) => sum + Number(site.unknown || 0), 0),
        Number(run.skipped_count || 0),
        Number(run.total_devices || 0),
      ];
    }),
  };
}
