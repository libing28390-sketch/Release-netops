import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { X, Star, History, Terminal, Trash2, ChevronRight, Bookmark } from 'lucide-react';
import type { Device } from '../types';

interface CustomCommandModalProps {
  language: string;
  t: (key: string) => string;
  customCommand: string;
  customCommandVars: string[];
  scriptVars: Record<string, string>;
  batchMode: boolean;
  batchDeviceIds: string[];
  selectedDevice: Device | null;
  isBatchRunning: boolean;
  isTestingConnection: boolean;
  showFavorites: boolean;
  commandFavorites: string[];
  commandHistory: string[];
  onClose: () => void;
  onSubmit: () => void;
  onCustomCommandChange: (value: string) => void;
  onScriptVarChange: (key: string, value: string) => void;
  onToggleFavorite: (command: string) => void;
  isFavorited: (command: string) => boolean;
  onSaveQuickQuery: () => void;
  onToggleFavorites: () => void;
  onUseFavorite: (command: string) => void;
}

const CustomCommandModal: React.FC<CustomCommandModalProps> = ({
  language,
  t,
  customCommand,
  customCommandVars,
  scriptVars,
  batchMode,
  batchDeviceIds,
  selectedDevice,
  isBatchRunning,
  isTestingConnection,
  showFavorites,
  commandFavorites,
  commandHistory,
  onClose,
  onSubmit,
  onCustomCommandChange,
  onScriptVarChange,
  onToggleFavorite,
  isFavorited,
  onSaveQuickQuery,
  onToggleFavorites,
  onUseFavorite,
}) => {
  const [activeTab, setActiveTab] = useState<'favorites' | 'history'>('favorites');
  const canSubmit = (batchMode ? batchDeviceIds.length > 0 : !!selectedDevice) && customCommand.trim() && !(batchMode ? isBatchRunning : isTestingConnection);

  const renderCommandItem = (cmd: string, type: 'favorite' | 'history') => {
    const isFav = isFavorited(cmd);
    
    return (
      <div 
        key={`${type}-${cmd}`}
        className="group relative flex flex-col gap-2 p-3.5 rounded-2xl border border-black/5 bg-white hover:border-cyan-200 hover:shadow-md hover:shadow-cyan-500/5 transition-all duration-300"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <code className="text-[12px] font-mono text-slate-700 leading-relaxed block break-all line-clamp-2 bg-slate-50/50 rounded-lg px-2 py-1.5 border border-slate-100 group-hover:bg-cyan-50/30 group-hover:border-cyan-100/50 transition-colors">
              {cmd}
            </code>
          </div>
          <button
            onClick={() => onToggleFavorite(cmd)}
            className={`p-1.5 rounded-xl transition-all ${isFav ? 'text-amber-400 bg-amber-50 shadow-sm shadow-amber-200/50' : 'text-slate-300 hover:text-amber-400 hover:bg-slate-50'}`}
            title={isFav ? (language === 'zh' ? '取消收藏' : 'Unfavorite') : (language === 'zh' ? '收藏' : 'Favorite')}
          >
            <Star size={14} fill={isFav ? "currentColor" : "none"} strokeWidth={isFav ? 1.5 : 2} />
          </button>
        </div>
        <div className="flex items-center gap-2 mt-1">
          <button
            onClick={() => onUseFavorite(cmd)}
            className="flex-1 flex items-center justify-center gap-2 py-1.5 rounded-xl bg-cyan-500 text-white text-[11px] font-bold hover:bg-cyan-600 shadow-sm shadow-cyan-500/20 active:scale-95 transition-all"
          >
            <ChevronRight size={12} strokeWidth={3} />
            {language === 'zh' ? '填入编辑器' : 'Use Command'}
          </button>
        </div>
      </div>
    );
  };

  return (
    <div
      className="fixed inset-0 bg-black/55 backdrop-blur-sm flex items-center justify-center z-[85] p-4"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.96, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="w-full max-w-4xl max-h-[90vh] rounded-[32px] bg-white shadow-2xl border border-black/5 overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-8 py-6 border-b border-black/5 bg-[linear-gradient(135deg,rgba(0,188,235,0.06),rgba(0,82,122,0.03))]">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-cyan-500 animate-pulse" />
                <p className="text-[10px] font-black uppercase tracking-[0.3em] text-cyan-600/80">
                  {language === 'zh' ? 'DIRECT EXECUTION' : 'DIRECT EXECUTION'}
                </p>
              </div>
              <h3 className="mt-1.5 text-2xl font-black text-slate-800 tracking-tight">
                {language === 'zh' ? '自定义命令' : 'Custom Command'}
              </h3>
            </div>
            <button
              onClick={onClose}
              className="w-10 h-10 rounded-2xl flex items-center justify-center text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-all active:scale-90"
            >
              <X size={20} strokeWidth={2.5} />
            </button>
          </div>
          
          <div className="mt-5 flex items-center gap-4">
            <div className="flex items-center bg-cyan-500/10 border border-cyan-500/20 rounded-2xl px-4 py-2 gap-2.5">
              <Terminal size={14} className="text-cyan-600" />
              <span className="text-[13px] font-bold text-cyan-700">
                {language === 'zh' ? '查询模式' : 'Query Mode'}
              </span>
            </div>
            <div className="h-4 w-px bg-slate-200 mx-1" />
            <span className="text-[12px] font-medium text-slate-500 italic">
              {language === 'zh' ? 'Exec 模式：只读操作，配置变更需走工单流' : 'Exec mode: read-only operations only'}
            </span>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 min-h-0 overflow-auto p-8 bg-[#fdfeff]">
          <div className="grid grid-cols-1 lg:grid-cols-[1.1fr,0.9fr] gap-8">
            {/* Left Column: Editor & Variables */}
            <div className="space-y-6">
              <div className="rounded-3xl border border-black/5 bg-white p-6 shadow-sm ring-1 ring-black/[0.02]">
                <div className="flex items-center justify-between gap-3 mb-4">
                  <div className="flex items-center gap-2">
                    <Bookmark size={14} className="text-slate-400" />
                    <p className="text-[11px] font-black uppercase tracking-[0.2em] text-slate-400">
                      {language === 'zh' ? '命令内容' : 'Command Content'}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      disabled={!customCommand.trim()}
                      onClick={onSaveQuickQuery}
                      className={`px-4 py-2 rounded-xl text-[11px] font-bold border transition-all active:scale-95 ${customCommand.trim()
                        ? 'border-cyan-500/30 text-cyan-600 hover:bg-cyan-50' : 'border-slate-100 text-slate-300 cursor-not-allowed'}`}
                    >
                      {language === 'zh' ? '+ 快捷查询' : '+ Quick Query'}
                    </button>
                  </div>
                </div>
                <textarea
                  value={customCommand}
                  onChange={(e) => onCustomCommandChange(e.target.value)}
                  placeholder={language === 'zh'
                    ? '例如:\nshow ip interface brief\nshow version\ndisplay version'
                    : 'Example:\nshow ip interface brief\nshow version\ndisplay version'}
                  className="w-full min-h-[320px] resize-y rounded-2xl border border-slate-100 bg-slate-900 px-5 py-4 text-[14px] leading-7 text-cyan-50 font-mono outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-500/40 transition-all shadow-inner"
                />
              </div>

              {customCommandVars.length > 0 && (
                <div className="rounded-3xl border border-black/5 bg-white p-6 shadow-sm ring-1 ring-black/[0.02] space-y-4">
                  <div>
                    <p className="text-[11px] font-black uppercase tracking-[0.2em] text-slate-400">
                      {language === 'zh' ? '变量替换' : 'Variable Substitution'}
                    </p>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {customCommandVars.map((key) => (
                      <label key={key} className="space-y-1.5 block">
                        <span className="text-[11px] font-bold text-slate-500 ml-1">{key}</span>
                        <input
                          type="text"
                          value={scriptVars[key] || ''}
                          onChange={(e) => onScriptVarChange(key, e.target.value)}
                          placeholder={language === 'zh' ? `输入 ${key}` : `Enter ${key}`}
                          className="w-full rounded-xl border border-slate-100 bg-slate-50/50 px-4 py-2.5 text-sm outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium"
                        />
                      </label>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Right Column: Targets & Favorites/History */}
            <div className="space-y-6">
              {/* Target Section */}
              <div className="rounded-3xl border border-black/5 bg-white p-6 shadow-sm ring-1 ring-black/[0.02] space-y-4">
                <p className="text-[11px] font-black uppercase tracking-[0.2em] text-slate-400">
                  {language === 'zh' ? '执行目标' : 'Execution Target'}
                </p>
                <div className="rounded-2xl border border-slate-100 bg-slate-50/80 px-4 py-4">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-[13px] font-bold text-slate-800">
                      {batchMode
                        ? (language === 'zh' ? `批量模式 · ${batchDeviceIds.length} 台设备` : `Batch mode · ${batchDeviceIds.length} devices`)
                        : (selectedDevice
                          ? `${selectedDevice.hostname}`
                          : (language === 'zh' ? '未选择设备' : 'No device selected'))}
                    </p>
                    {!batchMode && selectedDevice && (
                      <span className="text-[10px] font-black px-2 py-1 rounded-lg bg-cyan-100 text-cyan-700 font-mono">
                        {selectedDevice.platform || 'unknown'}
                      </span>
                    )}
                  </div>
                  {!batchMode && selectedDevice && (
                    <p className="mt-1 text-[11px] text-slate-400 font-medium">{selectedDevice.ip_address}</p>
                  )}
                </div>
                <div className="rounded-2xl px-4 py-3.5 text-[12px] leading-6 border border-cyan-100 bg-cyan-50/50 text-cyan-700 font-medium">
                  {language === 'zh'
                    ? '当前处于只读模式，系统会自动拦截所有的配置变更命令。'
                    : 'System is in read-only mode. All config modification commands will be intercepted.'}
                </div>
              </div>

              {/* Favorites & History Section */}
              <div className="rounded-3xl border border-black/5 bg-white shadow-sm ring-1 ring-black/[0.02] flex flex-col min-h-[400px]">
                {/* Tab Switcher */}
                <div className="flex p-1.5 bg-slate-100/50 rounded-t-3xl border-b border-slate-100">
                  <button
                    onClick={() => setActiveTab('favorites')}
                    className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-2xl text-[12px] font-bold transition-all ${
                      activeTab === 'favorites' ? 'bg-white text-cyan-600 shadow-sm' : 'text-slate-400 hover:text-slate-600'
                    }`}
                  >
                    <Star size={14} fill={activeTab === 'favorites' ? "currentColor" : "none"} />
                    {language === 'zh' ? '常用收藏' : 'Favorites'}
                  </button>
                  <button
                    onClick={() => setActiveTab('history')}
                    className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-2xl text-[12px] font-bold transition-all ${
                      activeTab === 'history' ? 'bg-white text-cyan-600 shadow-sm' : 'text-slate-400 hover:text-slate-600'
                    }`}
                  >
                    <History size={14} />
                    {language === 'zh' ? '执行历史' : 'History'}
                  </button>
                </div>

                {/* List Container */}
                <div className="p-5 flex-1 min-h-0 overflow-auto max-h-[400px] scrollbar-thin">
                  <AnimatePresence mode="wait">
                    <motion.div
                      key={activeTab}
                      initial={{ opacity: 0, x: activeTab === 'favorites' ? -10 : 10 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: activeTab === 'favorites' ? 10 : -10 }}
                      transition={{ duration: 0.2 }}
                      className="grid grid-cols-1 gap-3"
                    >
                      {activeTab === 'favorites' ? (
                        commandFavorites.length > 0 ? (
                          commandFavorites.map(fav => renderCommandItem(fav, 'favorite'))
                        ) : (
                          <div className="flex flex-col items-center justify-center py-12 px-6 text-center">
                            <div className="w-12 h-12 rounded-2xl bg-slate-50 flex items-center justify-center mb-3">
                              <Star size={24} className="text-slate-200" />
                            </div>
                            <p className="text-[12px] font-bold text-slate-400">{language === 'zh' ? '还没有收藏任何命令' : 'No favorites yet'}</p>
                            <p className="text-[11px] text-slate-300 mt-1">{language === 'zh' ? '点击命令旁的小星星即可收藏' : 'Click the star icon to save'}</p>
                          </div>
                        )
                      ) : (
                        commandHistory.length > 0 ? (
                          commandHistory.map(hist => renderCommandItem(hist, 'history'))
                        ) : (
                          <div className="flex flex-col items-center justify-center py-12 px-6 text-center">
                            <div className="w-12 h-12 rounded-2xl bg-slate-50 flex items-center justify-center mb-3">
                              <History size={24} className="text-slate-200" />
                            </div>
                            <p className="text-[12px] font-bold text-slate-400">{language === 'zh' ? '历史记录为空' : 'History is empty'}</p>
                            <p className="text-[11px] text-slate-300 mt-1">{language === 'zh' ? '执行过的命令会出现在这里' : 'Executed commands will appear here'}</p>
                          </div>
                        )
                      )}
                    </motion.div>
                  </AnimatePresence>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-8 py-6 border-t border-black/5 bg-slate-50/50 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
             <div className="w-1.5 h-1.5 rounded-full bg-slate-300" />
             <p className="text-[12px] font-bold text-slate-400">
               {batchMode
                 ? (language === 'zh' ? `即将下发至 ${batchDeviceIds.length} 台设备` : `Run on ${batchDeviceIds.length} devices`)
                 : (language === 'zh' ? '结果将实时呈现在终端视图中' : 'Results will appear in terminal')}
             </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              className="px-6 py-2.5 rounded-2xl text-[13px] font-bold text-slate-500 hover:bg-slate-100 hover:text-slate-700 transition-all active:scale-95"
            >
              {t('cancel')}
            </button>
            <button
              onClick={onSubmit}
              disabled={!canSubmit}
              className={`px-8 py-3 rounded-2xl text-[13px] font-black text-white shadow-xl transition-all active:scale-95 ${
                canSubmit
                  ? 'bg-slate-800 hover:bg-slate-900 shadow-slate-200'
                  : 'bg-slate-200 text-slate-400 cursor-not-allowed shadow-none'
              }`}
            >
              {batchMode
                ? (isBatchRunning
                  ? (language === 'zh' ? '批量执行中...' : 'Running Batch...')
                  : (language === 'zh' ? `批量查询 (${batchDeviceIds.length})` : `Run Batch (${batchDeviceIds.length})`))
                : (isTestingConnection
                  ? (language === 'zh' ? '执行中...' : 'Running...')
                  : (language === 'zh' ? '立即执行' : 'Run Query'))}
            </button>
          </div>
        </div>
      </motion.div>
    </div>
  );
};

export default CustomCommandModal;