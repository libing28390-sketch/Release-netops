import React, { useState } from 'react';
import {
  Archive,
  ArchiveRestore,
  Check,
  MessageSquare,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Plus,
  Search,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import { ActionButton } from '../../../components/ui/ActionIconButton';

export interface ChatSession {
  id: string;
  title: string;
  updatedAt: string;
  messages: any[];
  status?: 'active' | 'archived';
  created_at?: string;
  updated_at?: string;
}

interface CopilotSidebarProps {
  sessions: ChatSession[];
  activeSessionId: string;
  collapsed: boolean;
  showArchived: boolean;
  onToggleCollapsed: () => void;
  onToggleArchived: () => void;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onRenameSession: (id: string, title: string) => void | Promise<void>;
  onArchiveSession: (id: string, archived: boolean) => void | Promise<void>;
  onDeleteSession: (id: string) => void | Promise<void>;
}

export const CopilotSidebar: React.FC<CopilotSidebarProps> = ({
  sessions,
  activeSessionId,
  collapsed,
  showArchived,
  onToggleCollapsed,
  onToggleArchived,
  onSelectSession,
  onNewSession,
  onRenameSession,
  onArchiveSession,
  onDeleteSession,
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [menuSessionId, setMenuSessionId] = useState<string | null>(null);
  const [renameSessionId, setRenameSessionId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');

  const filteredSessions = sessions
    .filter((session) => (showArchived ? session.status === 'archived' : session.status !== 'archived'))
    .filter((session) => session.title.toLowerCase().includes(searchTerm.trim().toLowerCase()));

  const beginRename = (session: ChatSession) => {
    setMenuSessionId(null);
    setRenameSessionId(session.id);
    setRenameValue(session.title || '新对话');
  };

  const submitRename = async (sessionId: string) => {
    const value = renameValue.trim();
    if (value) await onRenameSession(sessionId, value);
    setRenameSessionId(null);
  };

  const handleDelete = async (session: ChatSession) => {
    setMenuSessionId(null);
    if (window.confirm(`确定删除“${session.title || '新对话'}”吗？删除后无法恢复。`)) {
      await onDeleteSession(session.id);
    }
  };

  return (
    <aside
      className={`${collapsed ? 'w-14' : 'w-64'} shrink-0 min-h-0 bg-[#f9f9f8] dark:bg-gray-900 border-r border-gray-200/70 dark:border-gray-800 flex flex-col h-full select-none transition-[width] duration-200`}
    >
      <div className={`${collapsed ? 'p-2' : 'p-3.5'} space-y-3`}>
        <div className={`flex items-center ${collapsed ? 'justify-center' : 'justify-between'} px-1`}>
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-7 h-7 rounded-lg bg-indigo-600 flex items-center justify-center text-white shadow-sm shrink-0">
              <Sparkles className="w-3.5 h-3.5" />
            </div>
            {!collapsed && <span className="font-bold text-gray-900 dark:text-white text-sm tracking-tight truncate">Nexora Copilot</span>}
          </div>
          {!collapsed && (
            <button
              type="button"
              onClick={onToggleCollapsed}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-200/60 dark:hover:bg-gray-800 transition"
              title="折叠侧栏"
              aria-label="折叠侧栏"
            >
              <PanelLeftClose className="w-4 h-4" />
            </button>
          )}
        </div>

        <button
          type="button"
          onClick={onNewSession}
          className={`${collapsed ? 'w-10 h-10 mx-auto' : 'w-full py-2 px-3'} bg-white dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700/80 text-gray-800 dark:text-gray-100 border border-gray-200/80 dark:border-gray-700 rounded-xl font-medium text-xs flex items-center justify-center gap-2 shadow-xs transition`}
          title="新建对话"
        >
          <Plus className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
          {!collapsed && <span>新建对话</span>}
        </button>

        {collapsed && (
          <button
            type="button"
            onClick={onToggleCollapsed}
            className="w-10 h-10 mx-auto rounded-xl flex items-center justify-center text-gray-500 hover:text-indigo-600 hover:bg-gray-200/60 dark:hover:bg-gray-800 transition"
            title="展开侧栏"
            aria-label="展开侧栏"
          >
            <PanelLeftOpen className="w-4 h-4" />
          </button>
        )}

        {!collapsed && (
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-gray-400" />
            <input
              type="text"
              placeholder="搜索会话"
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              className="w-full pl-8 pr-3 py-1.5 bg-gray-200/50 dark:bg-gray-800/60 border-none rounded-lg text-xs text-gray-700 dark:text-gray-200 focus:outline-none focus:ring-1 focus:ring-indigo-500 placeholder-gray-400"
            />
          </div>
        )}
      </div>

      {!collapsed && (
        <div className="px-3 pb-2 flex items-center justify-between text-[11px]">
          <span className="font-semibold text-gray-400">{showArchived ? '已归档' : '最近'}</span>
          <button
            type="button"
            onClick={onToggleArchived}
            className="text-gray-500 hover:text-indigo-600 dark:hover:text-indigo-300 transition"
          >
            {showArchived ? '查看最近' : '查看归档'}
          </button>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-2 space-y-3 text-xs">
        {collapsed ? (
          <div className="space-y-1 pt-1">
            {filteredSessions.slice(0, 8).map((session) => (
              <button
                type="button"
                key={session.id}
                onClick={() => onSelectSession(session.id)}
                className={`w-10 h-10 mx-auto rounded-xl flex items-center justify-center transition ${session.id === activeSessionId ? 'bg-gray-200/80 dark:bg-gray-800 text-indigo-600' : 'text-gray-400 hover:bg-gray-200/50 dark:hover:bg-gray-800/50'}`}
                title={session.title || '新对话'}
                aria-label={session.title || '新对话'}
              >
                <MessageSquare className="w-4 h-4" />
              </button>
            ))}
          </div>
        ) : (
          <div className="space-y-0.5 mt-1">
            {filteredSessions.length === 0 ? (
              <div className="px-3 py-8 text-center text-gray-400 text-xs">
                {showArchived ? '暂无归档会话' : '暂无会话'}
              </div>
            ) : (
              filteredSessions.map((session) => {
                const isActive = session.id === activeSessionId;
                const isMenuOpen = menuSessionId === session.id;
                const isRenaming = renameSessionId === session.id;
                return (
                  <div key={session.id} className="relative">
                    <div
                      onClick={() => onSelectSession(session.id)}
                      className={`group px-3 py-2 rounded-xl cursor-pointer transition flex items-center gap-2 ${isActive ? 'bg-gray-200/70 dark:bg-gray-800 font-semibold text-gray-900 dark:text-white' : 'text-gray-600 dark:text-gray-400 hover:bg-gray-200/40 dark:hover:bg-gray-800/40'}`}
                    >
                      <MessageSquare className={`w-3.5 h-3.5 flex-shrink-0 ${isActive ? 'text-indigo-600 dark:text-indigo-400' : 'text-gray-400'}`} />
                      {isRenaming ? (
                        <input
                          autoFocus
                          value={renameValue}
                          onChange={(event) => setRenameValue(event.target.value)}
                          onClick={(event) => event.stopPropagation()}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter') void submitRename(session.id);
                            if (event.key === 'Escape') setRenameSessionId(null);
                          }}
                          className="min-w-0 flex-1 bg-white dark:bg-gray-900 border border-indigo-300 rounded-md px-1.5 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-500"
                        />
                      ) : (
                        <span className="truncate flex-1">{session.title || '新对话'}</span>
                      )}
                      {isRenaming ? (
                        <button type="button" onClick={(event) => { event.stopPropagation(); void submitRename(session.id); }} className="p-1 text-emerald-600 hover:bg-emerald-50 rounded" title="保存名称">
                          <Check className="w-3.5 h-3.5" />
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={(event) => { event.stopPropagation(); setMenuSessionId(isMenuOpen ? null : session.id); }}
                          className={`p-1 rounded text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-300/70 dark:hover:bg-gray-700 transition ${isMenuOpen ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}
                          title="会话操作"
                          aria-label="会话操作"
                        >
                          <MoreHorizontal className="w-4 h-4" />
                        </button>
                      )}
                    </div>

                    {isMenuOpen && (
                      <div className="absolute z-20 right-1 top-10 w-36 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-1.5 shadow-lg">
                        <ActionButton type="button" icon={Pencil} variant="default" size="sm" onClick={() => beginRename(session)} className="!h-8 !w-full !justify-start !px-2.5 !text-xs dark:!text-gray-200">
                          重命名
                        </ActionButton>
                        <button type="button" onClick={() => { setMenuSessionId(null); void onArchiveSession(session.id, session.status !== 'archived'); }} className="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-xs text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700">
                          {session.status === 'archived' ? <ArchiveRestore className="w-3.5 h-3.5" /> : <Archive className="w-3.5 h-3.5" />}
                          {session.status === 'archived' ? '恢复会话' : '归档会话'}
                        </button>
                        <ActionButton type="button" icon={Trash2} variant="danger" size="sm" onClick={() => void handleDelete(session)} className="!h-8 !w-full !justify-start !px-2.5 !text-xs">
                          删除
                        </ActionButton>
                        <button type="button" onClick={() => setMenuSessionId(null)} className="absolute -right-2 -top-2 w-5 h-5 rounded-full bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 flex items-center justify-center text-gray-400 hover:text-gray-700" title="关闭菜单">
                          <X className="w-3 h-3" />
                        </button>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>
    </aside>
  );
};
