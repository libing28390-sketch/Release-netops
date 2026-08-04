import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  X, Activity, RotateCcw, AlertTriangle, Search, FileText,
  FileSpreadsheet, FileJson, ChevronRight, Loader2, Table2, Copy, Check, Download,
} from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip, ResponsiveContainer } from 'recharts';
import OutputActions from '../../../components/OutputActions';
import type { UnifiedExecutionLog, InspDetailTab, PlaybookExecutionApproval } from '../types';
import type { Device } from '../../../types';
import { splitOutputByCommand, downloadInspExcel, downloadInspJSON } from '../helpers';

interface ExecutionDetailProps {
  zh: boolean;
  open: boolean;
  selectedLog: UnifiedExecutionLog | null;
  logDetailLoading: boolean;
  onClose: () => void;
  onExport: (logId: string, format: string, source: string) => void;
  // Inspection
  inspectionDetail: any;
  selectedInspDeviceId: string | null;
  setSelectedInspDeviceId: (id: string | null) => void;
  collapsedCmds: Record<string, boolean>;
  toggleCmdCollapse: (cmd: string) => void;
  expandAllCmds: (cmds: string[]) => void;
  collapseAllCmds: (cmds: string[]) => void;
  inspParseResults: Record<string, { loading: boolean; data: any; error: string }>;
  inspCopiedKey: string | null;
  inspDetailTab: InspDetailTab;
  setInspDetailTab: (tab: InspDetailTab) => void;
  inspParseViewMode: Record<string, 'raw' | 'parsed'>;
  setInspParseViewMode: React.Dispatch<React.SetStateAction<Record<string, 'raw' | 'parsed'>>>;
  trendData: { deviceId: string; metric: string; series: any[]; firstInspection?: boolean } | null;
  trendLoading: boolean;
  setTrendData: (d: any) => void;
  onParseCmd: (blockKey: string, platform: string, command: string, rawOutput: string) => void;
  onCopyText: (text: string, key: string) => void;
  onFetchTrend: (deviceId: string, metric: string) => void;
  setCollapsedCmds: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  setInspParseResults: React.Dispatch<React.SetStateAction<Record<string, { loading: boolean; data: any; error: string }>>>;
  // Playbook
  pbDetail: any;
  pbDevices: any[];
  pbApprovals: PlaybookExecutionApproval[];
  pbApprovalsLoading: boolean;
  pbApprovalActionId: string;
  pbApprovalError: string;
  onPlaybookApproval: (approval: PlaybookExecutionApproval, decision: 'approve' | 'reject') => void;
  selectedPbDevice: any;
  pbDeviceDetail: any;
  onSelectPbDevice: (deviceId: string) => void;
  devices: Device[];
}

const ExecutionDetail: React.FC<ExecutionDetailProps> = ({
  zh, open, selectedLog, logDetailLoading, onClose, onExport,
  inspectionDetail, selectedInspDeviceId, setSelectedInspDeviceId,
  collapsedCmds, toggleCmdCollapse, expandAllCmds, collapseAllCmds,
  inspParseResults, inspCopiedKey, inspDetailTab, setInspDetailTab,
  inspParseViewMode, setInspParseViewMode,
  trendData, trendLoading, setTrendData,
  onParseCmd, onCopyText, onFetchTrend,
  setCollapsedCmds, setInspParseResults,
  pbDetail, pbDevices, pbApprovals, pbApprovalsLoading, pbApprovalActionId, pbApprovalError, onPlaybookApproval,
  selectedPbDevice, pbDeviceDetail, onSelectPbDevice, devices,
}) => {
  if (!selectedLog) return null;

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6 lg:p-8">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            className="relative bg-white rounded-[2rem] shadow-2xl w-full max-w-6xl h-[90vh] overflow-hidden flex flex-col z-10 border border-black/10"
          >
            {/* Header */}
            <div className="px-6 py-4 border-b border-black/5 flex items-center justify-between bg-black/[0.015] flex-shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-indigo-50 flex items-center justify-center text-indigo-600 border border-indigo-100">
                  <Activity size={18} />
                </div>
                <div>
                  <h3 className="text-base font-bold text-[#164e63]">
                    {selectedLog.name}
                  </h3>
                  <p className="text-[10px] text-black/30 font-mono mt-0.5">ID: {selectedLog.id}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {/* Export buttons */}
                <div className="flex items-center gap-1 bg-black/5 p-1 rounded-xl mr-2">
                  <button onClick={() => onExport(selectedLog.id, 'html', selectedLog.source)} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-indigo-700 hover:bg-white transition-all shadow-sm">
                    <FileText size={14} /> HTML
                  </button>
                  <button onClick={() => onExport(selectedLog.id, 'pdf', selectedLog.source)} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-rose-700 hover:bg-white transition-all shadow-sm">
                    <FileText size={14} /> PDF
                  </button>
                  <button onClick={() => onExport(selectedLog.id, 'xlsx', selectedLog.source)} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-emerald-700 hover:bg-white transition-all shadow-sm">
                    <FileSpreadsheet size={14} /> Excel
                  </button>
                  <button onClick={() => onExport(selectedLog.id, 'json', selectedLog.source)} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-slate-700 hover:bg-white transition-all shadow-sm">
                    <FileJson size={14} /> JSON
                  </button>
                </div>
                <button onClick={onClose} className="p-2 rounded-xl text-black/20 hover:bg-black/5 hover:text-black/40 transition-all">
                  <X size={20} />
                </button>
              </div>
            </div>

            {selectedLog.source === 'playbook' && selectedLog.status === 'awaiting_approval' && (
              <div className="shrink-0 border-b border-violet-100 bg-violet-50/60 px-6 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-xs font-semibold text-violet-900">{zh ? '执行审批门' : 'Execution approval gates'}</div>
                  {pbApprovalsLoading && <Loader2 size={14} className="animate-spin text-violet-500" />}
                </div>
                {pbApprovalError && <div className="mt-2 rounded-lg bg-rose-50 px-2.5 py-2 text-[10px] text-rose-700">{pbApprovalError}</div>}
                <div className="mt-2 space-y-2">
                  {pbApprovals.map((approval) => (
                    <div key={approval.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-violet-100 bg-white px-3 py-2 text-[10px]">
                      <div className="min-w-0">
                        <div className="font-semibold text-slate-800">{approval.title || approval.id}</div>
                        <div className="mt-0.5 text-slate-500">{approval.message || (zh ? '审批通过前不会启动设备任务。' : 'Device tasks remain paused until approval.')}</div>
                      </div>
                      {approval.status === 'PENDING' ? (
                        <div className="flex shrink-0 gap-1.5">
                          <button type="button" onClick={() => onPlaybookApproval(approval, 'approve')} disabled={pbApprovalActionId === approval.id} className="rounded-lg bg-emerald-600 px-2.5 py-1.5 font-semibold text-white disabled:opacity-50">{pbApprovalActionId === approval.id ? '...' : (zh ? '批准' : 'Approve')}</button>
                          <button type="button" onClick={() => onPlaybookApproval(approval, 'reject')} disabled={pbApprovalActionId === approval.id} className="rounded-lg border border-rose-200 bg-white px-2.5 py-1.5 font-semibold text-rose-700 disabled:opacity-50">{zh ? '拒绝' : 'Reject'}</button>
                        </div>
                      ) : <span className={`rounded-full px-2 py-1 font-semibold ${approval.status === 'APPROVED' ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>{approval.status}</span>}
                    </div>
                  ))}
                  {!pbApprovalsLoading && pbApprovals.length === 0 && <div className="text-[10px] text-violet-700/70">{zh ? '未找到审批记录。' : 'No approval records found.'}</div>}
                </div>
              </div>
            )}

            {/* Content */}
            <div className="flex-1 overflow-hidden relative">
              {logDetailLoading ? (
                <div className="h-full flex flex-col items-center justify-center text-black/20 gap-3">
                  <RotateCcw size={32} className="animate-spin opacity-20" />
                  <span className="text-xs font-bold">{zh ? '加载详情中...' : 'Loading details...'}</span>
                </div>
              ) : selectedLog.source === 'inspection' ? (
                <InspectionView
                  zh={zh}
                  inspectionDetail={inspectionDetail}
                  selectedInspDeviceId={selectedInspDeviceId}
                  setSelectedInspDeviceId={setSelectedInspDeviceId}
                  collapsedCmds={collapsedCmds}
                  toggleCmdCollapse={toggleCmdCollapse}
                  expandAllCmds={expandAllCmds}
                  collapseAllCmds={collapseAllCmds}
                  inspParseResults={inspParseResults}
                  inspCopiedKey={inspCopiedKey}
                  inspDetailTab={inspDetailTab}
                  setInspDetailTab={setInspDetailTab}
                  inspParseViewMode={inspParseViewMode}
                  setInspParseViewMode={setInspParseViewMode}
                  trendData={trendData}
                  trendLoading={trendLoading}
                  setTrendData={setTrendData}
                  onParseCmd={onParseCmd}
                  onCopyText={onCopyText}
                  onFetchTrend={onFetchTrend}
                  setCollapsedCmds={setCollapsedCmds}
                  setInspParseResults={setInspParseResults}
                />
              ) : (
                <PlaybookView
                  zh={zh}
                  pbDevices={pbDevices}
                  selectedPbDevice={selectedPbDevice}
                  pbDeviceDetail={pbDeviceDetail}
                  onSelectPbDevice={onSelectPbDevice}
                  devices={devices}
                  collapsedCmds={collapsedCmds}
                  toggleCmdCollapse={toggleCmdCollapse}
                  setCollapsedCmds={setCollapsedCmds}
                />
              )}
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};

/* ═══════════════════════════════════════════════════════ */
/*  Inspection Detail Sub-View                             */
/* ═══════════════════════════════════════════════════════ */

interface InspectionViewProps {
  zh: boolean;
  inspectionDetail: any;
  selectedInspDeviceId: string | null;
  setSelectedInspDeviceId: (id: string | null) => void;
  collapsedCmds: Record<string, boolean>;
  toggleCmdCollapse: (cmd: string) => void;
  expandAllCmds: (cmds: string[]) => void;
  collapseAllCmds: (cmds: string[]) => void;
  inspParseResults: Record<string, { loading: boolean; data: any; error: string }>;
  inspCopiedKey: string | null;
  inspDetailTab: InspDetailTab;
  setInspDetailTab: (tab: InspDetailTab) => void;
  inspParseViewMode: Record<string, 'raw' | 'parsed'>;
  setInspParseViewMode: React.Dispatch<React.SetStateAction<Record<string, 'raw' | 'parsed'>>>;
  trendData: any;
  trendLoading: boolean;
  setTrendData: (d: any) => void;
  onParseCmd: (blockKey: string, platform: string, command: string, rawOutput: string) => void;
  onCopyText: (text: string, key: string) => void;
  onFetchTrend: (deviceId: string, metric: string) => void;
  setCollapsedCmds: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  setInspParseResults: React.Dispatch<React.SetStateAction<Record<string, { loading: boolean; data: any; error: string }>>>;
}

const InspectionView: React.FC<InspectionViewProps> = ({
  zh, inspectionDetail, selectedInspDeviceId, setSelectedInspDeviceId,
  collapsedCmds, toggleCmdCollapse, expandAllCmds, collapseAllCmds,
  inspParseResults, inspCopiedKey, inspDetailTab, setInspDetailTab,
  inspParseViewMode, setInspParseViewMode,
  trendData, trendLoading, setTrendData,
  onParseCmd, onCopyText, onFetchTrend,
  setCollapsedCmds, setInspParseResults,
}) => {
  return (
    <div className="flex flex-col md:flex-row h-full">
      {/* Device List (Left) */}
      <div className="w-full md:w-4/12 border-r border-black/5 flex flex-col h-full bg-slate-50/50">
        <div className="p-4 border-b border-black/5 bg-white flex items-center justify-between">
          <span className="text-xs font-bold text-black/50">{zh ? '设备巡检结果' : 'Inspection Results'}</span>
          <span className="text-[10px] font-bold text-black/20 uppercase tracking-widest tabular-nums">
            {inspectionDetail?.results?.length || 0} {zh ? '台设备' : 'Devices'}
          </span>
        </div>
        <div className="flex-1 overflow-auto p-2 space-y-1 custom-scrollbar">
          {(inspectionDetail?.results || []).map((res: any) => {
            const isSelected = selectedInspDeviceId === res.device_id;
            return (
              <div
                key={res.id}
                onClick={() => {
                  setSelectedInspDeviceId(res.device_id);
                  setCollapsedCmds({});
                  setInspParseResults({});
                }}
                className={`flex items-center justify-between p-3 rounded-xl border cursor-pointer transition-all ${
                  isSelected 
                    ? 'bg-[#164e63] text-white border-transparent shadow-md' 
                    : 'bg-white border-black/5 hover:border-black/10 hover:shadow-sm'
                }`}
              >
                <div className="min-w-0">
                  <p className={`text-xs font-bold truncate ${isSelected ? 'text-white' : 'text-[#164e63]'}`}>{res.hostname}</p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <p className={`text-[9px] font-mono ${isSelected ? 'text-white/60' : 'text-black/30'}`}>{res.ip_address}</p>
                    <span className={`text-[9px] font-bold ${isSelected ? 'text-cyan-300' : 'text-cyan-600'}`}>Score: {res.health_score ?? '—'}</span>
                  </div>
                </div>
                <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
                  res.health_status === 'healthy' 
                    ? (isSelected ? 'bg-emerald-400/20 text-emerald-300' : 'bg-emerald-50 text-emerald-600')
                    : res.health_status === 'warning'
                      ? (isSelected ? 'bg-amber-400/20 text-amber-300' : 'bg-amber-50 text-amber-600')
                      : (isSelected ? 'bg-red-400/20 text-red-300' : 'bg-red-50 text-red-600')
                }`}>
                  {res.health_status === 'healthy' ? (zh ? '健康' : 'OK') : res.health_status === 'warning' ? (zh ? '警告' : 'WARN') : (zh ? '故障' : 'CRIT')}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Detail Content (Right) */}
      <div className="flex-1 flex flex-col bg-[#1E1E1E] overflow-hidden">
        {selectedInspDeviceId ? (() => {
          const res = inspectionDetail.results.find((r: any) => r.device_id === selectedInspDeviceId);
          if (!res) return null;
          
          let rawOutputs: Record<string, string> = {};
          try { rawOutputs = typeof res.raw_outputs_json === 'string' ? JSON.parse(res.raw_outputs_json) : (res.raw_outputs_json || {}); } catch(_e) {}
          
          let analysis: any[] = [];
          try { analysis = typeof res.analysis_json === 'string' ? JSON.parse(res.analysis_json) : (res.analysis_json || []); } catch(_e) {}

          let findings: any[] = [];
          try { findings = typeof res.findings_json === 'string' ? JSON.parse(res.findings_json) : (res.findings_json || []); } catch(_e) {}

          let metricsObj: Record<string, any> = {};
          try { metricsObj = typeof res.metrics_json === 'string' ? JSON.parse(res.metrics_json) : (res.metrics_json || {}); } catch(_e) {}

          let correlatedRisks: any[] = [];
          try { correlatedRisks = typeof res.correlated_risks_json === 'string' ? JSON.parse(res.correlated_risks_json) : (res.correlated_risks_json || []); } catch(_e) {}

          const complianceItems = analysis.filter((a: any) => (a.category === 'compliance') || (a.key && String(a.key).includes('compliance')));

          return (
            <>
              {/* Device header bar */}
              <div className="p-4 border-b border-white/10 bg-black/20 flex items-center justify-between">
                <div className="flex flex-col gap-1">
                  <span className="text-xs text-white/80 font-bold block">{res.hostname} ({res.ip_address})</span>
                  <div className="flex items-center gap-2">
                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded bg-white/5 ${res.ping_ok ? 'text-emerald-400' : 'text-red-400'}`}>Ping: {res.ping_ok ? 'OK' : 'FAIL'}</span>
                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded bg-white/5 ${res.ssh_ok ? 'text-emerald-400' : 'text-red-400'}`}>SSH: {res.ssh_ok ? 'OK' : 'FAIL'}</span>
                    {res.ssh_error && <span className="text-[10px] text-red-400/70 truncate max-w-[200px]" title={res.ssh_error}>{res.ssh_error}</span>}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <div className="text-[10px] text-white/30 font-mono uppercase tracking-widest">{zh ? '健康得分' : 'Health Score'}</div>
                  <div className={`text-xl font-black ${(res.health_score || 0) >= 90 ? 'text-emerald-400' : (res.health_score || 0) >= 60 ? 'text-amber-400' : 'text-red-400'}`}>{res.health_score ?? '—'}</div>
                </div>
              </div>

              <div className="flex-1 overflow-auto custom-scrollbar-dark p-6 space-y-8 select-text">
                {/* Tab bar */}
                <div className="flex items-center gap-1 border-b border-white/10 -mt-2 -mx-2 px-2">
                  {([
                    { key: 'analysis', label: zh ? '指标分析' : 'Analysis' },
                    { key: 'snapshot', label: zh ? '指标快照' : 'Snapshot' },
                    { key: 'compliance', label: zh ? '合规检查' : 'Compliance' },
                    { key: 'raw', label: zh ? '原始输出' : 'Raw Output' },
                  ] as { key: InspDetailTab; label: string }[]).map(t => (
                    <button
                      key={t.key}
                      onClick={() => { setInspDetailTab(t.key); setTrendData(null); }}
                      className={`px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider transition-colors ${
                        inspDetailTab === t.key ? 'text-cyan-400 border-b-2 border-cyan-400' : 'text-white/40 hover:text-white/70'
                      }`}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>

                {/* TAB: Analysis */}
                {inspDetailTab === 'analysis' && (
                  <AnalysisTab zh={zh} analysis={analysis} correlatedRisks={correlatedRisks} trendData={trendData} trendLoading={trendLoading} setTrendData={setTrendData} onFetchTrend={onFetchTrend} deviceId={res.device_id} />
                )}

                {/* TAB: Snapshot */}
                {inspDetailTab === 'snapshot' && (
                  <SnapshotTab zh={zh} metricsObj={metricsObj} />
                )}

                {/* TAB: Compliance */}
                {inspDetailTab === 'compliance' && (
                  <ComplianceTab zh={zh} complianceItems={complianceItems} />
                )}

                {/* TAB: Raw Output */}
                {inspDetailTab === 'raw' && (
                  <RawOutputTab
                    zh={zh} res={res} rawOutputs={rawOutputs} analysis={analysis} findings={findings}
                    collapsedCmds={collapsedCmds} toggleCmdCollapse={toggleCmdCollapse}
                    expandAllCmds={expandAllCmds} collapseAllCmds={collapseAllCmds}
                    inspParseResults={inspParseResults} inspCopiedKey={inspCopiedKey}
                    inspParseViewMode={inspParseViewMode} setInspParseViewMode={setInspParseViewMode}
                    onParseCmd={onParseCmd} onCopyText={onCopyText}
                  />
                )}
              </div>
            </>
          );
        })() : (
          <div className="flex-1 flex flex-col items-center justify-center text-white/20 gap-3">
            <Search size={48} strokeWidth={1} className="opacity-10" />
            <span className="text-sm">{zh ? '请选择左侧设备查看详情' : 'Select a device to see details'}</span>
          </div>
        )}
      </div>
    </div>
  );
};

/* ═══════════════════════════════════════════════════════ */
/*  Analysis Tab                                           */
/* ═══════════════════════════════════════════════════════ */

const AnalysisTab: React.FC<{
  zh: boolean; analysis: any[]; correlatedRisks: any[];
  trendData: any; trendLoading: boolean; setTrendData: (d: any) => void;
  onFetchTrend: (deviceId: string, metric: string) => void; deviceId: string;
}> = ({ zh, analysis, correlatedRisks, trendData, trendLoading, setTrendData, onFetchTrend, deviceId }) => (
  <div className="space-y-4">
    {correlatedRisks.length > 0 && (
      <div className="space-y-2">
        <h4 className="text-[11px] font-bold text-red-400 uppercase tracking-widest flex items-center gap-2">
          <AlertTriangle size={12} /> {zh ? '关联风险预警' : 'Correlated Risk Alerts'}
        </h4>
        {correlatedRisks.map((risk, i) => (
          <div key={i} className={`p-3 rounded-lg border ${risk.severity === 'critical' ? 'bg-red-500/10 border-red-500/30' : 'bg-amber-500/10 border-amber-500/30'}`}>
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1">
                <div className="text-xs font-bold text-white/90 mb-1">⚠️ {risk.rule_name}</div>
                <div className="text-[11px] text-white/60 leading-relaxed">{risk.description}</div>
                {risk.suggestion && <div className="text-[11px] text-cyan-400/70 mt-1.5">💡 {risk.suggestion}</div>}
              </div>
              <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded shrink-0 ${risk.severity === 'critical' ? 'bg-red-500/30 text-red-300' : 'bg-amber-500/30 text-amber-300'}`}>{risk.severity?.toUpperCase()}</span>
            </div>
          </div>
        ))}
      </div>
    )}

    {trendData && (
      <div className="rounded-lg border border-cyan-500/20 bg-black/30 p-4">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[11px] font-bold text-cyan-400">{zh ? '趋势：' : 'Trend: '}{trendData.metric}</span>
          <button onClick={() => setTrendData(null)} className="text-[10px] text-white/30 hover:text-white/60">✕</button>
        </div>
        {trendLoading ? (
          <div className="text-center py-6 text-white/30 text-xs">{zh ? '加载中...' : 'Loading...'}</div>
        ) : trendData.series.length > 0 ? (
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={trendData.series}>
              <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
              <XAxis dataKey="ts" stroke="#64748b" fontSize={10} tickFormatter={(v) => String(v).slice(5, 16)} />
              <YAxis stroke="#64748b" fontSize={10} />
              <RTooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', fontSize: 11 }} />
              <Line type="monotone" dataKey="value" stroke="#00bceb" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="text-center py-6 text-white/30 text-xs italic">
            {zh ? '暂无历史数据，首次巡检后将自动记录' : 'No history yet — data appears after future runs'}
          </div>
        )}
      </div>
    )}

    {analysis.length > 0 ? (
      <table className="nx-data-table nx-data-table--compact text-[11px]">
        <thead>
          <tr className="text-white/50 border-b border-white/10">
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '指标' : 'Metric'}</th>
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '当前值' : 'Value'}</th>
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '状态' : 'Status'}</th>
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '诊断结论' : 'Conclusion'}</th>
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '建议' : 'Suggestion'}</th>
            <th className="text-right py-2 px-2 font-bold uppercase tracking-wider">{zh ? '操作' : 'Actions'}</th>
          </tr>
        </thead>
        <tbody>
          {analysis.map((a, i) => {
            const rowBg = a.status === 'critical' ? 'bg-red-500/10' : a.status === 'warning' ? 'bg-amber-500/10' : '';
            const isNumeric = typeof a.value === 'number';
            return (
              <tr key={i} className={`${rowBg} border-b border-white/5`}>
                <td className="py-2 px-2 text-white/90 font-bold">{a.metric}</td>
                <td className="py-2 px-2 text-white/70 font-mono">{String(a.value ?? '—')}</td>
                <td className="py-2 px-2">
                  <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
                    a.status === 'critical' ? 'bg-red-500/30 text-red-300' : a.status === 'warning' ? 'bg-amber-500/30 text-amber-300' : 'bg-emerald-500/30 text-emerald-300'
                  }`}>{a.status?.toUpperCase()}</span>
                </td>
                <td className="py-2 px-2 text-white/50">{a.conclusion}</td>
                <td className="py-2 px-2 text-white/50">{a.suggestion}</td>
                <td className="py-2 px-2 text-right">
                  {isNumeric && a.key && (
                    <button onClick={() => onFetchTrend(deviceId, a.key)} className="text-[9px] font-bold text-cyan-400 hover:text-cyan-300 px-2 py-1 rounded border border-cyan-500/30 hover:bg-cyan-500/10">
                      {zh ? '趋势' : 'Trend'}
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    ) : (
      <div className="text-white/30 text-center py-6 text-xs italic">{zh ? '暂无分析结果' : 'No analysis available'}</div>
    )}
  </div>
);

/* ═══════════════════════════════════════════════════════ */
/*  Snapshot Tab                                           */
/* ═══════════════════════════════════════════════════════ */

const SnapshotTab: React.FC<{ zh: boolean; metricsObj: Record<string, any> }> = ({ zh, metricsObj }) => (
  <div className="space-y-2">
    {Object.keys(metricsObj).length === 0 ? (
      <div className="text-white/30 text-center py-6 text-xs italic">{zh ? '暂无指标数据' : 'No metrics'}</div>
    ) : (
      <table className="nx-data-table nx-data-table--compact text-[11px]">
        <thead>
          <tr className="text-white/50 border-b border-white/10">
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '指标键' : 'Metric Key'}</th>
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '值 / 错误' : 'Value / Error'}</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(metricsObj).map(([key, val]) => {
            const isError = val && typeof val === 'object' && 'error' in (val as any);
            return (
              <tr key={key} className="border-b border-white/5">
                <td className={`py-2 px-2 font-mono ${isError ? 'text-red-400' : 'text-white/80'}`}>{key}</td>
                <td className="py-2 px-2">
                  {isError ? (
                    <span className="text-red-400 text-[10px]">⚠ {(val as any).error}</span>
                  ) : (
                    <span className="text-white/70 font-mono">{String(val)}</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    )}
  </div>
);

/* ═══════════════════════════════════════════════════════ */
/*  Compliance Tab                                         */
/* ═══════════════════════════════════════════════════════ */

const ComplianceTab: React.FC<{ zh: boolean; complianceItems: any[] }> = ({ zh, complianceItems }) => (
  <div className="space-y-2">
    {complianceItems.length === 0 ? (
      <div className="text-white/30 text-center py-6 text-xs italic">{zh ? '暂无合规检查项' : 'No compliance checks defined'}</div>
    ) : (
      <table className="nx-data-table nx-data-table--compact text-[11px]">
        <thead>
          <tr className="text-white/50 border-b border-white/10">
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '合规项' : 'Item'}</th>
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '当前值' : 'Value'}</th>
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '状态' : 'Status'}</th>
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '说明' : 'Description'}</th>
          </tr>
        </thead>
        <tbody>
          {complianceItems.map((c, i) => {
            const passing = c.status === 'healthy';
            return (
              <tr key={i} className="border-b border-white/5">
                <td className="py-2 px-2 text-white/90 font-bold">{c.metric}</td>
                <td className="py-2 px-2 text-white/70 font-mono">{String(c.value ?? '—')}</td>
                <td className="py-2 px-2">
                  {passing ? (
                    <span className="inline-flex items-center gap-1 text-emerald-400 text-[10px] font-bold">✓ {zh ? '通过' : 'Pass'}</span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-red-400 text-[10px] font-bold">✗ {zh ? '失败' : 'Fail'}</span>
                  )}
                </td>
                <td className="py-2 px-2 text-white/50">{c.conclusion}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    )}
  </div>
);

/* ═══════════════════════════════════════════════════════ */
/*  Raw Output Tab                                         */
/* ═══════════════════════════════════════════════════════ */

const RawOutputTab: React.FC<{
  zh: boolean; res: any; rawOutputs: Record<string, string>; analysis: any[]; findings: any[];
  collapsedCmds: Record<string, boolean>; toggleCmdCollapse: (cmd: string) => void;
  expandAllCmds: (cmds: string[]) => void; collapseAllCmds: (cmds: string[]) => void;
  inspParseResults: Record<string, { loading: boolean; data: any; error: string }>;
  inspCopiedKey: string | null;
  inspParseViewMode: Record<string, 'raw' | 'parsed'>;
  setInspParseViewMode: React.Dispatch<React.SetStateAction<Record<string, 'raw' | 'parsed'>>>;
  onParseCmd: (blockKey: string, platform: string, command: string, rawOutput: string) => void;
  onCopyText: (text: string, key: string) => void;
}> = ({ zh, res, rawOutputs, analysis, findings, collapsedCmds, toggleCmdCollapse, expandAllCmds, collapseAllCmds, inspParseResults, inspCopiedKey, inspParseViewMode, setInspParseViewMode, onParseCmd, onCopyText }) => (
  <>
    {/* Findings */}
    {findings.length > 0 && (
      <div className="space-y-3">
        <h4 className="text-[11px] font-bold text-white/40 uppercase tracking-widest flex items-center gap-2">
          <AlertTriangle size={12} className="text-amber-500" /> {zh ? '异常发现' : 'Diagnostic Findings'}
        </h4>
        <div className="space-y-2">
          {findings.map((f, i) => (
            <div key={i} className={`p-3 rounded-lg border flex items-start gap-3 ${f.severity === 'critical' ? 'bg-red-500/10 border-red-500/20 text-red-400' : 'bg-amber-500/10 border-amber-500/20 text-amber-400'}`}>
              <div className="mt-1 w-1.5 h-1.5 rounded-full bg-current" />
              <span className="text-xs font-medium leading-relaxed">{f.message}</span>
            </div>
          ))}
        </div>
      </div>
    )}

    {/* Analysis summary */}
    {analysis.length > 0 && (
      <div className="space-y-3">
        <h4 className="text-[11px] font-bold text-white/40 uppercase tracking-widest flex items-center gap-2">
          <Activity size={12} className="text-cyan-500" /> {zh ? '智能分析' : 'Smart Analysis'}
        </h4>
        <div className="grid grid-cols-1 gap-3">
          {analysis.map((a, i) => (
            <div key={i} className="p-3 rounded-lg bg-white/5 border border-white/10 hover:bg-white/[0.08] transition-colors">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-bold text-white/80">{a.metric}</span>
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                  a.status === 'healthy' ? 'text-emerald-400 bg-emerald-400/10' : a.status === 'warning' ? 'text-amber-400 bg-amber-400/10' : 'text-red-400 bg-red-400/10'
                }`}>{a.status?.toUpperCase()}</span>
              </div>
              <div className="text-xs text-white/50 leading-relaxed">{a.conclusion}</div>
              {a.value !== undefined && (
                <div className="mt-2 text-[10px] font-mono text-white/30 italic">Value: {String(a.value)}</div>
              )}
            </div>
          ))}
        </div>
      </div>
    )}

    {/* Raw Output Blocks */}
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-[11px] font-bold text-white/40 uppercase tracking-widest flex items-center gap-2">
          <FileText size={12} className="text-indigo-400" /> {zh ? '命令执行记录' : 'Command Execution Blocks'}
        </h4>
        {Object.keys(rawOutputs).length > 1 && (
          <div className="flex items-center gap-3">
            <button onClick={() => expandAllCmds(Object.keys(rawOutputs))} className="text-[10px] font-bold text-cyan-400/50 hover:text-cyan-400 transition-colors">{zh ? '全部展开' : 'Expand All'}</button>
            <div className="w-px h-2 bg-white/10" />
            <button onClick={() => collapseAllCmds(Object.keys(rawOutputs))} className="text-[10px] font-bold text-white/20 hover:text-white/40 transition-colors">{zh ? '全部折叠' : 'Collapse All'}</button>
          </div>
        )}
      </div>
      <div className="space-y-3">
        {Object.keys(rawOutputs).length > 0 ? (
          Object.entries(rawOutputs).map(([cmd, output], i) => {
            const outputStr = String(output);
            const isError = outputStr.startsWith('__ERROR__') || outputStr.includes('% Invalid input') || outputStr.includes('error');
            const isCollapsed = collapsedCmds[cmd] ?? (!isError && Object.keys(rawOutputs).length > 3);
            const blockKey = `${res.device_id}::${cmd}`;
            const parseState = inspParseResults[blockKey];
            const isCopied = inspCopiedKey === blockKey;

            return (
              <div key={i} className={`rounded-lg overflow-hidden border transition-all ${isError ? 'border-red-500/30 bg-red-500/5' : 'border-white/5 bg-black/20'}`}>
                <div onClick={() => toggleCmdCollapse(cmd)} className="px-4 py-2 bg-white/5 flex items-center justify-between cursor-pointer hover:bg-white/[0.08]">
                  <div className="flex items-center gap-2 min-w-0">
                    <ChevronRight size={14} className={`text-white/20 transition-transform shrink-0 ${isCollapsed ? '' : 'rotate-90'}`} />
                    <span className={`text-[11px] font-mono font-bold truncate ${isError ? 'text-red-400' : 'text-cyan-400/80'}`}>&gt; {cmd}</span>
                  </div>
                  {!isCollapsed && (
                    <div className="flex items-center gap-1 shrink-0 ml-3" onClick={e => e.stopPropagation()}>
                      <div className="flex items-center gap-0.5 p-0.5 rounded-md bg-white/5 border border-white/10 mr-1">
                        <button onClick={() => setInspParseViewMode(prev => ({ ...prev, [blockKey]: 'raw' }))} className={`flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-bold transition-all ${(!inspParseViewMode[blockKey] || inspParseViewMode[blockKey] === 'raw') ? 'bg-white/10 text-white' : 'text-white/30 hover:text-white/60'}`}>Raw</button>
                        <button onClick={() => { if (!parseState || (!parseState.data && !parseState.loading)) { onParseCmd(blockKey, res.platform || 'cisco_ios', cmd, outputStr); } else { setInspParseViewMode(prev => ({ ...prev, [blockKey]: 'parsed' })); } }} className={`flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-bold transition-all ${(inspParseViewMode[blockKey] === 'parsed') ? 'bg-white/10 text-cyan-400' : 'text-white/30 hover:text-white/60'}`}>
                          {parseState?.loading ? <Loader2 size={9} className="animate-spin" /> : 'Parsed'}
                        </button>
                      </div>
                      <button onClick={() => onCopyText(outputStr, blockKey)} className={`flex items-center gap-1 p-1 rounded border transition-all text-[9px] font-mono ${isCopied ? 'bg-emerald-900/40 border-emerald-500/40 text-emerald-400' : 'bg-white/5 border-white/10 text-white/30 hover:text-white/60 hover:border-white/20'}`} title={zh ? '复制' : 'Copy'}>
                        {isCopied ? <Check size={11} /> : <Copy size={11} />}
                      </button>
                      <button onClick={() => { const safeCmd = cmd.replace(/[^a-z0-9_]/gi, '_').slice(0, 40); const blob = new Blob([outputStr], { type: 'text/plain' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `${res.hostname}_${safeCmd}.txt`; a.click(); URL.revokeObjectURL(url); }} className="flex items-center gap-1 p-1 rounded border bg-white/5 border-white/10 text-white/30 hover:text-cyan-400 hover:border-cyan-500/40 transition-all" title={zh ? '下载原始文本 (.txt)' : 'Download raw .txt'}>
                        <Download size={11} /> <span className="text-[9px] font-mono">txt</span>
                      </button>
                      <button onClick={() => { if (!parseState || (!parseState.data && !parseState.loading)) { onParseCmd(blockKey, res.platform || 'cisco_ios', cmd, outputStr); } }} disabled={parseState?.loading} className={`flex items-center gap-1 px-2 py-1 rounded border text-[9px] font-mono transition-all ${parseState?.data ? 'bg-cyan-900/40 border-cyan-500/40 text-cyan-300' : parseState?.error ? 'bg-amber-900/20 border-amber-500/30 text-amber-400/60' : 'bg-white/5 border-white/10 text-white/30 hover:text-cyan-400 hover:border-cyan-500/40'}`} title={parseState?.error || (zh ? '用 TextFSM 解析' : 'Parse with TextFSM')}>
                        {parseState?.loading ? <Loader2 size={11} className="animate-spin" /> : <Table2 size={11} />}
                        <span>{parseState?.data ? (zh ? '已解析' : 'Parsed') : (zh ? '解析' : 'Parse')}</span>
                      </button>
                      {parseState?.data?.count > 0 && (
                        <button onClick={() => { const safeCmd = cmd.replace(/[^a-z0-9_]/gi, '_').slice(0, 40); downloadInspExcel(parseState.data.records, parseState.data.fields, `${res.hostname}_${safeCmd}_parsed`); }} className="flex items-center gap-1 p-1 rounded border bg-emerald-900/30 border-emerald-500/40 text-emerald-400 hover:bg-emerald-900/50 transition-all" title={zh ? '下载解析结果 (Excel)' : 'Download parsed as Excel'}>
                          <FileSpreadsheet size={11} /> <span className="text-[9px] font-mono">xlsx</span>
                        </button>
                      )}
                      {parseState?.data?.count > 0 && (
                        <button onClick={() => { const safeCmd = cmd.replace(/[^a-z0-9_]/gi, '_').slice(0, 40); downloadInspJSON(parseState.data.records, `${res.hostname}_${safeCmd}_parsed`); }} className="flex items-center gap-1 p-1 rounded border bg-indigo-900/30 border-indigo-500/40 text-indigo-400 hover:bg-indigo-900/50 transition-all" title={zh ? '下载解析结果 (JSON)' : 'Download parsed as JSON'}>
                          <FileJson size={11} /> <span className="text-[9px] font-mono">json</span>
                        </button>
                      )}
                    </div>
                  )}
                  {isCollapsed && (
                    <span className="text-[10px] text-white/20 font-mono italic truncate max-w-[300px]">
                      {outputStr.substring(0, 60).replace(/\n/g, ' ')}...
                    </span>
                  )}
                </div>
                {!isCollapsed && (
                  <div className={`p-4 font-mono text-[11px] ${inspParseViewMode[blockKey] === 'parsed' ? '' : 'whitespace-pre-wrap'} leading-relaxed ${isError ? 'text-red-300/80' : 'text-white/60'}`}>
                    {inspParseViewMode[blockKey] === 'parsed' ? (
                      <>
                        {parseState?.loading ? (
                          <div className="flex items-center gap-2 py-4 text-cyan-400/50"><Loader2 size={16} className="animate-spin" /><span>{zh ? '正在解析中...' : 'Parsing...'}</span></div>
                        ) : parseState?.error ? (
                          <div className="py-4 text-amber-500/80 italic">⚠ {parseState.error}</div>
                        ) : parseState?.data?.records ? (
                          <div className="overflow-x-auto custom-scrollbar-dark pb-2">
                            <table className="w-full text-left border-collapse border border-white/10">
                              <thead>
                                <tr className="bg-white/5 border-b border-white/10">
                                  {parseState.data.fields.map((f: string) => (
                                    <th key={f} className="px-3 py-2 text-[10px] font-bold text-cyan-400/80 uppercase tracking-wider border-r border-white/10 last:border-r-0">{f}</th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-white/5">
                                {parseState.data.records.map((rec: any, idx: number) => (
                                  <tr key={idx} className="hover:bg-white/[0.03]">
                                    {parseState.data.fields.map((f: string) => (
                                      <td key={f} className="px-3 py-2 text-[10px] text-white/60 whitespace-nowrap border-r border-white/5 last:border-r-0">{String(rec[f] ?? '—')}</td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        ) : (
                          <div className="py-4 text-white/20 italic">{zh ? '未解析或解析无结果' : 'Not parsed or no results'}</div>
                        )}
                      </>
                    ) : (
                      outputStr
                    )}
                  </div>
                )}
              </div>
            );
          })
        ) : (
          <div className="text-white/20 text-center py-10 italic text-[11px]">
            {res.ssh_ok ? (zh ? '无命令回显' : 'No output returned') : (zh ? '连接未建立' : 'Connection failed')}
          </div>
        )}
      </div>
    </div>
  </>
);

/* ═══════════════════════════════════════════════════════ */
/*  Playbook Detail Sub-View                               */
/* ═══════════════════════════════════════════════════════ */

const PlaybookView: React.FC<{
  zh: boolean; pbDevices: any[]; selectedPbDevice: any; pbDeviceDetail: any;
  onSelectPbDevice: (deviceId: string) => void; devices: Device[];
  collapsedCmds: Record<string, boolean>; toggleCmdCollapse: (cmd: string) => void;
  setCollapsedCmds: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
}> = ({ zh, pbDevices, selectedPbDevice, pbDeviceDetail, onSelectPbDevice, devices, collapsedCmds, toggleCmdCollapse, setCollapsedCmds }) => (
  <div className="flex flex-col md:flex-row h-full">
    {/* Device List (Left) */}
    <div className="w-full md:w-4/12 border-r border-black/5 flex flex-col h-full bg-slate-50/50">
      <div className="p-4 border-b border-black/5 bg-white">
        <span className="text-xs font-bold text-black/50">{zh ? '执行设备情况' : 'Device Execution'}</span>
      </div>
      <div className="flex-1 overflow-auto p-2 space-y-1">
        {pbDevices.map((dev) => {
          const stMap: Record<string, { cls: string; label: string }> = {
            success: { cls: 'bg-emerald-500', label: zh ? '成功' : 'Pass' },
            completed: { cls: 'bg-emerald-500', label: zh ? '成功' : 'Pass' },
            failed: { cls: 'bg-red-500', label: zh ? '失败' : 'Fail' },
            error: { cls: 'bg-red-500', label: zh ? '失败' : 'Fail' },
            partial: { cls: 'bg-amber-500', label: zh ? '部分成功' : 'Partial' },
            partial_failure: { cls: 'bg-amber-500', label: zh ? '部分成功' : 'Partial' },
            running: { cls: 'bg-cyan-500 animate-pulse', label: zh ? '运行中' : 'Live' },
          };
          const dst = stMap[dev.status || ''] || { cls: 'bg-slate-400', label: dev.status || (zh ? '未知' : 'Unknown') };
          const isSelected = selectedPbDevice === dev.device_id;

          return (
            <div
              key={dev.device_id}
              onClick={() => onSelectPbDevice(dev.device_id)}
              className={`flex items-center justify-between p-3 rounded-xl border cursor-pointer transition-all ${
                isSelected ? 'bg-[#164e63] text-white border-transparent shadow-md' : 'bg-white border-black/5 hover:border-black/10 hover:shadow-sm'
              }`}
            >
              <div className="min-w-0">
                <p className={`text-xs font-bold truncate ${isSelected ? 'text-white' : 'text-[#164e63]'}`}>{dev.hostname}</p>
                <p className={`text-[10px] font-mono mt-0.5 ${isSelected ? 'text-white/60' : 'text-black/30'}`}>{dev.ip_address}</p>
              </div>
              <span className={`text-[9px] font-bold text-white px-2 py-0.5 rounded-md ${dst.cls}`}>{dst.label}</span>
            </div>
          );
        })}
      </div>
    </div>

    {/* Command Output (Right) */}
    <div className="flex-1 flex flex-col bg-[#1E1E1E] overflow-hidden">
      <div className="p-4 border-b border-white/10 bg-black/20 flex items-center justify-between">
        <div>
          <span className="text-xs text-white/80 font-bold block">
            {selectedPbDevice 
              ? (pbDevices.find((d: any) => d.device_id === selectedPbDevice)?.hostname || '') 
              : (zh ? '请选择设备查看命令输出' : 'Select a device to view command outputs')}
          </span>
          {selectedPbDevice && (() => {
            const dev = devices.find(d => d.id === selectedPbDevice);
            if (!dev) return null;
            return (
              <div className="flex items-center gap-3 mt-1.5">
                <span className="text-[10px] text-white/40 font-mono bg-white/5 px-1.5 py-0.5 rounded uppercase tracking-tighter">PLAT: {dev.platform || '-'}</span>
                <span className="text-[10px] text-white/40 font-mono bg-white/5 px-1.5 py-0.5 rounded uppercase tracking-tighter">ROLE: {dev.role || '-'}</span>
                <span className="text-[10px] text-white/40 font-mono bg-white/5 px-1.5 py-0.5 rounded uppercase tracking-tighter">SITE: {dev.site || '-'}</span>
                <span className="text-[10px] text-white/40 font-mono bg-white/5 px-1.5 py-0.5 rounded uppercase tracking-tighter">MOD: {dev.model || '-'}</span>
              </div>
            );
          })()}
        </div>
        {selectedPbDevice && pbDeviceDetail?.phases && (
          <div className="flex items-center gap-3">
            <button 
              onClick={() => {
                const next = { ...collapsedCmds };
                Object.entries(pbDeviceDetail.phases).forEach(([ph, pdata]: any) => {
                  const cmds = (pdata || {}).commands || [];
                  const outStr = typeof (pdata || {}).output === 'string' ? pdata.output : JSON.stringify((pdata || {}).output || '');
                  const blocks = splitOutputByCommand(outStr, cmds);
                  blocks.forEach((_, bi) => next[`pb_${selectedPbDevice}_${ph}_${bi}`] = false);
                });
                setCollapsedCmds(next);
              }}
              className="text-[10px] font-bold text-cyan-400/60 hover:text-cyan-400 transition-colors cursor-pointer"
            >
              {zh ? '全部展开' : 'Expand All'}
            </button>
            <div className="w-px h-2.5 bg-white/10" />
            <button 
              onClick={() => {
                const next = { ...collapsedCmds };
                Object.entries(pbDeviceDetail.phases).forEach(([ph, pdata]: any) => {
                  const cmds = (pdata || {}).commands || [];
                  const outStr = typeof (pdata || {}).output === 'string' ? pdata.output : JSON.stringify((pdata || {}).output || '');
                  const blocks = splitOutputByCommand(outStr, cmds);
                  blocks.forEach((_, bi) => next[`pb_${selectedPbDevice}_${ph}_${bi}`] = true);
                });
                setCollapsedCmds(next);
              }}
              className="text-[10px] font-bold text-white/30 hover:text-white/60 transition-colors cursor-pointer"
            >
              {zh ? '全部折叠' : 'Collapse All'}
            </button>
          </div>
        )}
      </div>
      <div className="flex-1 p-6 font-mono text-xs text-[#d4d4d4] overflow-auto whitespace-pre-wrap select-text relative">
        {pbDeviceDetail?.phases ? (
          Object.entries(pbDeviceDetail.phases).map(([phase, pdata]: any) => {
            const pd = pdata || {};
            const cmds = pd.commands || [];
            const outputStr = typeof pd.output === 'string' ? pd.output : JSON.stringify(pd.output || '');
            const blocks = splitOutputByCommand(outputStr, cmds);
            const dev = devices.find(d => d.id === selectedPbDevice);

            return (
              <div key={phase} className="mb-6 group/phase">
                <div className="flex items-center gap-2 mb-3">
                  <div className="h-px flex-1 bg-white/5" />
                  <span className="text-[#a170e8] text-[10px] font-black uppercase tracking-[0.2em]"># PHASE: {phase.toUpperCase()}</span>
                  <div className="h-px flex-1 bg-white/5" />
                </div>
                
                <div className="space-y-3">
                  {blocks.map((blk, bi) => {
                    const bOutput = blk.output || '';
                    const bIsError = bOutput.includes('__ERROR__') || bOutput.includes('% Invalid input') || bOutput.includes('error');
                    const bKey = `pb_${selectedPbDevice}_${phase}_${bi}`;
                    const isCollapsed = collapsedCmds[bKey] ?? false;
                    
                    return (
                      <div key={bi} className={`rounded-lg overflow-hidden border transition-all ${bIsError ? 'border-red-500/30 bg-red-500/5' : 'border-white/5 bg-black/20'}`}>
                        <div 
                          onClick={() => toggleCmdCollapse(bKey)}
                          className="px-4 py-2 bg-white/5 flex items-center justify-between cursor-pointer hover:bg-white/[0.08] select-none"
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <ChevronRight size={14} className={`text-white/20 shrink-0 transition-transform duration-200 ${isCollapsed ? '' : 'rotate-90'}`} />
                            <span className={`text-[11px] font-mono font-bold truncate ${bIsError ? 'text-red-400' : 'text-cyan-400/80'}`}>&gt; {blk.command || 'system'}</span>
                          </div>
                          <div className="flex items-center gap-2 shrink-0 ml-3" onClick={e => e.stopPropagation()}>
                            {isCollapsed && (
                              <span className="text-[10px] text-white/30 font-mono italic truncate max-w-[250px] hidden sm:inline">
                                {bOutput.substring(0, 60).replace(/\n/g, ' ')}...
                              </span>
                            )}
                            <OutputActions
                              text={blk.output}
                              filename={`${dev?.hostname || 'device'}_${phase}_cmd${bi}`}
                              theme="dark"
                              zh={zh}
                              iconOnly={true}
                            />
                          </div>
                        </div>
                        {!isCollapsed && (
                          <div className={`p-4 font-mono text-[11px] whitespace-pre-wrap leading-relaxed ${bIsError ? 'text-red-300/80' : 'text-[#d4d4d4]'}`}>
                            {blk.output || (pd.status === 'success' ? (zh ? '命令执行成功，但无回显' : 'Success, no output') : '—')}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })
        ) : (
          <div className="text-white/20 text-center py-24 select-none">{zh ? '无命令输出' : 'No command output'}</div>
        )}
      </div>
    </div>
  </div>
);

export default ExecutionDetail;
