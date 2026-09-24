import React, { useState } from 'react';
import {
  X,
  FileSpreadsheet,
  Download,
  CheckCircle2,
  AlertCircle,
  HelpCircle,
  ExternalLink,
  Table,
  Layers,
  Activity,
  Server,
  Globe,
  FileText,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { useEscapeClose } from '../hooks/useEscapeClose';

interface ExportTableModalProps {
  isOpen: boolean;
  onClose: () => void;
  language: 'zh' | 'en';
  currentDashboardUid?: string;
}

interface ReportPreset {
  id: string;
  titleZh: string;
  titleEn: string;
  descZh: string;
  descEn: string;
  icon: React.ComponentType<any>;
  badgeZh: string;
  badgeEn: string;
  sheetsZh: string[];
  sheetsEn: string[];
  endpoint: string;
  recommendedFormat: 'xlsx' | 'csv';
}

const REPORT_PRESETS: ReportPreset[] = [
  {
    id: 'interfaces',
    titleZh: '全网接口流量与利用率报表',
    titleEn: 'Network Interface Traffic & Utilization Report',
    descZh: '结合 CMDB 设备元数据与 VictoriaMetrics 5m 时序流量，多工作表汇总接口速率、利用率与错包排行',
    descEn: 'Combines CMDB metadata with VM traffic rates, multi-sheet workbook covering rates, utilization and discards',
    icon: Activity,
    badgeZh: '4 个专业工作表',
    badgeEn: '4 Sheets Included',
    sheetsZh: [
      '工作表 1: 接口清单与状态 (设备/IP/厂商/角色/描述/UP/DOWN/速率)',
      '工作表 2: 流量与利用率统计 (入向/出向速率、带宽利用率、峰值排序)',
      '工作表 3: 高利用率预警接口 (超阈值接口智能筛查、预警评级与处置建议)',
      '工作表 4: 接口错误与丢弃排行 (CRC 错包率与 Discard 丢弃率排行)',
    ],
    sheetsEn: [
      'Sheet 1: Interfaces Inventory & Status (Device, IP, Vendor, OperStatus, Speed)',
      'Sheet 2: Traffic Rates & Bandwidth Utilization (In/Out bps, Utilization %, Max Util)',
      'Sheet 3: High Utilization Alert Ports (Threshold check, alert levels, action advice)',
      'Sheet 4: Interface Errors & Discards (CRC errors and packet discards ranking)',
    ],
    endpoint: '/api/monitoring/v1/export/interfaces',
    recommendedFormat: 'xlsx',
  },
  {
    id: 'devices',
    titleZh: '网络设备运行与资源负荷报表',
    titleEn: 'Network Devices Resource Health & Capacity Report',
    descZh: '全网交换机、路由器、防火墙 CPU、内存与温度多维指标聚合，包含设备高负荷风险清单',
    descEn: 'Aggregates switch/router/firewall CPU, memory and temperature metrics with high-load alert sheet',
    icon: Server,
    badgeZh: '2 个专业工作表',
    badgeEn: '2 Sheets Included',
    sheetsZh: [
      '工作表 1: 设备运行与资源清单 (设备名/IP/厂商/平台/角色/在线状态/CPU/内存/温度)',
      '工作表 2: 高负荷告警设备 Top N (CPU > 70% 或内存 > 75% 风险排查清单)',
    ],
    sheetsEn: [
      'Sheet 1: Device Resource Inventory (Hostname, IP, Vendor, Platform, CPU, Memory, Temp)',
      'Sheet 2: High-Load Warning Devices (CPU > 70% or Mem > 75% risk checklist)',
    ],
    endpoint: '/api/monitoring/v1/export/devices',
    recommendedFormat: 'xlsx',
  },
  {
    id: 'outbound',
    titleZh: '互联网出口与 WAN 链路运行报表',
    titleEn: 'Internet Outbound & WAN Health Report',
    descZh: '边界出口运营商对等链路、ICMP/HTTP 探针实时延迟、丢包率与可用性汇总',
    descEn: 'Border gateway ISP peering links, probe latency, packet loss and availability summary',
    icon: Globe,
    badgeZh: '出口链路与探针',
    badgeEn: 'Links & Probes',
    sheetsZh: [
      '工作表 1: 出口链路与探针状态 (探针名称/运营商/探测地址/实时延迟/丢包率/健康评级)',
    ],
    sheetsEn: [
      'Sheet 1: Outbound Links & Probes (Probe name, ISP, Target, Latency, Loss, Health)',
    ],
    endpoint: '/api/monitoring/v1/export/outbound',
    recommendedFormat: 'xlsx',
  },
];

export const ExportTableModal: React.FC<ExportTableModalProps> = ({
  isOpen,
  onClose,
  language,
}) => {
  const zh = language === 'zh';
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [showGrafanaGuide, setShowGrafanaGuide] = useState(false);

  useEscapeClose(isOpen, onClose);
  if (!isOpen) return null;

  const handleDownload = async (preset: ReportPreset, format: 'xlsx' | 'csv') => {
    const key = `${preset.id}-${format}`;
    setDownloadingId(key);
    setSuccessMessage(null);
    setErrorMessage(null);

    try {
      const token = localStorage.getItem('netops_token');
      const headers: Record<string, string> = {};
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const response = await fetch(`${preset.endpoint}?format=${format}`, {
        headers,
        credentials: 'same-origin',
      });

      if (!response.ok) {
        throw new Error(`Export failed with HTTP status ${response.status}`);
      }

      const blob = await response.blob();
      const contentDisposition = response.headers.get('Content-Disposition') || '';
      let filename = `${preset.id}_${new Date().toISOString().slice(0, 10)}.${format}`;
      const match = contentDisposition.match(/filename="?([^"]+)"?/);
      if (match && match[1]) {
        filename = match[1];
      }

      // Trigger browser download
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);

      setSuccessMessage(
        zh
          ? `已成功生成并下载报表：${filename}`
          : `Successfully exported and downloaded: ${filename}`
      );
    } catch (err: any) {
      setErrorMessage(
        zh
          ? `导出失败：${err?.message || '网络连接或服务端异常'}`
          : `Export error: ${err?.message || 'Network or server failure'}`
      );
    } finally {
      setDownloadingId(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs animate-in fade-in duration-200">
      <div className="relative flex flex-col w-full max-w-3xl max-h-[90vh] overflow-hidden rounded-3xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200/80 dark:border-zinc-800/80 px-6 py-4.5 bg-slate-50/70 dark:bg-zinc-900/70">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-cyan-600 text-white shadow-md shadow-cyan-600/20">
              <FileSpreadsheet size={20} />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-900 dark:text-zinc-100">
                {zh ? '监控报表与表格数据导出' : 'Monitoring Reports & Data Export'}
              </h3>
              <p className="text-xs text-slate-500 dark:text-zinc-400">
                {zh
                  ? '融合 CMDB 资产元数据与 VictoriaMetrics 时序指标，生成多工作表专业 XLSX / CSV 报表'
                  : 'Fuses CMDB assets with VictoriaMetrics timeseries into multi-sheet professional workbooks'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl p-1.5 text-slate-400 hover:text-slate-700 dark:hover:text-zinc-200 hover:bg-slate-100 dark:hover:bg-zinc-800 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Alerts */}
        {successMessage && (
          <div className="mx-6 mt-4 flex items-center gap-2 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800/50 px-3.5 py-2.5 text-xs text-emerald-800 dark:text-emerald-300">
            <CheckCircle2 size={16} className="text-emerald-600 shrink-0" />
            <span className="font-medium">{successMessage}</span>
          </div>
        )}
        {errorMessage && (
          <div className="mx-6 mt-4 flex items-center gap-2 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800/50 px-3.5 py-2.5 text-xs text-rose-800 dark:text-rose-300">
            <AlertCircle size={16} className="text-rose-600 shrink-0" />
            <span className="font-medium">{errorMessage}</span>
          </div>
        )}

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          <div className="text-xs font-semibold text-slate-500 dark:text-zinc-400 uppercase tracking-wider">
            {zh ? 'Nexora 官方权威报表生成（推荐）' : 'Official Authoritative Reports (Recommended)'}
          </div>

          <div className="space-y-3.5">
            {REPORT_PRESETS.map(preset => {
              const Icon = preset.icon;
              const isXlsxBusy = downloadingId === `${preset.id}-xlsx`;
              const isCsvBusy = downloadingId === `${preset.id}-csv`;
              const sheets = zh ? preset.sheetsZh : preset.sheetsEn;

              return (
                <div
                  key={preset.id}
                  className="rounded-2xl border border-slate-200/90 dark:border-zinc-800/90 bg-slate-50/40 dark:bg-zinc-800/20 p-4 transition-all hover:border-cyan-300 dark:hover:border-cyan-800 hover:shadow-sm"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="flex items-start gap-3">
                      <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-xl bg-white dark:bg-zinc-800 border border-slate-200 dark:border-zinc-700 text-cyan-600 dark:text-cyan-400 shadow-2xs">
                        <Icon size={18} />
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-bold text-slate-900 dark:text-zinc-100">
                            {zh ? preset.titleZh : preset.titleEn}
                          </span>
                          <span className="rounded-md bg-cyan-100 dark:bg-cyan-950/60 px-2 py-0.5 text-[10px] font-bold text-cyan-800 dark:text-cyan-300">
                            {zh ? preset.badgeZh : preset.badgeEn}
                          </span>
                        </div>
                        <p className="mt-1 text-xs text-slate-500 dark:text-zinc-400 leading-relaxed">
                          {zh ? preset.descZh : preset.descEn}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        type="button"
                        onClick={() => void handleDownload(preset, 'xlsx')}
                        disabled={Boolean(downloadingId)}
                        className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white px-3.5 py-1.5 text-xs font-bold shadow-xs transition-colors disabled:opacity-50 cursor-pointer"
                        title={zh ? '生成包含多工作表的专业 Excel 文件' : 'Export formatted multi-sheet Excel file'}
                      >
                        <FileSpreadsheet size={14} className={isXlsxBusy ? 'animate-spin' : ''} />
                        <span>{isXlsxBusy ? (zh ? '正在生成…' : 'Exporting…') : zh ? '导出 Excel (.xlsx)' : 'Export XLSX'}</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => void handleDownload(preset, 'csv')}
                        disabled={Boolean(downloadingId)}
                        className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 hover:bg-slate-50 dark:hover:bg-zinc-700 text-slate-700 dark:text-zinc-200 px-3 py-1.5 text-xs font-semibold shadow-2xs transition-colors disabled:opacity-50 cursor-pointer"
                        title={zh ? '导出带 UTF-8 BOM 的通用 CSV 文本' : 'Export standard CSV file with UTF-8 BOM'}
                      >
                        <Download size={13} className={isCsvBusy ? 'animate-spin' : ''} />
                        <span>{isCsvBusy ? (zh ? '生成中…' : 'Generating…') : 'CSV'}</span>
                      </button>
                    </div>
                  </div>

                  {/* Sheet breakdown details */}
                  <div className="mt-3 rounded-xl bg-white dark:bg-zinc-900 border border-slate-200/60 dark:border-zinc-800/60 p-2.5">
                    <div className="text-[11px] font-semibold text-slate-600 dark:text-zinc-300 mb-1.5">
                      {zh ? '工作表构成 (Sheets Layout)：' : 'Sheets included:'}
                    </div>
                    <ul className="space-y-1">
                      {sheets.map((sheet, sIdx) => (
                        <li key={sIdx} className="text-[11px] text-slate-500 dark:text-zinc-400 flex items-start gap-1.5">
                          <span className="text-cyan-600 font-bold shrink-0">•</span>
                          <span>{sheet}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Collapsible Grafana Native Guide */}
          <div className="mt-6 rounded-2xl border border-slate-200/80 dark:border-zinc-800/80 bg-cyan-50/40 dark:bg-cyan-950/20 p-4">
            <button
              type="button"
              onClick={() => setShowGrafanaGuide(!showGrafanaGuide)}
              className="flex w-full items-center justify-between text-left text-xs font-bold text-cyan-900 dark:text-cyan-200 cursor-pointer"
            >
              <div className="flex items-center gap-2">
                <HelpCircle size={15} className="text-cyan-600 dark:text-cyan-400" />
                <span>
                  {zh
                    ? '💡 如何在 Grafana 原生界面直接导出单个面板的数据？(临时排障)'
                    : '💡 How to export directly in native Grafana panels? (Ad-hoc troubleshooting)'}
                </span>
              </div>
              {showGrafanaGuide ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
            </button>

            {showGrafanaGuide && (
              <div className="mt-3 space-y-2 text-xs leading-relaxed text-slate-600 dark:text-zinc-300 border-t border-cyan-200/60 dark:border-cyan-800/50 pt-3">
                <p>
                  {zh
                    ? '若需临时提取某一个特定图表的全部原始点，可以直接使用 Grafana 12.1.0 原生的数据检查器导出：'
                    : 'If you want ad-hoc raw data from a specific panel, use Grafana 12.1.0 native inspect export:'}
                </p>
                <ol className="list-decimal list-inside space-y-1.5 pl-1 text-[11px] text-slate-700 dark:text-zinc-300 font-medium">
                  <li>
                    <span className="font-bold">{zh ? '切换视图模式' : 'Switch view mode'}</span>: {zh ? '在监控大盘顶部工具栏切换为“电视模式”或点击“在新窗口打开”。' : 'Switch to TV mode or click Open in New Tab.'}
                  </li>
                  <li>
                    <span className="font-bold">{zh ? '找到目标面板' : 'Locate panel'}</span>: {zh ? '鼠标悬停在需要导出的任意图表面板右上角。' : 'Hover over the top right corner of the target panel.'}
                  </li>
                  <li>
                    <span className="font-bold">{zh ? '打开检查抽屉' : 'Inspect panel'}</span>: {zh ? '点击三点菜单 ⋮ → 选择 Inspect (检查) → 切换到 Data (数据) 标签页。' : 'Click menu ⋮ → Inspect → Data tab.'}
                  </li>
                  <li>
                    <span className="font-bold">{zh ? '关键数据选项' : 'Key Data options'}</span>:
                    <ul className="list-disc list-inside pl-4 mt-0.5 space-y-0.5 text-slate-500 dark:text-zinc-400 font-normal">
                      <li><strong>Apply panel transformations</strong>: {zh ? '保留在面板中配置的列过滤和中文别名（如设备名称、端口号、利用率）。' : 'Applies column renames and drops.'}</li>
                      <li><strong>Formatted data</strong>: {zh ? '导出经过格式化后的值（保留 %、bps、ms 等单位）。' : 'Exports formatted numbers with units.'}</li>
                      <li><strong>Download for Excel</strong>: {zh ? '让导出的 CSV 文件与 Microsoft Excel 完全兼容。' : 'Optimizes CSV for Excel.'}</li>
                    </ul>
                  </li>
                  <li>
                    <span className="font-bold">{zh ? '点击下载' : 'Download'}</span>: {zh ? '点击 Download CSV 按钮，即刻保存到本地。' : 'Click Download CSV.'}
                  </li>
                </ol>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end border-t border-slate-200/80 dark:border-zinc-800/80 px-6 py-3.5 bg-slate-50/70 dark:bg-zinc-900/70">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-4 py-2 text-xs font-semibold text-slate-700 dark:text-zinc-200 hover:bg-slate-50 dark:hover:bg-zinc-700 transition-colors cursor-pointer"
          >
            {zh ? '关闭' : 'Close'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ExportTableModal;
