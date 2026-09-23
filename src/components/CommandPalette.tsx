import React from 'react';
import { motion } from 'motion/react';
import { Pin, Search } from 'lucide-react';

interface CommandPaletteItem {
  path: string;
  label: string;
  group: string;
}

interface CommandPaletteProps {
  open: boolean;
  language: string;
  query: string;
  items: CommandPaletteItem[];
  pinnedPaths: string[];
  currentPath: string;
  onClose: () => void;
  onQueryChange: (value: string) => void;
  onNavigate: (path: string) => void;
  onTogglePin: (path: string) => void;
}

const CommandPalette: React.FC<CommandPaletteProps> = ({
  open,
  language,
  query,
  items,
  pinnedPaths,
  currentPath,
  onClose,
  onQueryChange,
  onNavigate,
  onTogglePin,
}) => {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[200] flex items-start justify-center pt-[15vh] bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, y: 12, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        className="w-full max-w-lg mx-4 rounded-2xl shadow-2xl border border-white/10 bg-[#131720] overflow-hidden"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-3 px-4 py-3 border-b border-white/10">
          <Search size={16} className="text-white/40 shrink-0" />
          <input
            autoFocus
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder={language === 'zh' ? '搜索页面…' : 'Go to page…'}
            className="flex-1 bg-transparent text-white text-sm placeholder-white/30 outline-none"
          />
          <kbd className="hidden sm:block text-[10px] text-white/25 border border-white/10 rounded px-1.5 py-0.5 font-mono">ESC</kbd>
        </div>

        <ul className="max-h-80 overflow-y-auto py-2">
          {items.length === 0 ? (
            <li className="px-4 py-8 text-center text-white/30 text-sm">
              {language === 'zh' ? '没有匹配的页面' : 'No results found'}
            </li>
          ) : (
            items.map((item) => {
              const active = currentPath === item.path;
              const isPinned = pinnedPaths.includes(item.path);

              return (
                <li key={item.path}>
                  <div className={`flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-white/5 ${active ? 'text-[#63dbf6]' : 'text-white/80'}`}>
                    <button
                      type="button"
                      className="min-w-0 flex-1 text-left"
                      onClick={() => onNavigate(item.path)}
                    >
                      <span className="block truncate text-sm">{item.label}</span>
                    </button>
                    <span className="text-[11px] text-white/30 shrink-0">{item.group}</span>
                    <button
                      type="button"
                      onClick={() => onTogglePin(item.path)}
                      title={isPinned ? (language === 'zh' ? '取消固定' : 'Unpin') : (language === 'zh' ? '固定到侧栏' : 'Pin to sidebar')}
                      className={`shrink-0 p-1 rounded hover:bg-white/10 transition-colors ${isPinned ? 'text-[#00bceb]' : 'text-white/20 hover:text-white/60'}`}
                    >
                      <Pin size={12} />
                    </button>
                  </div>
                </li>
              );
            })
          )}
        </ul>

        <div className="px-4 py-2 border-t border-white/5 flex items-center gap-4 text-[11px] text-white/25">
          <span className="flex items-center gap-1"><kbd className="border border-white/10 rounded px-1 py-0.5 font-mono">↵</kbd> {language === 'zh' ? '跳转' : 'go'}</span>
          <span className="flex items-center gap-1"><kbd className="border border-white/10 rounded px-1 py-0.5 font-mono">ESC</kbd> {language === 'zh' ? '关闭' : 'close'}</span>
          <span className="ml-auto flex items-center gap-1"><kbd className="border border-white/10 rounded px-1 py-0.5 font-mono">Ctrl K</kbd> {language === 'zh' ? '切换' : 'toggle'}</span>
        </div>
      </motion.div>
    </div>
  );
};

export default CommandPalette;