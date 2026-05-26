import React from 'react';
import { RotateCcw, Monitor, Terminal, Minimize2, Maximize2, X, Search } from 'lucide-react';
import OutputActions from '../../../components/OutputActions';
import type { Device } from '../../../types';
import type { QuickQueryTable } from '../types';

interface QuickQueryResultOverlayProps {
  isZh: boolean;
  quickQueryRunning: boolean;
  quickQueryOutput: string;
  quickQueryMaximized: boolean;
  quickQueryLabel: string;
  targetDevices: Device[];
  onQuickQueryMaximizedChange: (val: boolean) => void;
  onResetQuickQuery: () => void;
  handleClearSelection: () => void;
  quickQueryCommands: string[];
  copyTextWithFallback: (text: string) => Promise<boolean>;
  showToast: (message: string, tone: 'success' | 'error' | 'warning' | 'info') => void;
  quickQueryStructured: any;
  quickQueryView: 'terminal' | 'table';
  quickQueryTable: QuickQueryTable;
  quickQuerySearch: string;
  setQuickQuerySearch: (val: string) => void;
  filteredQuickQueryRecords: Array<Record<string, any>>;
}

export const QuickQueryResultOverlay: React.FC<QuickQueryResultOverlayProps> = ({
  isZh,
  quickQueryRunning,
  quickQueryOutput,
  quickQueryMaximized,
  quickQueryLabel,
  targetDevices,
  onQuickQueryMaximizedChange,
  onResetQuickQuery,
  handleClearSelection,
  quickQueryCommands,
  copyTextWithFallback,
  showToast,
  quickQueryStructured,
  quickQueryView,
  quickQueryTable,
  quickQuerySearch,
  setQuickQuerySearch,
  filteredQuickQueryRecords,
}) => {
  if (!quickQueryRunning && !quickQueryOutput) return null;

  return (
    <>
      <div
        className="fixed inset-0 z-[70] bg-[#020817]/72 backdrop-blur-sm"
        onClick={() => {
          onResetQuickQuery();
          handleClearSelection();
        }}
      />
      <div
        className={
          quickQueryMaximized
            ? 'fixed left-1/2 top-1/2 z-[80] flex h-[84vh] w-[min(1280px,90vw)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-3xl border border-white/10 bg-[linear-gradient(180deg,#0d1117_0%,#151b23_100%)] shadow-[0_32px_120px_rgba(0,0,0,0.6)]'
            : 'fixed left-1/2 top-1/2 z-[80] flex h-[min(520px,70vh)] w-[min(720px,85vw)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-3xl border border-white/10 bg-[linear-gradient(180deg,#0d1117_0%,#151b23_100%)] shadow-[0_32px_120px_rgba(0,0,0,0.6)]'
        }
      >
        {/* Terminal title bar */}
        <div className="shrink-0 flex items-center justify-between border-b border-white/[0.06] bg-[linear-gradient(90deg,#1c2030_0%,#161b22_100%)] px-4 py-2.5">
          <div className="flex items-center gap-3 min-w-0">
            <div className="flex gap-[6px] mr-1 shrink-0">
              <span className="w-[10px] h-[10px] rounded-full bg-[#ff5f57]/80" />
              <span className="w-[10px] h-[10px] rounded-full bg-[#febc2e]/80" />
              <span className="w-[10px] h-[10px] rounded-full bg-[#28c840]/80" />
            </div>
            {quickQueryRunning ? (
              <RotateCcw size={13} className="animate-spin text-[#00bceb] shrink-0" />
            ) : (
              <Monitor size={13} className="text-emerald-400 shrink-0" />
            )}
            <span className="text-[12px] font-bold text-white/90 truncate">{quickQueryLabel}</span>
            <div className="flex items-center gap-2 truncate">
              <Terminal size={12} className="text-cyan-400/70" />
              <span className="text-[11px] font-bold tracking-widest text-white/80 uppercase truncate">
                {targetDevices.length === 1
                  ? targetDevices[0].hostname
                  : isZh
                  ? `批量执行 (${targetDevices.length})`
                  : `Batch (${targetDevices.length})`}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={() => onQuickQueryMaximizedChange(!quickQueryMaximized)} className="text-white/30 hover:text-white transition-colors">
              {quickQueryMaximized ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            </button>
            <button
              onClick={() => {
                onResetQuickQuery();
                handleClearSelection();
              }}
              className="text-white/30 hover:text-white transition-colors"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Executed commands bar */}
        {!quickQueryRunning && quickQueryCommands.length > 0 && (
          <div className="shrink-0 border-b border-white/[0.05] bg-[linear-gradient(180deg,rgba(16,23,34,0.92)_0%,rgba(9,14,22,0.82)_100%)] px-4 py-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center rounded-full border border-cyan-400/18 bg-cyan-400/10 px-2 py-1 text-[9px] font-bold uppercase tracking-[0.16em] text-cyan-100/90">
                    {isZh ? '实际执行命令' : 'Executed Commands'}
                  </span>
                  <span className="text-[10px] text-white/38">
                    {quickQueryCommands.length} {isZh ? '条' : `cmd${quickQueryCommands.length > 1 ? 's' : ''}`}
                  </span>
                </div>
                <div className="mt-2 flex flex-col gap-1.5">
                  {quickQueryCommands.map((cmd, idx) => (
                    <div
                      key={`${cmd}-${idx}`}
                      className="overflow-hidden rounded-xl border border-cyan-400/14 bg-[linear-gradient(180deg,rgba(3,11,21,0.96)_0%,rgba(7,18,32,0.92)_100%)]"
                    >
                      <div className="flex items-stretch">
                        <span className="w-1 shrink-0 bg-[linear-gradient(180deg,rgba(34,211,238,0.95)_0%,rgba(6,182,212,0.45)_100%)]" />
                        <div className="min-w-0 flex-1 px-3 py-2">
                          <div className="mb-1 flex items-center gap-2 text-[9px] font-bold uppercase tracking-[0.16em] text-cyan-200/55">
                            <span>{isZh ? '命令' : 'Command'}</span>
                            <span className="text-white/18">#{idx + 1}</span>
                          </div>
                          <code className="block overflow-x-auto text-[11px] font-medium leading-relaxed text-[#F7FBFF]">{cmd}</code>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <button
                onClick={async () => {
                  const ok = await copyTextWithFallback(quickQueryCommands.join('\n'));
                  showToast(ok ? (isZh ? '命令已复制' : 'Copied') : (isZh ? '复制失败' : 'Failed'), ok ? 'success' : 'error');
                }}
                className="shrink-0 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-[10px] font-bold uppercase tracking-[0.12em] text-white/60 hover:bg-white/[0.08] hover:text-white transition-all"
              >
                {isZh ? '复制' : 'Copy'}
              </button>
            </div>
          </div>
        )}

        {/* Terminal/Table content */}
        <div className="flex-1 overflow-auto terminal-scroll">
          {quickQueryRunning ? (
            <div className="flex flex-col items-center justify-center py-16 gap-4">
              <div className="w-10 h-10 rounded-full border-2 border-[#00bceb]/20 border-t-[#00bceb] animate-spin" />
              <span className="text-xs text-white/25 font-mono">{isZh ? '正在查询...' : 'Querying...'}</span>
            </div>
          ) : quickQueryStructured && quickQueryView === 'table' ? (
            <div className="p-5 space-y-4">
              <div className="flex items-center justify-between gap-3 border-b border-white/[0.04] pb-3">
                <div className="flex items-center gap-4 min-w-0">
                  <div className="min-w-0">
                    <p className="text-[12px] font-bold text-white/90 truncate">{quickQueryLabel}</p>
                    <p className="mt-1 text-[10px] text-white/35">
                      {quickQueryTable.category?.parser || 'ntc-templates'} · {isZh ? '记录数' : 'Records'} {filteredQuickQueryRecords.length} /{' '}
                      {Number(quickQueryTable.category?.count || 0)}
                    </p>
                  </div>
                  <div className="relative">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-white/25" size={11} />
                    <input
                      type="text"
                      value={quickQuerySearch}
                      onChange={(e) => setQuickQuerySearch(e.target.value)}
                      placeholder={isZh ? '过滤结果...' : 'Filter results...'}
                      className="pl-7 pr-3 py-1 bg-white/[0.04] border border-white/[0.08] rounded-lg text-[11px] text-white placeholder-white/25 outline-none focus:border-cyan-500/50 w-44 transition-all"
                    />
                    {quickQuerySearch && (
                      <button onClick={() => setQuickQuerySearch('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-white/25 hover:text-white">
                        <X size={10} />
                      </button>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {quickQueryTable.category?.parse_errors?.length > 0 && (
                    <span className="rounded-full bg-amber-500/12 px-2 py-1 text-[10px] font-bold uppercase text-amber-300">
                      {isZh ? '部分回退' : 'Partial Fallback'}
                    </span>
                  )}
                  <OutputActions
                    text={quickQueryOutput}
                    csvRows={filteredQuickQueryRecords as Array<Record<string, unknown>>}
                    filename={`${(quickQueryLabel || 'query').replace(/[^a-zA-Z0-9_-]+/g, '_').slice(0, 40) || 'query'}`}
                    theme="dark"
                    zh={isZh}
                  />
                </div>
              </div>
              {quickQueryTable.records.length > 0 ? (
                <div
                  className={
                    quickQueryMaximized
                      ? 'overflow-auto rounded-xl border border-white/[0.06] bg-black/20 max-h-[calc(84vh-12rem)]'
                      : 'overflow-auto rounded-xl border border-white/[0.06] bg-black/20 min-h-[24rem] max-h-[58vh]'
                  }
                >
                  <table className="min-w-full text-left text-[12px] text-[#d8e2eb]">
                    <thead className="sticky top-0 bg-[#101722]">
                      <tr className="border-b border-white/[0.06]">
                        {quickQueryTable.columns.map((col) => (
                          <th key={col} className="px-3 py-2 text-[10px] font-bold uppercase tracking-[0.14em] text-white/45 whitespace-nowrap">
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {filteredQuickQueryRecords.map((rec, ri) => (
                        <tr key={ri} className="border-b border-white/[0.04] last:border-b-0 hover:bg-white/[0.03]">
                          {quickQueryTable.columns.map((col) => {
                            const val = rec?.[col];
                            return (
                              <td key={`${ri}-${col}`} className="px-3 py-2 align-top text-[11px] text-[#d8e2eb] whitespace-nowrap">
                                {val == null || val === '' ? <span className="text-white/20">-</span> : String(val)}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-white/[0.08] bg-white/[0.02] px-4 py-5 text-sm text-white/45">
                  {isZh ? '当前没有结构化记录，可切回终端查看原始回显。' : 'No structured records available. Switch to Terminal for raw output.'}
                </div>
              )}
              {quickQueryTable.category?.parse_errors?.length > 0 && (
                <div className="rounded-xl border border-amber-400/20 bg-amber-400/8 px-4 py-3 text-xs text-amber-200">
                  <p className="font-bold uppercase tracking-[0.14em]">{isZh ? '解析提示' : 'Parsing Notes'}</p>
                  <div className="mt-2 space-y-1">
                    {quickQueryTable.category.parse_errors.map((item: any, idx: number) => (
                      <div key={idx}>
                        {item.command}: {item.error}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="p-5 relative group/output">
              <div className="mb-3 flex items-start justify-between gap-2 border-b border-white/[0.04] pb-3">
                <div className="flex items-start gap-2 flex-1 min-w-0">
                  <span className="text-emerald-400/60 font-mono font-bold text-[11px] mt-0.5 select-none shrink-0">❯</span>
                  <code className="text-[11px] font-mono text-emerald-400/40 leading-relaxed whitespace-pre-wrap break-all">{quickQueryLabel}</code>
                </div>
                {quickQueryOutput && (
                  <OutputActions
                    text={quickQueryOutput}
                    filename={`${(quickQueryLabel || 'query').replace(/[^a-zA-Z0-9_-]+/g, '_').slice(0, 40) || 'query'}`}
                    theme="dark"
                    zh={isZh}
                  />
                )}
              </div>
              <pre className="text-[13px] font-mono text-[#e6edf3] leading-[1.75] whitespace-pre-wrap break-all select-text">{quickQueryOutput}</pre>
            </div>
          )}
        </div>
      </div>
    </>
  );
};
