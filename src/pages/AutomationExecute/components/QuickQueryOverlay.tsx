import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Terminal, X, Zap } from 'lucide-react';
import type { Device } from '../../../types';

interface QuickQueryOverlayProps {
  isZh: boolean;
  targetDevices: Device[];
  handleClearSelection: () => void;
  queryPresets: Array<{ icon: string; label: string; labelEn: string; cmds: string; group: string; scope: string; operationalCategory?: string }>;
  quickQueryRunning: boolean;
  onRunQuickQuery: (label: string, commands: string, operationalCategory?: string, authRole?: string) => void;
  hasTargets: boolean;
}

interface CommandSuggestion {
  platform: string;
  command: string;
  filename: string;
  source: 'builtin' | 'custom' | string;
  score: number;
}

export const QuickQueryOverlay: React.FC<QuickQueryOverlayProps> = ({
  isZh,
  targetDevices,
  handleClearSelection,
  queryPresets,
  quickQueryRunning,
  onRunQuickQuery,
  hasTargets,
}) => {
  const [customCommand, setCustomCommand] = useState('');
  const [suggestions, setSuggestions] = useState<CommandSuggestion[]>([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);

  // Clear previous command when the overlay is triggered/re-opened
  useEffect(() => {
    if (hasTargets) {
      setCustomCommand('');
    }
  }, [hasTargets]);

  useEffect(() => {
    const query = customCommand.trim();
    if (!hasTargets || query.length < 2) {
      setSuggestions([]);
      setSuggestionsLoading(false);
      return;
    }

    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      const platforms = Array.from(new Set(targetDevices.map((device) => device.platform).filter(Boolean)));
      if (platforms.length === 0) return;
      setSuggestionsLoading(true);
      try {
        const token = localStorage.getItem('netops_token');
        const headers = token ? { Authorization: `Bearer ${token}` } : undefined;
        const responses = await Promise.all(platforms.map((platform) =>
          fetch(`/api/textfsm/command-suggestions?platform=${encodeURIComponent(platform)}&query=${encodeURIComponent(query)}&limit=8`, {
            headers,
            signal: controller.signal,
          }).then((response) => response.ok ? response.json() : null)
        ));
        const unique = new Map<string, CommandSuggestion>();
        responses.flatMap((response) => Array.isArray(response?.data) ? response.data : [])
          .forEach((item: CommandSuggestion) => {
            const key = `${item.platform}:${item.command}`;
            if (!unique.has(key)) unique.set(key, item);
          });
        setSuggestions(Array.from(unique.values()).slice(0, 12));
      } catch (error: any) {
        if (error?.name !== 'AbortError') setSuggestions([]);
      } finally {
        if (!controller.signal.aborted) setSuggestionsLoading(false);
      }
    }, 180);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [customCommand, hasTargets, targetDevices]);

  const handleRunCustom = () => {
    if (!customCommand.trim()) return;
    onRunQuickQuery(
      isZh ? '自定义命令查询' : 'Custom Command Query',
      customCommand.trim(),
      'custom_command',
      'normal'
    );
  };

  return (
    <AnimatePresence>
      {hasTargets && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[60] flex flex-col bg-slate-900/40 backdrop-blur-md p-6"
        >
          <div className="flex-1 flex flex-col max-w-6xl mx-auto w-full bg-white rounded-[2.5rem] shadow-2xl border border-white/20 overflow-hidden">
            {/* Header: Target Confirmation */}
            <div className="flex-shrink-0 px-8 py-6 bg-gradient-to-r from-slate-50 to-white border-b border-gray-100 flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 rounded-2xl bg-cyan-500 flex items-center justify-center shadow-lg shadow-cyan-500/20">
                  <Terminal size={24} className="text-white" />
                </div>
                <div>
                  <h3 className="text-xl font-black text-slate-800 tracking-tight">
                    {isZh ? '确认目标并选择操作' : 'Confirm Targets & Execute'}
                  </h3>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                    <p className="text-sm text-slate-500 font-medium">
                      {isZh
                        ? `已选中 ${targetDevices.length} 台设备，请确认后点击下方工具执行`
                        : `${targetDevices.length} devices selected. Confirm and click a tool below.`}
                    </p>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={handleClearSelection}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-2xl bg-white border border-gray-200 text-slate-500 hover:text-red-500 hover:border-red-100 hover:bg-red-50 transition-all font-bold text-sm shadow-sm"
                >
                  <X size={16} />
                  {isZh ? '重选设备' : 'Reselect Devices'}
                </button>
              </div>
            </div>

            {/* Device List Recap (Confirmation Bar) */}
            <div className="flex-shrink-0 px-8 py-4 bg-slate-50/50 border-b border-gray-100 overflow-hidden">
              <div className="flex flex-wrap gap-2">
                {targetDevices.map((dev) => (
                  <div key={dev.id} className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-white border border-slate-200/60 shadow-sm">
                    <span className={`w-1.5 h-1.5 rounded-full ${dev.status === 'online' ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                    <span className="text-xs font-bold text-slate-700">{dev.hostname}</span>
                    <span className="text-[10px] font-mono text-slate-400">{dev.ip_address}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Custom Command Input Section */}
            <div className="flex-shrink-0 px-8 py-5 bg-slate-50 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center gap-4">
              <div className="flex-1">
                <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">
                  {isZh ? '✏️ 自定义查看命令查询 (仅支持只读查看指令，如 show/display 等)' : '✏️ Custom Check Command (e.g. show/display)'}
                </label>
                <div className="relative">
                  <input
                    type="text"
                    value={customCommand}
                    onChange={(e) => setCustomCommand(e.target.value)}
                    placeholder={isZh ? '例如: display current-configuration 或 show version' : 'e.g. show version or display ospf peer'}
                    className="w-full pl-4 pr-16 py-3 rounded-xl border border-slate-200 bg-white text-slate-800 text-sm font-semibold shadow-inner focus:outline-none focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/20 transition-all font-mono"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        handleRunCustom();
                      }
                    }}
                  />
                  <div className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-bold text-slate-400 font-mono select-none">
                    ↵
                  </div>
                  {(suggestionsLoading || suggestions.length > 0) && (
                    <div className="absolute left-0 right-0 top-full z-20 mt-2 overflow-hidden rounded-xl border border-cyan-100 bg-white shadow-xl shadow-slate-900/10">
                      {suggestionsLoading && suggestions.length === 0 ? (
                        <div className="px-4 py-3 text-xs font-medium text-slate-400">
                          {isZh ? '正在匹配已有 TextFSM 模板…' : 'Searching existing TextFSM templates…'}
                        </div>
                      ) : suggestions.length > 0 ? (
                        <div className="max-h-64 overflow-auto py-1">
                          {suggestions.map((suggestion) => (
                            <button
                              key={`${suggestion.platform}:${suggestion.filename}`}
                              type="button"
                              onMouseDown={(event) => event.preventDefault()}
                              onClick={() => {
                                setCustomCommand(suggestion.command);
                                setSuggestions([]);
                              }}
                              className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left hover:bg-cyan-50"
                            >
                              <span className="min-w-0">
                                <span className="block truncate font-mono text-xs font-bold text-slate-700">{suggestion.command}</span>
                                <span className="mt-0.5 block truncate text-[10px] text-slate-400">{suggestion.filename}</span>
                              </span>
                              <span className={`flex-shrink-0 rounded-md px-1.5 py-1 text-[9px] font-bold uppercase ${suggestion.source === 'custom' ? 'bg-amber-50 text-amber-600' : 'bg-slate-100 text-slate-500'}`}>
                                {suggestion.source === 'custom' ? (isZh ? '自定义' : 'Custom') : (isZh ? '内置' : 'Built-in')}
                              </span>
                            </button>
                          ))}
                        </div>
                      ) : (
                        <div className="px-4 py-3 text-xs font-medium text-slate-400">
                          {isZh ? '当前设备平台未找到匹配模板' : 'No matching template for the target platform'}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
              <div className="flex-shrink-0 sm:self-end">
                <button
                  disabled={quickQueryRunning || !customCommand.trim()}
                  onClick={handleRunCustom}
                  className="w-full sm:w-auto px-6 py-3 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-500 hover:from-cyan-600 hover:to-blue-600 text-white font-bold text-sm shadow-md shadow-cyan-500/10 hover:shadow-cyan-500/20 active:scale-[0.98] transition-all disabled:opacity-40 flex items-center justify-center gap-2"
                >
                  <Zap size={15} />
                  {isZh ? '执行查询' : 'Run Query'}
                </button>
              </div>
            </div>

            {/* Tools Grid */}
            <div className="flex-1 overflow-auto p-8 custom-scrollbar">
              <div className="space-y-8">
                {Object.entries(
                  queryPresets.reduce((acc: Record<string, typeof queryPresets>, item) => {
                    if (!acc[item.group]) acc[item.group] = [];
                    acc[item.group].push(item);
                    return acc;
                  }, {})
                ).map(([groupId, items]) => {
                  const groupMeta =
                    groupId === 'net'
                      ? { label: isZh ? '基础网络查询' : 'Network', icon: '🌐', bg: 'bg-cyan-50', text: 'text-cyan-600', border: 'border-cyan-100' }
                      : groupId === 'route'
                      ? { label: isZh ? '路由协议分析' : 'Routing', icon: '🗺️', bg: 'bg-indigo-50', text: 'text-indigo-600', border: 'border-indigo-100' }
                      : groupId === 'sys'
                      ? { label: isZh ? '系统状态监控' : 'System', icon: '⚙️', bg: 'bg-slate-50', text: 'text-slate-600', border: 'border-slate-100' }
                      : { label: isZh ? '个人常用收藏' : 'Favorites', icon: '⭐', bg: 'bg-amber-50', text: 'text-amber-600', border: 'border-amber-100' };

                  return (
                    <div key={groupId} className="space-y-4">
                      <div className="flex items-center gap-3">
                        <span className={`text-sm font-black uppercase tracking-[0.2em] ${groupMeta.text}`}>
                          {groupMeta.icon} {groupMeta.label}
                        </span>
                        <div className="h-px flex-1 bg-slate-100" />
                      </div>
                      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
                        {items.map((cmd, idx) => (
                          <button
                            key={idx}
                            disabled={quickQueryRunning}
                            onClick={() => {
                              onRunQuickQuery(isZh ? cmd.label : cmd.labelEn, cmd.cmds, cmd.operationalCategory, 'normal');
                            }}
                            className="group relative flex items-center gap-4 p-4 rounded-2xl border border-slate-100 bg-white hover:border-cyan-400 hover:shadow-xl hover:shadow-cyan-500/10 hover:-translate-y-1 transition-all duration-300 disabled:opacity-40"
                          >
                            <div
                              className={`w-12 h-12 rounded-xl ${groupMeta.bg} ${groupMeta.border} border flex items-center justify-center text-2xl group-hover:scale-110 transition-transform flex-shrink-0`}
                            >
                              {cmd.icon}
                            </div>
                            <div className="min-w-0 text-left">
                              <p className="text-[13px] font-black text-slate-700 group-hover:text-cyan-700 transition-colors">
                                {isZh ? cmd.label : cmd.labelEn}
                              </p>
                              <p className="text-[10px] text-slate-400 font-bold mt-0.5 font-mono uppercase tracking-wider">
                                {cmd.operationalCategory || 'CLI'}
                              </p>
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Footer: Tips */}
            <div className="flex-shrink-0 px-8 py-4 bg-slate-50 text-[11px] text-slate-400 flex items-center gap-2 border-t border-slate-100">
              <Zap size={12} className="text-amber-400" />
              {isZh ? '点击上方图标将立即开始执行快捷查询。' : 'Click any icon to execute a quick query.'}
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};
