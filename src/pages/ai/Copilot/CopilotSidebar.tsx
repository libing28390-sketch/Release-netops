import React, { useState } from 'react';
import { Plus, Search, MessageSquare, Trash2, Settings, User, Sparkles } from 'lucide-react';

export interface ChatSession {
  id: string;
  title: string;
  updatedAt: string;
  messages: any[];
}

interface CopilotSidebarProps {
  sessions: ChatSession[];
  activeSessionId: string;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onDeleteSession: (id: string, e: React.MouseEvent) => void;
}

export const CopilotSidebar: React.FC<CopilotSidebarProps> = ({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewSession,
  onDeleteSession,
}) => {
  const [searchTerm, setSearchTerm] = useState('');

  const filteredSessions = sessions.filter((s) =>
    s.title.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <aside className="w-64 bg-[#f9f9f8] dark:bg-gray-900 border-r border-gray-200/70 dark:border-gray-800 flex flex-col h-full select-none">
      {/* App Branding & New Chat */}
      <div className="p-3.5 space-y-3">
        <div className="flex items-center justify-between px-2">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-lg bg-indigo-600 flex items-center justify-center text-white shadow-sm">
              <Sparkles className="w-3.5 h-3.5" />
            </div>
            <span className="font-bold text-gray-900 dark:text-white text-sm tracking-tight">Nexora Copilot</span>
          </div>
        </div>

        <button
          onClick={onNewSession}
          className="w-full py-2 px-3 bg-white dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700/80 text-gray-800 dark:text-gray-100 border border-gray-200/80 dark:border-gray-700 rounded-xl font-medium text-xs flex items-center justify-center gap-2 shadow-xs transition"
        >
          <Plus className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
          <span>新建对话</span>
        </button>

        {/* Search */}
        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-gray-400" />
          <input
            type="text"
            placeholder="搜索历史对话..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 bg-gray-200/50 dark:bg-gray-800/60 border-none rounded-lg text-xs text-gray-700 dark:text-gray-200 focus:outline-none focus:ring-1 focus:ring-indigo-500 placeholder-gray-400"
          />
        </div>
      </div>

      {/* Sessions Grouped List */}
      <div className="flex-1 overflow-y-auto px-2 space-y-3 text-xs">
        <div>
          <div className="px-2 py-1 text-[11px] font-semibold text-gray-400 uppercase tracking-wider">
            对话历史
          </div>
          <div className="space-y-0.5 mt-1">
            {filteredSessions.length === 0 ? (
              <div className="px-3 py-4 text-center text-gray-400 text-xs">
                暂无匹配对话
              </div>
            ) : (
              filteredSessions.map((s) => {
                const isActive = s.id === activeSessionId;
                return (
                  <div
                    key={s.id}
                    onClick={() => onSelectSession(s.id)}
                    className={`group px-3 py-2.5 rounded-xl cursor-pointer transition flex items-center justify-between ${
                      isActive
                        ? 'bg-gray-200/70 dark:bg-gray-800 font-semibold text-gray-900 dark:text-white'
                        : 'text-gray-600 dark:text-gray-400 hover:bg-gray-200/40 dark:hover:bg-gray-800/40'
                    }`}
                  >
                    <div className="flex items-center gap-2 truncate pr-2">
                      <MessageSquare className={`w-3.5 h-3.5 flex-shrink-0 ${isActive ? 'text-indigo-600 dark:text-indigo-400' : 'text-gray-400'}`} />
                      <span className="truncate">{s.title || '新对话'}</span>
                    </div>
                    <button
                      onClick={(e) => onDeleteSession(s.id, e)}
                      className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 p-1 transition"
                      title="删除对话"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </aside>
  );
};
