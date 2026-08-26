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
  quickQueryCommands: string[];
  copyTextWithFallback: (text: string) => Promise<boolean>;
  showToast: (message: string, tone: 'success' | 'error' | 'warning' | 'info') => void;
  quickQueryStructured: any;
  quickQueryView: 'terminal' | 'table';
  quickQueryTable: QuickQueryTable;
  quickQuerySearch: string;
  setQuickQuerySearch: (val: string) => void;
  filteredQuickQueryRecords: Array<Record<string, any>>;
  onOpenDebugger?: (platform: string, command: string, output: string) => void;
  onQuickQueryViewChange?: (view: 'terminal' | 'table') => void;
}

const formatParserLabel = (value: unknown, isZh: boolean): string => {
  const raw = String(value || '').trim();
  if (!raw) return isZh ? '未声明解析器' : 'Parser not reported';

  if (raw.toLowerCase().startsWith('textfsm:')) {
    const filename = raw.slice('textfsm:'.length).trim();
    return isZh ? `TextFSM 自动匹配 · ${filename}` : `TextFSM automatic match · ${filename}`;
  }
  if (raw === 'platform-parser' || raw === 'platform-registry') {
    return isZh ? '平台版本自动匹配' : 'Automatic platform-version match';
  }
  if (raw === 'ntc-templates') {
    return isZh ? 'NTC Templates（旧目录）' : 'NTC Templates (legacy catalog)';
  }
  return raw;
};

export const QuickQueryResultOverlay: React.FC<QuickQueryResultOverlayProps> = ({
  isZh,
  quickQueryRunning,
  quickQueryOutput,
  quickQueryMaximized,
  quickQueryLabel,
  targetDevices,
  onQuickQueryMaximizedChange,
  onResetQuickQuery,
  quickQueryCommands,
  copyTextWithFallback,
  showToast,
  quickQueryStructured,
  quickQueryView,
  quickQueryTable,
  quickQuerySearch,
  setQuickQuerySearch,
  filteredQuickQueryRecords,
  onOpenDebugger,
  onQuickQueryViewChange,
}) => {
  if (!quickQueryRunning && !quickQueryOutput) return null;

  return (
    <>
      <div
        className="fixed inset-0 z-[70] bg-[#020817]/72 backdrop-blur-sm"
        onClick={() => {
          onResetQuickQuery();
        }}
      />
      <div
        className={quickQueryMaximized
          ? 'fixed left-1/2 top-1/2 z-[80] flex h-[min(900px,calc(100vh-2rem))] w-[min(1360px,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-2xl border border-white/10 bg-[linear-gradient(180deg,#0d1117_0%,#151b23_100%)] shadow-[0_32px_120px_rgba(0,0,0,0.6)] sm:rounded-3xl'
          : 'fixed left-1/2 top-1/2 z-[80] flex h-[min(680px,calc(100vh-2rem))] w-[min(900px,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-2xl border border-white/10 bg-[linear-gradient(180deg,#0d1117_0%,#151b23_100%)] shadow-[0_32px_120px_rgba(0,0,0,0.6)] sm:rounded-3xl'}
      >
        {/* Terminal title bar */}
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-white/[0.06] bg-[linear-gradient(90deg,#1c2030_0%,#161b22_100%)] px-4 py-3 sm:px-5">
          <div className="flex min-w-0 flex-1 items-center gap-2.5">
            <div className="mr-0.5 flex shrink-0 gap-[5px] sm:mr-1 sm:gap-[6px]">
              <span className="w-[10px] h-[10px] rounded-full bg-[#ff5f57]/80" />
              <span className="w-[10px] h-[10px] rounded-full bg-[#febc2e]/80" />
              <span className="w-[10px] h-[10px] rounded-full bg-[#28c840]/80" />
            </div>
            {quickQueryRunning ? (
              <RotateCcw size={13} className="animate-spin text-[#00bceb] shrink-0" />
            ) : (
              <Monitor size={13} className="text-emerald-400 shrink-0" />
            )}
            <span className="max-w-[42%] truncate text-[12px] font-bold text-white/90 sm:max-w-none">{quickQueryLabel}</span>
            <span className="hidden text-white/20 sm:inline">/</span>
            <div className="flex min-w-0 items-center gap-2 truncate">
              <Terminal size={12} className="text-cyan-400/70" />
              <span className="truncate text-[11px] font-bold uppercase tracking-widest text-white/80">
                {targetDevices.length === 1
                  ? targetDevices[0].hostname
                  : isZh
                  ? `批量执行 (${targetDevices.length})`
                  : `Batch (${targetDevices.length})`}
              </span>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2 sm:gap-3">
            {/* View Toggle */}
            {!quickQueryRunning && quickQueryTable.records.length > 0 && (
              <div className="flex items-center rounded-xl border border-white/5 bg-black/45 p-0.5">
                <button
                  type="button"
                  onClick={() => onQuickQueryViewChange?.('table')}
                  className={`rounded-lg px-2.5 py-1.5 text-[11px] font-bold transition-all ${
                    quickQueryView === 'table'
                      ? 'bg-indigo-600 text-white shadow-sm shadow-indigo-600/10'
                      : 'text-white/40 hover:text-white/70'
                  }`}
                >
                  {isZh ? '表格' : 'Table'}
                </button>
                <button
                  type="button"
                  onClick={() => onQuickQueryViewChange?.('terminal')}
                  className={`rounded-lg px-2.5 py-1.5 text-[11px] font-bold transition-all ${
                    quickQueryView === 'terminal'
                      ? 'bg-indigo-600 text-white shadow-sm shadow-indigo-600/10'
                      : 'text-white/40 hover:text-white/70'
                  }`}
                >
                  {isZh ? '终端' : 'Terminal'}
                </button>
              </div>
            )}
            <button
              type="button"
              aria-label={quickQueryMaximized ? (isZh ? '还原窗口' : 'Restore window') : (isZh ? '最大化窗口' : 'Maximize window')}
              onClick={() => onQuickQueryMaximizedChange(!quickQueryMaximized)}
              className="rounded-lg p-1.5 text-white/35 transition-colors hover:bg-white/[0.06] hover:text-white"
            >
              {quickQueryMaximized ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            </button>
            <button
              type="button"
              aria-label={isZh ? '关闭结果' : 'Close result'}
              onClick={() => {
                onResetQuickQuery();
              }}
              className="rounded-lg p-1.5 text-white/35 transition-colors hover:bg-white/[0.06] hover:text-white"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Executed commands bar */}
        {!quickQueryRunning && quickQueryCommands.length > 0 && (
          <div className="shrink-0 border-b border-white/[0.05] bg-[linear-gradient(180deg,rgba(16,23,34,0.92)_0%,rgba(9,14,22,0.82)_100%)] px-4 py-4 sm:px-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="inline-flex items-center rounded-full border border-cyan-400/18 bg-cyan-400/10 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-[0.16em] text-cyan-100/90">
                    {isZh ? '实际执行命令' : 'Executed Commands'}
                  </span>
                  <span className="text-[10px] text-white/38">
                    {quickQueryCommands.length} {isZh ? '条' : `cmd${quickQueryCommands.length > 1 ? 's' : ''}`}
                  </span>
                </div>
                <div className="terminal-scroll mt-3 max-h-40 space-y-2 overflow-y-auto pr-1">
                  {quickQueryCommands.map((cmd, idx) => (
                    <div
                      key={`${cmd}-${idx}`}
                      className="overflow-hidden rounded-2xl border border-cyan-400/14 bg-[linear-gradient(180deg,rgba(3,11,21,0.96)_0%,rgba(7,18,32,0.92)_100%)]"
                    >
                      <div className="flex items-stretch">
                        <span className="w-1 shrink-0 bg-[linear-gradient(180deg,rgba(34,211,238,0.95)_0%,rgba(6,182,212,0.45)_100%)]" />
                        <div className="min-w-0 flex-1 px-4 py-3">
                          <div className="mb-1.5 flex items-center gap-2 text-[9px] font-bold uppercase tracking-[0.16em] text-cyan-200/55">
                            <span>{isZh ? '命令' : 'Command'}</span>
                            <span className="text-white/18">#{idx + 1}</span>
                          </div>
                          <code className="netops-terminal-font block overflow-x-auto text-[12px] font-medium leading-relaxed text-[#F7FBFF]">{cmd}</code>
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
                className="self-start rounded-xl border border-white/[0.08] bg-white/[0.04] px-3.5 py-2.5 text-[10px] font-bold uppercase tracking-[0.12em] text-white/60 transition-all hover:bg-white/[0.08] hover:text-white sm:mt-0"
              >
                {isZh ? '复制' : 'Copy'}
              </button>
            </div>
          </div>
        )}

        {/* Terminal/Table content */}
        <div className="min-h-0 flex-1 overflow-auto terminal-scroll">
          {quickQueryRunning ? (
            <div className="flex flex-col items-center justify-center py-16 gap-4">
              <div className="w-10 h-10 rounded-full border-2 border-[#00bceb]/20 border-t-[#00bceb] animate-spin" />
              <span className="text-xs text-white/25 font-mono">{isZh ? '正在查询...' : 'Querying...'}</span>
            </div>
          ) : quickQueryStructured && quickQueryView === 'table' ? (
            <div className="space-y-4 p-4 sm:p-5">
              <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-3 sm:p-4">
                <div className="flex flex-col gap-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate text-[13px] font-bold text-white/90">{quickQueryLabel}</p>
                        <span
                          title={formatParserLabel(quickQueryTable.category?.parser, isZh)}
                          className="max-w-full truncate rounded-full border border-cyan-400/15 bg-cyan-400/[0.07] px-2.5 py-1 text-[10px] text-cyan-100/70"
                        >
                          {formatParserLabel(quickQueryTable.category?.parser, isZh)}
                        </span>
                      </div>
                      <p className="mt-2 text-[10px] text-white/40">
                        {isZh ? '结构化记录' : 'Structured records'} · {filteredQuickQueryRecords.length} / {Number(quickQueryTable.category?.count || 0)}
                      </p>
                    </div>
                    {quickQueryTable.category?.parse_errors?.length > 0 && (
                      <span className="rounded-full bg-amber-500/12 px-2.5 py-1.5 text-[10px] font-bold uppercase text-amber-300">
                        {isZh ? '部分回退' : 'Partial Fallback'}
                      </span>
                    )}
                  </div>
                  <div className="flex flex-col gap-2 border-t border-white/[0.06] pt-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="relative w-full sm:max-w-xs">
                      <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-white/25" size={12} />
                      <input
                        type="text"
                        value={quickQuerySearch}
                        onChange={(e) => setQuickQuerySearch(e.target.value)}
                        aria-label={isZh ? '搜索结构化结果' : 'Search structured results'}
                        placeholder={isZh ? '搜索所有字段，如 IP、目的地址、协议...' : 'Search all fields, e.g. IP, destination, protocol...'}
                        className="w-full rounded-xl border border-white/[0.08] bg-white/[0.04] py-2 pl-8 pr-8 text-[11px] text-white outline-none transition-all placeholder:text-white/25 focus:border-cyan-500/50 focus:bg-white/[0.06]"
                      />
                      {quickQuerySearch && (
                        <button
                          type="button"
                          aria-label={isZh ? '清除过滤条件' : 'Clear filter'}
                          onClick={() => setQuickQuerySearch('')}
                          className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-white/25 hover:bg-white/[0.06] hover:text-white"
                        >
                          <X size={11} />
                        </button>
                      )}
                    </div>
                    <div className="flex items-center justify-between gap-2 sm:justify-end">
                      <span className="text-[10px] uppercase tracking-[0.14em] text-white/25">{isZh ? '导出结果' : 'Export'}</span>
                      <OutputActions
                        text={JSON.stringify(filteredQuickQueryRecords, null, 2)}
                        csvRows={filteredQuickQueryRecords as Array<Record<string, unknown>>}
                        filename={`${(quickQueryLabel || 'query').replace(/[^a-zA-Z0-9_-]+/g, '_').slice(0, 40) || 'query'}`}
                        theme="dark"
                        zh={isZh}
                        iconOnly
                      />
                    </div>
                  </div>
                </div>
              </div>
              {quickQueryTable.records.length > 0 ? (
                <div
                  className={
                    quickQueryMaximized
                      ? 'max-h-[calc(100vh-15rem)] overflow-auto rounded-2xl border border-white/[0.06] bg-black/20'
                      : 'min-h-[12rem] max-h-[calc(100vh-18rem)] overflow-auto rounded-2xl border border-white/[0.06] bg-black/20 sm:min-h-[20rem]'
                  }
                >
                  <table className="nx-terminal-table min-w-full text-left text-[12px] text-[#d8e2eb]">
                    <thead className="sticky top-0 bg-[#101722]">
                      <tr className="border-b border-white/[0.06]">
                        {quickQueryTable.columns.map((col) => (
                          <th key={col} className="whitespace-nowrap px-4 py-3 text-[10px] font-bold uppercase tracking-[0.14em] text-white/45">
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
                              <td key={`${ri}-${col}`} className="whitespace-nowrap px-4 py-2.5 align-top text-[11px] text-[#d8e2eb]">
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
                  <p>
                    {quickQuerySearch.trim()
                      ? (isZh ? `没有匹配“${quickQuerySearch.trim()}”的记录。` : `No records match “${quickQuerySearch.trim()}”.`)
                      : (isZh ? '当前没有结构化记录，可切回终端查看原始回显。' : 'No structured records available. Switch to Terminal for raw output.')}
                  </p>
                  {quickQuerySearch.trim() && (
                    <button
                      type="button"
                      onClick={() => setQuickQuerySearch('')}
                      className="mt-2 rounded-lg border border-cyan-400/20 px-2.5 py-1.5 text-[11px] font-semibold text-cyan-200 transition-colors hover:bg-cyan-400/10"
                    >
                      {isZh ? '清除搜索' : 'Clear search'}
                    </button>
                  )}
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
            <div className="group/output relative p-4 sm:p-5">
              <div className="mb-4 rounded-2xl border border-white/[0.06] bg-white/[0.02] p-3 sm:p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="flex min-w-0 flex-1 items-start gap-3">
                    <span className="mt-0.5 shrink-0 select-none font-mono text-[11px] font-bold text-emerald-400/60">❯</span>
                    <div className="min-w-0">
                      <p className="mb-1 text-[10px] font-bold uppercase tracking-[0.14em] text-white/30">{isZh ? '执行命令' : 'Executed command'}</p>
                      <code className="netops-terminal-font block break-all text-[12px] leading-relaxed text-emerald-300/80">{quickQueryLabel}</code>
                    </div>
                  </div>
                  {quickQueryOutput && (
                    <div className="flex items-center gap-2 self-start">
                      <span className="text-[10px] uppercase tracking-[0.14em] text-white/25">{isZh ? '导出' : 'Export'}</span>
                      <OutputActions
                        text={quickQueryOutput}
                        filename={`${(quickQueryLabel || 'query').replace(/[^a-zA-Z0-9_-]+/g, '_').slice(0, 40) || 'query'}`}
                        theme="dark"
                        zh={isZh}
                        iconOnly
                      />
                    </div>
                  )}
                </div>
              </div>
              {(quickQueryStructured?.categories?.[0]?.parse_status === 'unmatched' ||
                quickQueryStructured?.categories?.[0]?.parse_status === 'failed' ||
                quickQueryStructured?.categories?.[0]?.parse_status === 'device_error') && (
                <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-indigo-500/20 bg-indigo-500/5 px-4 py-3 text-xs text-indigo-300">
                  <div className="flex items-center gap-2">
                    <span className="text-sm">🧩</span>
                    <span>
                      {isZh
                        ? (quickQueryStructured?.categories?.[0]?.parse_status === 'device_error'
                          ? '设备返回了命令错误回显，请检查 Profile 中的实际命令；前端保留原始回显。'
                          : '该命令当前无匹配的结构化解析模板，前端仅展示原始回显。')
                        : (quickQueryStructured?.categories?.[0]?.parse_status === 'device_error'
                          ? 'The device returned a command error. Check the Profile command; raw output is preserved.'
                          : 'No parsing template matched this command. Raw output is shown.')}
                    </span>
                  </div>
                  <button
                    onClick={() => {
                      if (onOpenDebugger) {
                        const dev = quickQueryStructured.device || {};
                        onOpenDebugger(
                          dev.platform || 'cisco_ios',
                          quickQueryCommands.join('\n'),
                          quickQueryOutput
                        );
                      }
                    }}
                    className="shrink-0 rounded-lg bg-indigo-600/80 hover:bg-indigo-600 px-3 py-1.5 font-semibold text-white transition-all"
                  >
                    {isZh ? '在线调试与创建解析模板' : 'Debug & Create Template'}
                  </button>
                </div>
              )}
              <pre className="netops-terminal-font text-[13px] text-[#e6edf3] leading-[1.75] whitespace-pre-wrap break-all select-text">{quickQueryOutput}</pre>
            </div>
          )}
        </div>
      </div>
    </>
  );
};
