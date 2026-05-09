import React, { useState, useEffect } from 'react';
import { 
  ShieldCheck, 
  Terminal, 
  Clock, 
  Activity, 
  User, 
  Monitor, 
  Trash2, 
  Download, 
  PlayCircle, 
  StopCircle,
  Search,
  RefreshCw,
  MoreVertical
} from 'lucide-react';
import CastPlayer from '../components/access/CastPlayer';

interface PAMSession {
  id: string;
  asset_id: string;
  asset_hostname: string;
  requester_username: string;
  access_level: 'normal' | 'admin';
  login_username: string;
  target_ip: string;
  status: 'connecting' | 'active' | 'closed' | 'error' | 'timeout';
  connected_at: string | null;
  closed_at: string | null;
  duration_seconds: number;
  command_count: number;
  recording_path: string;
  created_at: string;
}

const PAMAuditTab: React.FC<{ language: string; showToast: (msg: string, type?: 'success'|'error'|'info') => void }> = ({ language, showToast }) => {
  const isZh = language === 'zh';
  const [sessions, setSessions] = useState<PAMSession[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'active' | 'history'>('active');
  const [searchQuery, setSearchQuery] = useState('');
  const [showPlayback, setShowPlayback] = useState(false);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);

  const fetchSessions = async () => {
    setLoading(true);
    try {
      const statusFilter = activeTab === 'active' ? 'active' : '';
      const res = await fetch(`/api/pam/sessions?status=${statusFilter}&page_size=100`);
      const data = await res.json();
      if (data.items) {
        setSessions(data.items);
      }
    } catch (err) {
      showToast(isZh ? '加载会话失败' : 'Failed to load sessions', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSessions();
    const timer = setInterval(() => {
      if (activeTab === 'active') fetchSessions();
    }, 10000);
    return () => clearInterval(timer);
  }, [activeTab]);

  const handleKill = async (sessionId: string) => {
    if (!window.confirm(isZh ? '确定要强制断开此会话吗？' : 'Are you sure you want to terminate this session?')) return;
    try {
      const res = await fetch(`/api/pam/sessions/${sessionId}/kill`, { method: 'POST' });
      if (res.ok) {
        showToast(isZh ? '会话已终止' : 'Session terminated', 'success');
        fetchSessions();
      }
    } catch (err) {
      showToast('Action failed', 'error');
    }
  };

  const handleDownload = (sessionId: string) => {
    window.open(`/api/pam/sessions/${sessionId}/recording`, '_blank');
  };

  const formatDuration = (sec: number) => {
    if (!sec) return '0s';
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  };

  const filteredSessions = sessions.filter(s => 
    s.asset_hostname?.toLowerCase().includes(searchQuery.toLowerCase()) ||
    s.requester_username?.toLowerCase().includes(searchQuery.toLowerCase()) ||
    s.target_ip?.includes(searchQuery)
  );

  return (
    <div className="flex flex-col h-full bg-slate-50/50">
      {/* Header */}
      <div className="px-8 py-6 bg-white border-b border-slate-200">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-cyan-600 rounded-xl">
              <ShieldCheck className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-900">
                {isZh ? 'PAM 受控会话审计' : 'PAM Session Audit'}
              </h1>
              <p className="text-sm text-slate-500">
                {isZh ? '实时监控、强制断开及录制回放' : 'Real-time monitoring, termination, and playback'}
              </p>
            </div>
          </div>
          <button 
            onClick={fetchSessions}
            className="p-2 hover:bg-slate-100 rounded-full transition-colors"
          >
            <RefreshCw className={`w-5 h-5 text-slate-400 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>

        {/* Filters & Tabs */}
        <div className="flex items-center justify-between">
          <div className="flex p-1 bg-slate-100 rounded-lg">
            <button
              onClick={() => setActiveTab('active')}
              className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${
                activeTab === 'active' 
                ? 'bg-white text-cyan-600 shadow-sm' 
                : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              {isZh ? '活跃会话' : 'Active Sessions'}
            </button>
            <button
              onClick={() => setActiveTab('history')}
              className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${
                activeTab === 'history' 
                ? 'bg-white text-cyan-600 shadow-sm' 
                : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              {isZh ? '历史记录' : 'Session History'}
            </button>
          </div>

          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="text"
              placeholder={isZh ? '搜索设备、用户...' : 'Search device, user...'}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10 pr-4 py-2 bg-slate-100 border-none rounded-lg text-sm focus:ring-2 focus:ring-cyan-500 w-64 transition-all"
            />
          </div>
        </div>
      </div>

      {/* Content Area */}
      <div className="flex-1 overflow-auto p-8">
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">{isZh ? '状态' : 'Status'}</th>
                <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">{isZh ? '设备 / 资产' : 'Device / Asset'}</th>
                <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">{isZh ? '请求者' : 'Requester'}</th>
                <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">{isZh ? '权限级别' : 'Access'}</th>
                <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">{isZh ? '连接时间' : 'Connected At'}</th>
                <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">{isZh ? '时长' : 'Duration'}</th>
                <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-right">{isZh ? '操作' : 'Actions'}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filteredSessions.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-6 py-12 text-center text-slate-400 italic text-sm">
                    {loading ? '...' : (isZh ? '暂无会话记录' : 'No sessions found')}
                  </td>
                </tr>
              ) : filteredSessions.map(s => (
                <tr key={s.id} className="hover:bg-slate-50/80 transition-colors group">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full ${
                        s.status === 'active' ? 'bg-emerald-500 animate-pulse' :
                        s.status === 'error' ? 'bg-rose-500' :
                        s.status === 'timeout' ? 'bg-amber-500' : 'bg-slate-300'
                      }`} />
                      <span className="text-sm font-medium text-slate-700 capitalize">
                        {s.status === 'active' ? (isZh ? '在线' : 'Online') : s.status}
                      </span>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex flex-col">
                      <span className="text-sm font-semibold text-slate-900">{s.asset_hostname || 'Unknown Host'}</span>
                      <span className="text-xs text-slate-500 font-mono">{s.target_ip}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <div className="w-7 h-7 bg-slate-100 rounded-full flex items-center justify-center">
                        <User className="w-4 h-4 text-slate-500" />
                      </div>
                      <span className="text-sm text-slate-700">{s.requester_username}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <span className={`px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider ${
                      s.access_level === 'admin' 
                      ? 'bg-rose-50 text-rose-600' 
                      : 'bg-blue-50 text-blue-600'
                    }`}>
                      {s.access_level}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2 text-sm text-slate-500">
                      <Clock className="w-4 h-4 text-slate-300" />
                      {s.connected_at ? new Date(s.connected_at).toLocaleString() : '-'}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2 text-sm text-slate-600">
                      <Activity className="w-4 h-4 text-slate-300" />
                      {s.status === 'active' ? (isZh ? '连接中' : 'Active') : formatDuration(s.duration_seconds)}
                    </div>
                  </td>
                  <td className="px-6 py-4 text-right">
                    <div className="flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      {s.status === 'active' ? (
                        <button
                          onClick={() => handleKill(s.id)}
                          className="p-2 text-rose-500 hover:bg-rose-50 rounded-lg transition-colors"
                          title={isZh ? '强制切断' : 'Kill Session'}
                        >
                          <StopCircle className="w-5 h-5" />
                        </button>
                      ) : s.recording_path ? (
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => handleDownload(s.id)}
                            className="p-2 text-cyan-500 hover:bg-cyan-50 rounded-lg transition-colors"
                            title={isZh ? '下载录像' : 'Download Cast'}
                          >
                            <Download className="w-5 h-5" />
                          </button>
                          <button
                            onClick={() => {
                              setSelectedSessionId(s.id);
                              setShowPlayback(true);
                            }}
                            className="p-2 text-cyan-500 hover:bg-cyan-50 rounded-lg transition-colors"
                            title={isZh ? '回溯回放' : 'Backtrack Playback'}
                          >
                            <PlayCircle className="w-5 h-5" />
                          </button>
                        </div>
                      ) : null}
                      <button className="p-2 text-slate-400 hover:bg-slate-50 rounded-lg transition-colors">
                        <MoreVertical className="w-5 h-5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {showPlayback && selectedSessionId && (
        <CastPlayer 
          sessionId={selectedSessionId} 
          totalDuration={sessions.find(s => s.id === selectedSessionId)?.duration_seconds || 0}
          onClose={() => {
            setShowPlayback(false);
            setSelectedSessionId(null);
          }}
          isZh={isZh}
        />
      )}
    </div>
  );
};

export default PAMAuditTab;
