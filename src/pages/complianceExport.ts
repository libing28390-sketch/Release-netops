import type { ComplianceFinding } from '../types';
import type { TableExportData } from '../components/ui/TableExportMenu';

export type ComplianceExportFinding = ComplianceFinding & {
  site?: string | null;
  last_seen_at?: string | null;
};

const display = (value: unknown) => value === null || value === undefined || value === '' ? '—' : String(value);

export function buildComplianceExportData(
  findings: ComplianceExportFinding[],
  language: string,
): TableExportData {
  const zh = language === 'zh';
  return {
    headers: zh
      ? ['规则名称', '规则编号', '主机名', '管理 IP', '站点', '级别', '分类', '状态', '最近出现']
      : ['Rule', 'Rule Code', 'Hostname', 'Management IP', 'Site', 'Severity', 'Category', 'Status', 'Last Seen'],
    rows: findings.map((finding) => {
      const lastSeen = finding.last_seen_at || finding.last_seen;
      return [
        display(finding.title),
        display(finding.rule_id),
        display(finding.hostname),
        display(finding.ip_address),
        display(finding.site),
        display(finding.severity),
        display(finding.category),
        display(finding.status),
        lastSeen ? new Date(lastSeen).toLocaleString() : '—',
      ];
    }),
  };
}
