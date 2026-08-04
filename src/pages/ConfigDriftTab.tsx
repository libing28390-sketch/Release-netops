import React, { useState, useEffect, useCallback } from 'react';
import { RefreshCw, ShieldAlert, ShieldCheck, GitCompare, RotateCcw, Download, ChevronDown, ChevronRight, AlertTriangle, TrendingUp } from 'lucide-react';
import * as XLSX from 'xlsx';
import PageHero from '../components/PageHero';

interface DriftItem {
  device_id: string;
  hostname: string;
  ip_address: string;
  platform: string;
  device_status: string;
  drift_status: string;
  added_lines: number;
  removed_lines: number;
  changed_lines: number;
  last_checked: string;
  baseline_time: string;
  current_time: string;
  baseline_snapshot_id?: string;
  current_snapshot_id?: string;
}

interface DiffBlock {
  header: string;
  lines: { type: 'add' | 'remove' | 'context'; content: string }[];
}

interface DiffDetail {
  device_id: string;
  hostname: string;
  baseline: { id: string; timestamp: string; trigger: string };
  current: { id: string; timestamp: string; trigger: string };
  added: number;
  removed: number;
  changed: number;
  has_drift: boolean;
  blocks: DiffBlock[];
}

interface ConfigDriftTabProps {
  language: string;
  t: (key: string) => string;
}

const ConfigDriftTab: React.FC<ConfigDriftTabProps> = ({ language, t }) => {
  const [scanning, setScanning] = useState(false);
  const [items, setItems] = useState<DriftItem[]>([]);
  const [summary, setSummary] = useState({ total: 0, drifted: 0, compliant: 0, no_baseline: 0 });
  const [selectedDevice, setSelectedDevice] = useState<DriftItem | null>(null);
  const [diff, setDiff] = useState<DiffDetail | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [rollbackPreview, setRollbackPreview] = useState<string[] | null>(null);
  const [selectedLines, setSelectedLines] = useState<Set<number>>(new Set());
  const [expandedBlocks, setExpandedBlocks] = useState<Set<number>>(new Set());
  const [filterStatus, setFilterStatus] = useState('all');

  const runScan = useCallback(async () => {
    setScanning(true);
    try {
      const r = await fetch('/api/config-drift/scan');
      if (r.ok) {
        const data = await r.json();
        setItems(data.items || []);
        setSummary({ total: data.total, drifted: data.drifted, compliant: data.compliant, no_baseline: data.no_baseline });
      }
    } catch { /* ignore */ }
    setScanning(false);
  }, []);

  useEffect(() => { runScan(); }, [runScan]);

  const loadDiff = async (item: DriftItem) => {
    setSelectedDevice(item);
    setDiff(null);
    setRollbackPreview(null);
    setSelectedLines(new Set());
    setExpandedBlocks(new Set());
    if (item.drift_status !== 'drifted') return;
    setDiffLoading(true);
    try {
      const params = new URLSearchParams({ ...(item.baseline_snapshot_id ? { baseline_id: item.baseline_snapshot_id } : {}), ...(item.current_snapshot_id ? { current_id: item.current_snapshot_id } : {}) });
      const r = await fetch(`/api/config-drift/device/${item.device_id}/diff?${params}`);
      if (r.ok) {
        const data = await r.json();
        setDiff(data);
        // Auto-expand all blocks
        setExpandedBlocks(new Set(data.blocks.map((_: DiffBlock, i: number) => i)));
      }
    } catch { /* ignore */ }
    setDiffLoading(false);
  };

  const previewRollback = async (mode: 'full' | 'selective') => {
    if (!selectedDevice) return;
    const baselineId = selectedDevice.baseline_snapshot_id || diff?.baseline?.id;
    if (!baselineId) return;
    try {
      const r = await fetch('/api/config-drift/rollback-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          device_id: selectedDevice.device_id,
          snapshot_id: baselineId,
          selected_lines: mode === 'selective' ? Array.from(selectedLines) : [],
        }),
      });
      if (r.ok) {
        const data = await r.json();
        setRollbackPreview(data.commands || []);
      }
    } catch { /* ignore */ }
  };

  const toggleLine = (lineIdx: number) => {
    setSelectedLines(prev => {
      const next = new Set(prev);
      if (next.has(lineIdx)) next.delete(lineIdx);
      else next.add(lineIdx);
      return next;
    });
  };

  const handleExport = () => {
    if (items.length === 0) return;
    const data = items.map(i => ({
      Hostname: i.hostname,
      IP: i.ip_address,
      Platform: i.platform,
      Status: i.drift_status,
      'Added Lines': i.added_lines,
      'Removed Lines': i.removed_lines,
      'Changed Lines': i.changed_lines,
      'Last Checked': i.last_checked ? new Date(i.last_checked).toLocaleString() : '',
      'Baseline Time': i.baseline_time ? new Date(i.baseline_time).toLocaleString() : '',
    }));
    const ws = XLSX.utils.json_to_sheet(data);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Config Drift');
    const ts = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
    XLSX.writeFile(wb, `config_drift_report_${ts}.xlsx`);
  };

  const filtered = filterStatus === 'all' ? items : items.filter(i => i.drift_status === filterStatus);

  const statusIcon = (s: string) => {
    if (s === 'drifted') return <ShieldAlert size={16} className="text-red-500" />;
    if (s === 'compliant') return <ShieldCheck size={16} className="text-emerald-500" />;
    return <AlertTriangle size={16} className="text-black/30" />;
  };

  const statusLabel = (s: string) => {
    const map: Record<string, string> = language === 'zh'
      ? { drifted: '已漂移', compliant: '一致', no_baseline: '无基线', error: '错误' }
      : { drifted: 'Drifted', compliant: 'Compliant', no_baseline: 'No Baseline', error: 'Error' };
    return map[s] || s;
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={TrendingUp}
        title={language === 'zh' ? '配置漂移检测' : 'Configuration Drift'}
        subtitle={language === 'zh' ? '对比设备当前配置与基线快照，发现未授权变更' : 'Compare current configs against baselines to detect unauthorized changes'}
        actions={
          <>
            <button onClick={handleExport} className="p-1.5 rounded-lg border border-black/10 text-black/40 hover:text-[#00bceb] hover:border-[#00bceb]/30 transition-all" title={language === 'zh' ? '导出报告' : 'Export'}>
              <Download size={14} />
            </button>
            <button onClick={runScan} disabled={scanning} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-[#00bceb] text-white text-sm font-semibold hover:bg-[#00a5d0] transition-all disabled:opacity-50">
              <RefreshCw size={14} className={scanning ? 'animate-spin' : ''} />
              {language === 'zh' ? '扫描全部设备' : 'Scan All Devices'}
            </button>
          </>
        }
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-5">

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { label: language === 'zh' ? '设备总数' : 'Total', value: summary.total, color: 'text-[#00172D]', border: '' },
          { label: language === 'zh' ? '已漂移' : 'Drifted', value: summary.drifted, color: summary.drifted > 0 ? 'text-red-600' : 'text-emerald-600', border: summary.drifted > 0 ? 'border-l-[3px] border-l-red-500' : '' },
          { label: language === 'zh' ? '一致' : 'Compliant', value: summary.compliant, color: 'text-emerald-600', border: '' },
          { label: language === 'zh' ? '无基线' : 'No Baseline', value: summary.no_baseline, color: summary.no_baseline > 0 ? 'text-orange-500' : 'text-black/40', border: summary.no_baseline > 0 ? 'border-l-[3px] border-l-orange-400' : '' },
        ].map((card, i) => (
          <div key={i} className={`bg-white px-5 py-4 rounded-2xl shadow-sm border border-black/5 ${card.border}`}>
            <p className="text-[11px] font-bold uppercase tracking-wider text-black/30 mb-1">{card.label}</p>
            <p className={`text-2xl font-bold monitoring-data ${card.color}`}>{card.value}</p>
          </div>
        ))}
      </div>

      {/* Content: List + Detail */}
      <div className="grid grid-cols-12 gap-4">
        {/* Device List */}
        <div className="col-span-12 lg:col-span-5 bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-black/5 bg-black/[0.02] flex items-center justify-between">
            <span className="text-sm font-semibold text-[#00172D]">{language === 'zh' ? '设备列表' : 'Devices'}</span>
            <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)} className="text-xs bg-white border border-black/10 rounded-lg px-2 py-1 outline-none" title={language === 'zh' ? '按漂移状态筛选' : 'Filter by drift status'}>
              <option value="all">{language === 'zh' ? '全部' : 'All'}</option>
              <option value="drifted">{language === 'zh' ? '已漂移' : 'Drifted'}</option>
              <option value="compliant">{language === 'zh' ? '一致' : 'Compliant'}</option>
              <option value="no_baseline">{language === 'zh' ? '无基线' : 'No Baseline'}</option>
            </select>
          </div>
          <div className="max-h-[600px] overflow-y-auto divide-y divide-black/5">
            {filtered.length === 0 && (
              <div className="py-12 text-center text-sm text-black/30">
                {scanning ? (language === 'zh' ? '扫描中...' : 'Scanning...') : (language === 'zh' ? '暂无数据，请点击扫描' : 'No data. Click scan to start.')}
              </div>
            )}
            {filtered.map(item => (
              <button key={item.device_id} onClick={() => loadDiff(item)} className={`w-full text-left px-4 py-3 hover:bg-black/[0.02] transition-colors ${selectedDevice?.device_id === item.device_id ? 'bg-[#00bceb]/5 border-l-[3px] border-l-[#00bceb]' : ''}`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {statusIcon(item.drift_status)}
                    <div>
                      <p className="text-sm font-semibold text-[#00172D]">{item.hostname || item.device_id}</p>
                      <p className="text-[11px] text-black/40">{item.ip_address} · {item.platform}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${
                      item.drift_status === 'drifted' ? 'bg-red-100 text-red-700' :
                      item.drift_status === 'compliant' ? 'bg-emerald-100 text-emerald-700' :
                      'bg-black/5 text-black/40'
                    }`}>{statusLabel(item.drift_status)}</span>
                    {item.drift_status === 'drifted' && (
                      <p className="text-[10px] text-black/40 mt-1 monitoring-data">+{item.added_lines} -{item.removed_lines}</p>
                    )}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Diff Detail */}
        <div className="col-span-12 lg:col-span-7 bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
          {!selectedDevice ? (
            <div className="flex flex-col items-center justify-center h-[500px]">
              <GitCompare size={40} className="text-black/10 mb-3" />
              <p className="text-sm text-black/30">{language === 'zh' ? '选择设备查看漂移详情' : 'Select a device to view drift details'}</p>
            </div>
          ) : diffLoading ? (
            <div className="flex items-center justify-center h-[500px]">
              <RefreshCw size={24} className="animate-spin text-[#00bceb]" />
            </div>
          ) : selectedDevice.drift_status !== 'drifted' ? (
            <div className="flex flex-col items-center justify-center h-[500px]">
              {selectedDevice.drift_status === 'compliant' ? (
                <>
                  <ShieldCheck size={40} className="text-emerald-400 mb-3" />
                  <p className="text-sm text-emerald-600 font-semibold">{language === 'zh' ? '配置一致，无漂移' : 'Configuration is compliant'}</p>
                </>
              ) : (
                <>
                  <AlertTriangle size={40} className="text-black/10 mb-3" />
                  <p className="text-sm text-black/30">{language === 'zh' ? '该设备只有一个快照，无法对比' : 'Only one snapshot exists, cannot compare'}</p>
                </>
              )}
            </div>
          ) : diff ? (
            <div className="flex flex-col h-full">
              {/* Diff Header */}
              <div className="px-4 py-3 border-b border-black/5 bg-black/[0.02]">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-semibold text-[#00172D]">{diff.hostname}</p>
                    <p className="text-[11px] text-black/40">
                      {language === 'zh' ? '基线' : 'Baseline'}: {new Date(diff.baseline.timestamp).toLocaleString()} →
                      {' '}{language === 'zh' ? '当前' : 'Current'}: {new Date(diff.current.timestamp).toLocaleString()}
                    </p>
                  </div>
                  <div className="flex items-center gap-3 text-xs monitoring-data">
                    <span className="text-emerald-600">+{diff.added}</span>
                    <span className="text-red-500">-{diff.removed}</span>
                  </div>
                </div>
              </div>

              {/* Diff Blocks */}
              <div className="flex-1 overflow-y-auto max-h-[440px]">
                {diff.blocks.map((block, bi) => (
                  <div key={bi} className="border-b border-black/5">
                    <button onClick={() => setExpandedBlocks(prev => {
                      const next = new Set(prev);
                      if (next.has(bi)) next.delete(bi); else next.add(bi);
                      return next;
                    })} className="w-full text-left px-4 py-2 bg-blue-50/50 text-xs font-mono text-blue-700 flex items-center gap-2 hover:bg-blue-50">
                      {expandedBlocks.has(bi) ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                      {block.header}
                    </button>
                    {expandedBlocks.has(bi) && (
                      <div className="font-mono text-xs leading-6">
                        {block.lines.map((line, li) => {
                          const globalIdx = diff.blocks.slice(0, bi).reduce((s, b) => s + b.lines.filter(l => l.type !== 'context').length, 0) + block.lines.slice(0, li + 1).filter(l => l.type !== 'context').length;
                          return (
                            <div key={li} className={`px-4 flex items-start gap-1 ${
                              line.type === 'add' ? 'bg-emerald-50 text-emerald-800' :
                              line.type === 'remove' ? 'bg-red-50 text-red-800' :
                              'text-black/50'
                            }`}>
                              {line.type !== 'context' && (
                                <input type="checkbox" checked={selectedLines.has(globalIdx)} onChange={() => toggleLine(globalIdx)} className="mt-1.5 flex-shrink-0 accent-[#00bceb]" title={language === 'zh' ? '选中用于回滚' : 'Select for rollback'} />
                              )}
                              <span className="w-5 flex-shrink-0 text-right text-black/20 select-none">
                                {line.type === 'add' ? '+' : line.type === 'remove' ? '-' : ' '}
                              </span>
                              <span className="flex-1 whitespace-pre-wrap break-all">{line.content}</span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {/* Rollback Actions */}
              <div className="px-4 py-3 border-t border-black/5 bg-black/[0.02]">
                <div className="flex items-center gap-3">
                  <button onClick={() => previewRollback('selective')} disabled={selectedLines.size === 0} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-orange-500 text-white text-xs font-semibold hover:bg-orange-600 transition-all disabled:opacity-40 disabled:cursor-not-allowed">
                    <RotateCcw size={12} />
                    {language === 'zh' ? `选择性回滚 (${selectedLines.size})` : `Selective Rollback (${selectedLines.size})`}
                  </button>
                  <button onClick={() => previewRollback('full')} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-black/10 text-black/60 text-xs font-medium hover:border-[#00bceb]/30 hover:text-[#00bceb] transition-all">
                    <RotateCcw size={12} />
                    {language === 'zh' ? '完整回滚预览' : 'Full Rollback Preview'}
                  </button>
                </div>
              </div>

              {/* Rollback Preview */}
              {rollbackPreview && (
                <div className="px-4 py-3 border-t border-black/5 bg-amber-50/50 max-h-[200px] overflow-y-auto">
                  <p className="text-xs font-semibold text-amber-700 mb-2">
                    {language === 'zh' ? `回滚命令预览 (${rollbackPreview.length} 行)` : `Rollback Preview (${rollbackPreview.length} lines)`}
                  </p>
                  <pre className="font-mono text-[11px] text-amber-900 whitespace-pre-wrap">{rollbackPreview.join('\n')}</pre>
                </div>
              )}
            </div>
          ) : null}
        </div>
      </div>
      </div>
    </div>
  );
};

export default ConfigDriftTab;
