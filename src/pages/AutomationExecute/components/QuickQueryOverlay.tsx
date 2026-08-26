import React, { useState, useEffect, useMemo } from 'react';
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
  version?: string;
  score: number;
}

const resolveSuggestionPlatform = (device: Pick<Device, 'platform' | 'version'>): string => {
  const platform = String(device.platform || '').trim().toLowerCase();
  const version = String(device.version || '').trim().toLowerCase();

  if (platform === 'hp_comware' || platform.includes('h3c_comware_v5')) return 'h3c_comware_v5';
  if (platform.includes('h3c_comware_v7')) return 'h3c_comware_v7';
  if (platform === 'h3c_comware9' || platform.includes('h3c_comware_v9')) return 'h3c_comware_v9';

  if (platform === 'h3c_comware' || platform === 'h3c' || platform === 'comware') {
    const majorVersion = version.match(/(?:^|[^\d])([579])(?:\.|\b)/)?.[1];
    return majorVersion ? `h3c_comware_v${majorVersion}` : 'h3c_comware';
  }

  return platform;
};

const suggestionVariantFromFilename = (filename: string): string => {
  const match = String(filename || '').toLowerCase().match(/^(h3c_comware_v[579])_/);
  return match?.[1] || '';
};

const isConcreteH3cVariant = (value: string): boolean => /^h3c_comware_v[579]$/.test(value);

const formatSuggestionScope = (platform: string, isZh: boolean): string => {
  const h3cMatch = platform.match(/^h3c_comware_v([579])$/);
  if (h3cMatch) return `H3C Comware V${h3cMatch[1]}`;
  if (platform === 'h3c_comware') return isZh ? 'H3C Comware 平台族' : 'H3C Comware family';
  return platform.replace(/_/g, ' ') || (isZh ? '当前设备平台' : 'Target platform');
};

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
  const [suggestionsQueried, setSuggestionsQueried] = useState(false);
  const [selectedSuggestion, setSelectedSuggestion] = useState<CommandSuggestion | null>(null);
  const targetSignature = targetDevices.map((device) => `${device.id}:${device.platform || ''}:${device.version || ''}`).join('|');
  const targetSuggestionPlatforms = useMemo(
    () => Array.from(new Set(targetDevices.map(resolveSuggestionPlatform).filter(Boolean))),
    [targetSignature],
  );
  const targetSuggestionPlatformSignature = targetSuggestionPlatforms.join('|');
  const suggestionScopeLabel = targetSuggestionPlatforms.length === 1
    ? formatSuggestionScope(targetSuggestionPlatforms[0], isZh)
    : (isZh ? '按选中设备版本分别匹配' : 'Match each selected device version');
  const isZteTarget = targetDevices.length > 0 && targetDevices.every(
    (device) => String(device.platform || '').trim().toLowerCase() === 'zte_zxros'
  );

  // Clear previous command when the overlay is triggered/re-opened
  useEffect(() => {
    if (hasTargets) {
      setCustomCommand(isZteTarget ? 'show lldp neighbor' : '');
      setSelectedSuggestion(null);
    }
  }, [hasTargets, isZteTarget, targetSignature]);

  useEffect(() => {
    const query = customCommand.trim();
    if (!hasTargets || query.length < 2) {
      setSuggestions([]);
      setSuggestionsLoading(false);
      setSuggestionsQueried(false);
      return;
    }
    if (selectedSuggestion && query === selectedSuggestion.command.trim()) {
      return;
    }

    const controller = new AbortController();
    setSuggestions([]);
    setSuggestionsQueried(false);
    const timer = window.setTimeout(async () => {
      const platforms = targetSuggestionPlatforms;
      if (platforms.length === 0) {
        setSuggestionsQueried(true);
        return;
      }
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
            const itemPlatform = String(item.platform || '').trim().toLowerCase();
            const itemVersion = String(item.version || '').trim().toLowerCase();
            const itemVariant = suggestionVariantFromFilename(item.filename)
              || (itemPlatform === 'h3c_comware' && /^v[579]$/.test(itemVersion) ? `h3c_comware_${itemVersion}` : itemPlatform);
            const concreteTargetVariants = new Set(platforms.filter(isConcreteH3cVariant));
            // Never leak a different concrete H3C grammar into the candidate list.
            // A versionless family template remains an explicit, safe fallback.
            if (concreteTargetVariants.size > 0 && isConcreteH3cVariant(itemVariant) && !concreteTargetVariants.has(itemVariant)) {
              return;
            }
            const key = `${item.platform}:${item.filename || item.command}`;
            if (!unique.has(key)) unique.set(key, item);
          });
        setSuggestions(Array.from(unique.values()).slice(0, 12));
        setSuggestionsQueried(true);
      } catch (error: any) {
        if (error?.name !== 'AbortError') {
          setSuggestions([]);
          setSuggestionsQueried(false);
        }
      } finally {
        if (!controller.signal.aborted) setSuggestionsLoading(false);
      }
    }, 180);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [customCommand, hasTargets, selectedSuggestion, targetSuggestionPlatformSignature]);

  const showSuggestionPanel = hasTargets && !selectedSuggestion && customCommand.trim().length >= 2 && (suggestionsLoading || suggestionsQueried);

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
          className="fixed inset-0 z-[60] flex flex-col bg-slate-900/45 backdrop-blur-md p-4 sm:p-5"
        >
          <div className="flex-1 min-h-0 flex flex-col max-w-7xl mx-auto w-full bg-slate-50 rounded-[1.75rem] shadow-[0_24px_80px_rgba(15,23,42,0.24)] border border-white/80 overflow-hidden">
            {/* Header: Target Confirmation */}
            <div className="flex-shrink-0 px-6 py-4 bg-white border-b border-slate-200/80 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-cyan-500 flex items-center justify-center shadow-md shadow-cyan-500/20">
                  <Terminal size={20} className="text-white" />
                </div>
                <div>
                  <h3 className="text-lg font-black text-slate-800 tracking-tight">
                    {isZh ? '确认目标并选择操作' : 'Confirm Targets & Execute'}
                  </h3>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                    <p className="text-xs text-slate-500 font-medium">
                      {isZh
                        ? `已选中 ${targetDevices.length} 台设备，请确认后点击下方工具执行`
                        : `${targetDevices.length} devices selected. Confirm and click a tool below.`}
                    </p>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleClearSelection}
                  className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-white border border-slate-200 text-slate-500 hover:text-red-500 hover:border-red-100 hover:bg-red-50 transition-all font-bold text-xs shadow-sm"
                >
                  <X size={16} />
                  {isZh ? '重选设备' : 'Reselect Devices'}
                </button>
              </div>
            </div>

            {/* Device List Recap (Confirmation Bar) */}
            <div className="flex-shrink-0 px-6 py-3 bg-slate-50 border-b border-slate-200/80 overflow-hidden">
              <div className="flex gap-2 overflow-x-auto pb-0.5">
                {targetDevices.map((dev) => (
                  <div key={dev.id} className="flex shrink-0 items-center gap-2 px-3 py-1.5 rounded-lg bg-white border border-slate-200 shadow-sm">
                    <span className={`w-1.5 h-1.5 rounded-full ${dev.status === 'online' ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                    <span className="text-xs font-bold text-slate-700">{dev.hostname}</span>
                    <span className="text-[10px] font-mono text-slate-400">{dev.ip_address}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Custom Command Input Section */}
            <div className="flex-shrink-0 px-6 py-4 bg-white border-b border-slate-200/80 flex flex-col sm:flex-row sm:items-end gap-3">
              <div className="flex-1">
                <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
                  <div>
                    <label className="block text-xs font-bold uppercase tracking-wider text-slate-500">
                      {isZh ? '✏️ 自定义查看命令查询' : '✏️ Custom Check Command'}
                    </label>
                    <p className="mt-1 text-[10px] font-medium text-slate-400">
                      {isZh ? '仅支持只读查看指令，如 show/display；候选不跨具体版本回退' : 'Read-only show/display commands; suggestions never cross concrete versions'}
                    </p>
                  </div>
                  <span className="rounded-full border border-cyan-100 bg-cyan-50 px-2.5 py-1 text-[10px] font-bold text-cyan-700">
                    {isZh ? `匹配范围：${suggestionScopeLabel}` : `Scope: ${suggestionScopeLabel}`}
                  </span>
                </div>
                <div className="relative">
                  <input
                    type="text"
                    value={customCommand}
                    onChange={(e) => {
                      setCustomCommand(e.target.value);
                      setSelectedSuggestion(null);
                    }}
                    placeholder={isZh ? '例如: display current-configuration 或 show version' : 'e.g. show version or display ospf peer'}
                    className="netops-terminal-font w-full rounded-xl border border-slate-200 bg-slate-50 py-2.5 pl-4 pr-20 text-sm font-semibold text-slate-800 shadow-inner transition-all focus:border-cyan-500 focus:bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        handleRunCustom();
                      }
                    }}
                  />
                  {selectedSuggestion && (
                    <button
                      type="button"
                      aria-label={isZh ? '清除已选模板' : 'Clear selected template'}
                      title={isZh ? `清除已选模板：${selectedSuggestion.filename}` : `Clear selected template: ${selectedSuggestion.filename}`}
                      onClick={() => {
                        setSelectedSuggestion(null);
                        setCustomCommand('');
                      }}
                      className="absolute right-8 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-200 hover:text-slate-700"
                    >
                      <X size={13} />
                    </button>
                  )}
                  <div className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-bold text-slate-400 font-mono select-none">
                    ↵
                  </div>
                  {showSuggestionPanel && (
                    <div className="absolute left-0 right-0 top-full z-50 mt-2 overflow-hidden rounded-xl border border-cyan-100 bg-white shadow-2xl shadow-slate-900/15">
                      {suggestionsLoading && suggestions.length === 0 ? (
                        <div className="px-4 py-3 text-xs font-medium text-slate-400">
                          {isZh ? `正在匹配 ${suggestionScopeLabel} 的 TextFSM 模板…` : `Searching TextFSM templates for ${suggestionScopeLabel}…`}
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
                                setSuggestionsQueried(false);
                                setSelectedSuggestion(suggestion);
                              }}
                              className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left hover:bg-cyan-50"
                            >
                              <span className="min-w-0">
                                <span className="netops-terminal-font block truncate text-xs font-bold text-slate-700">{suggestion.command}</span>
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
                          <p>{isZh ? '当前设备版本未找到匹配模板' : 'No matching template for the device version'}</p>
                          <p className="mt-1 text-[10px] font-normal text-slate-300">
                            {isZh ? '仍可执行命令，并在结果中查看原始回显或进入解析调试。' : 'You can still run the command and inspect raw output or open the parser debugger.'}
                          </p>
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
                  className="w-full sm:w-auto px-5 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-500 hover:from-cyan-600 hover:to-blue-600 text-white font-bold text-sm shadow-md shadow-cyan-500/10 hover:shadow-cyan-500/20 active:scale-[0.98] transition-all disabled:opacity-40 flex items-center justify-center gap-2"
                >
                  <Zap size={15} />
                  {selectedSuggestion
                    ? (isZh ? '执行已选模板' : 'Run Selected Template')
                    : (isZh ? '执行查询' : 'Run Query')}
                </button>
              </div>
            </div>

            {/* Tools Grid */}
            <div className="flex-1 min-h-0 overflow-auto p-6 custom-scrollbar">
              <div className="space-y-6">
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
                    <div key={groupId} className="space-y-3">
                      <div className="flex items-center gap-3">
                        <span className={`text-sm font-black uppercase tracking-[0.2em] ${groupMeta.text}`}>
                          {groupMeta.icon} {groupMeta.label}
                        </span>
                        <div className="h-px flex-1 bg-slate-100" />
                      </div>
                      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
                        {items.map((cmd, idx) => (
                          <button
                            key={idx}
                            disabled={quickQueryRunning}
                            onClick={() => {
                              onRunQuickQuery(isZh ? cmd.label : cmd.labelEn, cmd.cmds, cmd.operationalCategory, 'normal');
                            }}
                            className="group relative flex items-center gap-3 p-3 rounded-xl border border-slate-200/80 bg-white hover:border-cyan-400 hover:shadow-lg hover:shadow-cyan-500/10 hover:-translate-y-0.5 transition-all duration-300 disabled:opacity-40"
                          >
                            <div
                              className={`w-10 h-10 rounded-lg ${groupMeta.bg} ${groupMeta.border} border flex items-center justify-center text-xl group-hover:scale-105 transition-transform flex-shrink-0`}
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
            <div className="flex-shrink-0 px-6 py-3 bg-white text-[11px] text-slate-400 flex items-center gap-2 border-t border-slate-200/80">
              <Zap size={12} className="text-amber-400" />
              {isZh ? '点击上方图标将立即开始执行快捷查询。' : 'Click any icon to execute a quick query.'}
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};
