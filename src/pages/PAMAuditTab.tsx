import React, { useState, useEffect, useCallback } from 'react';
import PageHero from '../components/PageHero';
import { 
  ShieldCheck, 
  Terminal, 
  Clock, 
  Activity, 
  User, 
  Trash2, 
  Download, 
  PlayCircle, 
  StopCircle,
  Search,
  RefreshCw,
  MoreVertical,
  History,
  Wifi,
  WifiOff,
  AlertCircle,
  Timer
} from 'lucide-react';
import CastPlayer from '../components/access/CastPlayer';
import Pagination from '../components/Pagination';

interface PAMSession {
  id: string;
  asset_id: string;
  asset_hostname: string;
  requester_username: string;
  access_level: 'normal' | 'admin';
  login_username: string;
  connect_method: 'web' | 'local';
  target_ip: string;
  status: 'connecting' | 'active' | 'closed' | 'error' | 'timeout';
  connected_at: string | null;
  closed_at: string | null;
  close_reason: string;
  duration_seconds: number;
  command_count: number;
  recording_path: string;
  created_at: string;
  /** Set to 1 when the underlying asset has been deleted; the session row
   *  itself is preserved for audit purposes (Plan A soft-delete). */
  archived?: number;
}

const STATUS_CONFIG = {
  active:     { dot: 'bg-emerald-500 animate-pulse', text: 'text-emerald-700', bg: 'bg-emerald-50', label: '在线', labelEn: 'Online' },
  connecting: { dot: 'bg-amber-400 animate-pulse',  text: 'text-amber-700',   bg: 'bg-amber-50',   label: '连接中', labelEn: 'Connecting' },
  closed:     { dot: 'bg-slate-300',                text: 'text-slate-500',   bg: 'bg-slate-50',   label: '已关闭', labelEn: 'Closed' },
  error:      { dot: 'bg-rose-500',                 text: 'text-rose-700',    bg: 'bg-rose-50',    label: '错误',   labelEn: 'Error' },
  timeout:    { dot: 'bg-orange-400',               text: 'text-orange-700',  bg: 'bg-orange-50',  label: '超时',   labelEn: 'Timeout' },
};

const PAMAuditTab: React.FC<{ language: string; showToast: (msg: string, type?: 'success'|'error'|'info') => void }> = ({ language, showToast }) => {
  const isZh = language === 'zh';
  const [sessions, setSessions] = useState<PAMSession[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'active' | 'history'>('active');
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [showPlayback, setShowPlayback] = useState(false);
  const [selectedSession, setSelectedSession] = useState<PAMSession | null>(null);
  // Kill confirmation modal
  const [killTarget, setKillTarget] = useState<PAMSession | null>(null);
  const [isKilling, setIsKilling] = useState(false);
  // Pagination — server-driven so we never pull the whole history table.
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [totalItems, setTotalItems] = useState(0);
  // Counts for the tab badges. Fetched independently with page_size=1 so a
  // 5k-row history table does not have to ship to the client just to show "n".
  const [activeCnt, setActiveCnt] = useState(0);
  const [historyCnt, setHistoryCnt] = useState(0);

  // Debounce the search box so we don't send a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchQuery.trim()), 250);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const fetchSessions = useCallback(async () => {
    setLoading(true);
    try {
      const statusFilter = activeTab === 'active' ? 'active' : '';
      const params = new URLSearchParams({
        status: statusFilter,
        page: String(page),
        page_size: String(pageSize),
      });
      if (debouncedSearch) params.set('search', debouncedSearch);
      const res = await fetch(`/api/pam/sessions?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.items) {
        setSessions(data.items);
        setTotalItems(typeof data.total === 'number' ? data.total : (data.items?.length || 0));
      }
    } catch (err) {
      showToast(isZh ? '加载会话失败' : 'Failed to load sessions', 'error');
    } finally {
      setLoading(false);
    }
  }, [activeTab, page, pageSize, debouncedSearch, isZh, showToast]);

  // Cheap badge counts — one tiny request each, parallel with the main list.
  const fetchCounts = useCallback(async () => {
    try {
      const [activeRes, historyRes] = await Promise.all([
        fetch('/api/pam/sessions?status=active&page=1&page_size=1'),
        // Closed sessions across all non-active states. We pass status=closed
        // to bucket the most common case; the History tab's tab badge is a
        // ballpark indicator, not a precise count, so this is acceptable.
        fetch('/api/pam/sessions?status=closed&page=1&page_size=1'),
      ]);
      if (activeRes.ok) {
        const j = await activeRes.json();
        setActiveCnt(typeof j.total === 'number' ? j.total : 0);
      }
      if (historyRes.ok) {
        const j = await historyRes.json();
        setHistoryCnt(typeof j.total === 'number' ? j.total : 0);
      }
    } catch { /* ignore — badges are best-effort */ }
  }, []);

  useEffect(() => {
    fetchSessions();
    fetchCounts();
    // Auto-refresh active sessions every 15 seconds. (Was 8 s; raised to
    // reduce backend pressure now that paging is server-side.)
    if (activeTab === 'active') {
      const timer = setInterval(() => {
        fetchSessions();
        fetchCounts();
      }, 15000);
      return () => clearInterval(timer);
    }
  }, [activeTab, fetchSessions, fetchCounts]);

  // ESC to dismiss kill confirmation modal
  useEffect(() => {
    if (!killTarget) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isKilling) {
        e.preventDefault();
        setKillTarget(null);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [killTarget, isKilling]);

  const confirmKill = async () => {
    if (!killTarget) return;
    setIsKilling(true);
    try {
      const res = await fetch(`/api/pam/sessions/${killTarget.id}/kill`, { method: 'POST' });
      if (res.ok) {
        showToast(isZh ? '会话已终止' : 'Session terminated', 'success');
        fetchSessions();
      } else {
        let detail = '';
        try {
          const body = await res.json();
          detail = body?.detail || body?.message || '';
        } catch {
          try { detail = await res.text(); } catch { /* ignore */ }
        }
        showToast(
          (isZh ? '操作失败' : 'Action failed') + (detail ? `: ${detail}` : ` (HTTP ${res.status})`),
          'error'
        );
      }
    } catch (err) {
      showToast(
        (isZh ? '网络错误' : 'Network error') + `: ${err instanceof Error ? err.message : String(err)}`,
        'error'
      );
    } finally {
      setIsKilling(false);
      setKillTarget(null);
    }
  };

  const handleDownload = (sessionId: string) => {
    window.open(`/api/pam/sessions/${sessionId}/recording`, '_blank');
  };

  const formatDuration = (sec: number) => {
    if (!sec || sec <= 0) return '—';
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (h > 0) return `${h}h ${m}m`;
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  };

  const formatTime = (ts: string | null) => {
    if (!ts) return '—';
    try {
      return new Date(ts).toLocaleString(isZh ? 'zh-CN' : 'en-US', {
        month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
      });
    } catch { return ts; }
  };

  // The server has already filtered + paginated the results.
  // Sessions list is exactly what we need to render.
  const filteredSessions = sessions;
  const paginatedSessions = sessions;

  // Reset to first page whenever filter or tab changes (so the user is not
  // stranded on a page that no longer exists).
  useEffect(() => {
    setPage(1);
  }, [activeTab, debouncedSearch]);

  // Clamp page if total items shrink (e.g. an active session just closed).
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={ShieldCheck}
        title={isZh ? 'PAM 受控会话审计' : 'PAM Session Audit'}
        subtitle={isZh ? '实时监控、强制断开及录制回放' : 'Real-time monitoring, termination & playback'}
        actions={
          <button
            onClick={fetchSessions}
            className="p-2 hover:bg-slate-100 rounded-full transition-colors"
            title={isZh ? '刷新' : 'Refresh'}
          >
            <RefreshCw className={`w-5 h-5 text-slate-400 ${loading ? 'animate-spin' : ''}`} />
          </button>
        }
        extras={
          /* Tabs + Search */
          <div className="flex items-center justify-between">
            <div className="flex p-1 bg-slate-100 rounded-lg gap-1">
              <button
                onClick={() => setActiveTab('active')}
                className={`flex items-center gap-2 px-4 py-1.5 text-sm font-medium rounded-md transition-all ${
                  activeTab === 'active'
                    ? 'bg-white text-cyan-600 shadow-sm'
                    : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                <Wifi className="w-3.5 h-3.5" />
                {isZh ? '活跃会话' : 'Active Sessions'}
                {activeCnt > 0 && (
                  <span className="ml-1 px-1.5 py-0.5 bg-emerald-100 text-emerald-700 text-[10px] font-bold rounded-full">
                    {activeCnt}
                  </span>
                )}
              </button>
              <button
                onClick={() => setActiveTab('history')}
                className={`flex items-center gap-2 px-4 py-1.5 text-sm font-medium rounded-md transition-all ${
                  activeTab === 'history'
                    ? 'bg-white text-cyan-600 shadow-sm'
                    : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                <History className="w-3.5 h-3.5" />
                {isZh ? '历史记录' : 'Session History'}
                {activeTab === 'history' && historyCnt > 0 && (
                  <span className="ml-1 px-1.5 py-0.5 bg-slate-200 text-slate-600 text-[10px] font-bold rounded-full">
                    {historyCnt}
                  </span>
                )}
              </button>
            </div>

            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="text"
                placeholder={isZh ? '搜索设备、用户、IP...' : 'Search device, user, IP...'}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10 pr-4 py-2 bg-slate-100 border-none rounded-lg text-sm focus:ring-2 focus:ring-cyan-500 w-64 transition-all outline-none"
              />
            </div>
          </div>
        }
      />

      <div className="flex-1 overflow-auto px-6 py-5" style={{ background: 'rgba(248, 250, 252, 0.5)' }}>

      {/* ── Table ── */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
          {filteredSessions.length === 0 && !loading ? (
            /* Empty state */
            <div className="flex flex-col items-center justify-center py-20 gap-4 text-slate-400">
              {activeTab === 'active' ? (
                <>
                  <WifiOff className="w-12 h-12 text-slate-200" />
                  <p className="text-sm font-medium">{isZh ? '当前没有活跃的受控会话' : 'No active sessions right now'}</p>
                  <p className="text-xs text-slate-300">
                    {isZh ? '通过"操作工作台"发起 Web 登录后，会话将在此显示' : 'Sessions appear here after launching a Web login from the Workspace'}
                  </p>
                </>
              ) : (
                <>
                  <History className="w-12 h-12 text-slate-200" />
                  <p className="text-sm font-medium">{isZh ? '暂无历史会话记录' : 'No session history yet'}</p>
                  <p className="text-xs text-slate-300">
                    {isZh ? '已关闭的会话将在此归档' : 'Closed sessions will be archived here'}
                  </p>
                </>
              )}
            </div>
          ) : (
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider w-28">{isZh ? '状态' : 'Status'}</th>
                  <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">{isZh ? '设备 / 资产' : 'Device / Asset'}</th>
                  <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">{isZh ? '请求者' : 'Requester'}</th>
                  <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">{isZh ? '登录账号' : 'Login Account'}</th>
                  <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">{isZh ? '权限级别' : 'Access Level'}</th>
                  <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">{isZh ? '连接时间' : 'Connected At'}</th>
                  <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">{isZh ? '时长' : 'Duration'}</th>
                  <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-right">{isZh ? '操作' : 'Actions'}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {loading && filteredSessions.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-6 py-12 text-center text-slate-400 text-sm">
                      <RefreshCw className="w-5 h-5 animate-spin inline-block mr-2" />
                      {isZh ? '加载中...' : 'Loading...'}
                    </td>
                  </tr>
                ) : paginatedSessions.map(s => {
                  const cfg = STATUS_CONFIG[s.status] || STATUS_CONFIG.closed;
                  const isActive = s.status === 'active' || s.status === 'connecting';
                  return (
                    <tr key={s.id} className="hover:bg-slate-50/80 transition-colors group">
                      {/* Status */}
                      <td className="px-6 py-4">
                        <div className={`inline-flex items-center gap-2 px-2.5 py-1 rounded-full ${cfg.bg}`}>
                          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${cfg.dot}`} />
                          <span className={`text-xs font-semibold ${cfg.text}`}>
                            {isZh ? cfg.label : cfg.labelEn}
                          </span>
                        </div>
                      </td>

                      {/* Device */}
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-3">
                          <div className="flex flex-col">
                            <div className="flex items-center gap-1.5">
                              <span className="text-sm font-semibold text-slate-900">{s.asset_hostname || '—'}</span>
                              {s.archived ? (
                                <span
                                  className="inline-flex items-center px-1.5 py-0.5 rounded-md text-[9px] font-bold uppercase tracking-wider bg-slate-100 text-slate-500 border border-slate-200"
                                  title={isZh ? '关联资产已删除，会话记录已归档保留' : 'Underlying asset removed; session archived for audit'}
                                >
                                  {isZh ? '已归档' : 'Archived'}
                                </span>
                              ) : null}
                            </div>
                            <span className="text-xs text-slate-400 font-mono mt-0.5">{s.target_ip}</span>
                          </div>
                          {(s as any).risk_level > 0 && (
                            <div 
                              className={`group relative p-1.5 rounded-lg border ${(s as any).risk_level === 2 ? 'bg-rose-50 border-rose-200 text-rose-500' : 'bg-amber-50 border-amber-200 text-amber-500'}`}
                              title={(s as any).risk_summary}
                            >
                              <AlertCircle className="w-4 h-4" />
                              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-48 p-2 bg-slate-900 text-white text-[10px] rounded shadow-xl opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10">
                                <div className="font-bold mb-1">{(s as any).risk_level === 2 ? '极高风险' : '中等风险'}</div>
                                {(s as any).risk_summary}
                              </div>
                            </div>
                          )}
                        </div>
                      </td>

                      {/* Requester */}
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2">
                          <div className="w-7 h-7 bg-cyan-50 rounded-full flex items-center justify-center flex-shrink-0">
                            <User className="w-3.5 h-3.5 text-cyan-500" />
                          </div>
                          <span className="text-sm text-slate-700">{s.requester_username || '—'}</span>
                        </div>
                      </td>

                      {/* Login account */}
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-1.5">
                          <span className="font-mono text-xs text-slate-600 bg-slate-100 px-2 py-1 rounded">
                            {s.login_username || '—'}
                          </span>
                          {(s as any).connect_method === 'local' && (
                            <span className="text-[9px] font-bold text-amber-600 bg-amber-50 border border-amber-200 px-1.5 py-0.5 rounded uppercase tracking-wider">
                              {isZh ? '本地' : 'Local'}
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Access level */}
                      <td className="px-6 py-4">
                        <span className={`px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider ${
                          s.access_level === 'admin'
                            ? 'bg-rose-50 text-rose-600'
                            : 'bg-blue-50 text-blue-600'
                        }`}>
                          {s.access_level === 'admin' ? (isZh ? '特权' : 'Admin') : (isZh ? '普通' : 'Normal')}
                        </span>
                      </td>

                      {/* Connected at */}
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-1.5 text-sm text-slate-500">
                          <Clock className="w-3.5 h-3.5 text-slate-300 flex-shrink-0" />
                          {formatTime(s.connected_at || s.created_at)}
                        </div>
                      </td>

                      {/* Duration */}
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-1.5 text-sm text-slate-600">
                          <Timer className="w-3.5 h-3.5 text-slate-300 flex-shrink-0" />
                          {isActive ? (
                            <span className="text-emerald-600 font-medium">{isZh ? '进行中' : 'Live'}</span>
                          ) : (
                            formatDuration(s.duration_seconds)
                          )}
                        </div>
                      </td>

                      {/* Actions */}
                      <td className="px-6 py-4 text-right">
                        <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          {isActive ? (
                            <button
                              onClick={() => setKillTarget(s)}
                              className="p-2 text-rose-500 hover:bg-rose-50 rounded-lg transition-colors"
                              title={isZh ? '强制切断' : 'Kill Session'}
                            >
                              <StopCircle className="w-4 h-4" />
                            </button>
                          ) : s.recording_path ? (
                            <>
                              <button
                                onClick={() => handleDownload(s.id)}
                                className="p-2 text-cyan-500 hover:bg-cyan-50 rounded-lg transition-colors"
                                title={isZh ? '下载录像' : 'Download Cast'}
                              >
                                <Download className="w-4 h-4" />
                              </button>
                              <button
                                onClick={() => {
                                  setSelectedSession(s);
                                  setShowPlayback(true);
                                }}
                                className="p-2 text-cyan-500 hover:bg-cyan-50 rounded-lg transition-colors"
                                title={isZh ? '回溯回放' : 'Playback'}
                              >
                                <PlayCircle className="w-4 h-4" />
                              </button>
                            </>
                          ) : (
                            <span className="text-[10px] text-slate-300 px-2">
                              {s.connect_method === 'local'
                                ? (isZh ? '本地终端·无录像' : 'Local · No recording')
                                : (isZh ? '无录像' : 'No recording')}
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination (matching style used across the app) */}
        {filteredSessions.length > 0 && (
          <div className="mt-4 rounded-2xl bg-white border border-slate-200 overflow-hidden">
            <Pagination
              currentPage={page}
              totalItems={totalItems}
              onPageChange={setPage}
              itemsPerPage={pageSize}
              onItemsPerPageChange={(n) => { setPageSize(n); setPage(1); }}
              language={language}
            />
          </div>
        )}

        {activeTab === 'active' && filteredSessions.length > 0 && (
          <div className="mt-2 flex items-center justify-end text-[11px] text-slate-400 px-2">
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              {isZh ? '每 8 秒自动刷新' : 'Auto-refresh every 8s'}
            </span>
          </div>
        )}
      </div>

      {/* ── CastPlayer Modal ── */}
      {showPlayback && selectedSession && (
        <CastPlayer
          sessionId={selectedSession.id}
          totalDuration={selectedSession.duration_seconds || 0}
          sessionMeta={{
            hostname: selectedSession.asset_hostname,
            ip: selectedSession.target_ip,
            loginUser: selectedSession.login_username,
            requester: selectedSession.requester_username,
            connectedAt: selectedSession.connected_at,
          }}
          onClose={() => {
            setShowPlayback(false);
            setSelectedSession(null);
          }}
          isZh={isZh}
        />
      )}

      {/* ── Kill Session Confirmation Modal ── */}
      {killTarget && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => !isKilling && setKillTarget(null)}
          />
          <div className="relative w-full max-w-md bg-white rounded-2xl shadow-2xl overflow-hidden border border-rose-100">
            {/* Warning header */}
            <div className="bg-gradient-to-r from-rose-500 to-red-600 px-6 py-4 flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-white/20 flex items-center justify-center">
                <AlertCircle className="w-5 h-5 text-white" />
              </div>
              <div>
                <h3 className="text-base font-bold text-white">
                  {isZh ? '强制断开会话' : 'Terminate Session'}
                </h3>
                <p className="text-xs text-rose-100 mt-0.5">
                  {isZh ? '此操作不可撤销' : 'This action cannot be undone'}
                </p>
              </div>
            </div>

            {/* Body */}
            <div className="px-6 py-5 space-y-4">
              <p className="text-sm text-slate-700 leading-relaxed">
                {isZh
                  ? '确定要强制断开以下会话吗？用户当前的操作将被立即中断，已执行的命令不会回滚。'
                  : 'Are you sure you want to terminate the following session? The user\'s current operation will be interrupted immediately. Executed commands cannot be rolled back.'}
              </p>

              <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 space-y-2 text-xs">
                <div className="flex items-start justify-between gap-4">
                  <span className="text-slate-400 font-medium">{isZh ? '目标设备' : 'Device'}</span>
                  <span className="font-mono font-bold text-slate-700 text-right truncate">
                    {killTarget.asset_hostname || killTarget.target_ip}
                  </span>
                </div>
                <div className="flex items-start justify-between gap-4">
                  <span className="text-slate-400 font-medium">{isZh ? 'IP 地址' : 'IP Address'}</span>
                  <span className="font-mono text-slate-600">{killTarget.target_ip}</span>
                </div>
                <div className="flex items-start justify-between gap-4">
                  <span className="text-slate-400 font-medium">{isZh ? '登录账号' : 'Login User'}</span>
                  <span className="font-mono text-slate-600">{killTarget.login_username}</span>
                </div>
                <div className="flex items-start justify-between gap-4">
                  <span className="text-slate-400 font-medium">{isZh ? '请求者' : 'Requester'}</span>
                  <span className="font-mono text-slate-600">{killTarget.requester_username}</span>
                </div>
                <div className="flex items-start justify-between gap-4">
                  <span className="text-slate-400 font-medium">{isZh ? '权限级别' : 'Access Level'}</span>
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                    killTarget.access_level === 'admin' ? 'bg-amber-100 text-amber-700' : 'bg-cyan-100 text-cyan-700'
                  }`}>
                    {killTarget.access_level.toUpperCase()}
                  </span>
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="px-6 py-4 bg-slate-50 border-t border-slate-100 flex items-center justify-end gap-2">
              <button
                onClick={() => setKillTarget(null)}
                disabled={isKilling}
                className="px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-200 rounded-lg transition-colors disabled:opacity-50"
              >
                {isZh ? '取消' : 'Cancel'}
              </button>
              <button
                onClick={confirmKill}
                disabled={isKilling}
                className="px-4 py-2 text-sm font-bold text-white bg-gradient-to-r from-rose-500 to-red-600 hover:from-rose-600 hover:to-red-700 rounded-lg shadow-md shadow-rose-500/30 transition-all disabled:opacity-50 flex items-center gap-2"
              >
                {isKilling ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    {isZh ? '断开中...' : 'Terminating...'}
                  </>
                ) : (
                  <>
                    <StopCircle className="w-4 h-4" />
                    {isZh ? '确认强制断开' : 'Confirm Terminate'}
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default PAMAuditTab;
