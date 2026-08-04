import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  Plus, X, Trash2, Edit3, Shield, Search, User, FileCode, Terminal, Layout, Maximize2, XCircle, Wand2, ChevronDown, CheckCircle2, MessageSquare, AlertCircle, SearchCode, Copy
} from 'lucide-react';
import Pagination from '../components/Pagination';
import PageHero from '../components/PageHero';

interface Script {
  id: string;
  name: string;
  content: string;
  description: string;
  platform: string;
  category: string;
  script_type: string;
  author: string;
  version: string;
  status: string;
  submitter_name?: string;
  approver_username?: string;
  rejected_reason?: string;
  updated_at?: string;
}

interface UserInfo {
  username: string;
}

const ScriptManagementTab: React.FC<{ language: string; showToast: (msg: string, type: 'success' | 'error' | 'info') => void }> = ({ language, showToast }) => {
  const [scripts, setScripts] = useState<Script[]>([]);
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [currentUser, setCurrentUser] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [platformFilter, setPlatformFilter] = useState('All');
  const [categoryFilter, setCategoryFilter] = useState<'all' | 'inspection' | 'change' | 'system'>('all');
  const [typeFilter, setTypeFilter] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');
  
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<'create' | 'edit'>('create');
  const [editForm, setEditForm] = useState<Partial<Script>>({});
  
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [showRejectPrompt, setShowRejectPrompt] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  
  const [auditorSearch, setAuditorSearch] = useState('');
  const [showAuditorDropdown, setShowAuditorDropdown] = useState(false);

  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [totalScripts, setTotalScripts] = useState(0);

  const zh = language === 'zh';
  const BRAND_COLOR = "#00a9ce";

  // Status Localization Map
  const STATUS_MAP: Record<string, { zh: string, en: string, color: string, bg: string, border: string }> = {
    draft: { zh: '草稿', en: 'Draft', color: 'text-slate-500', bg: 'bg-slate-50 dark:bg-slate-800/50', border: 'border-slate-200 dark:border-slate-700' },
    pending_audit: { zh: '待审核', en: 'Pending', color: 'text-amber-500', bg: 'bg-amber-50 dark:bg-amber-500/10', border: 'border-amber-200 dark:border-amber-500/20' },
    released: { zh: '已发布', en: 'Released', color: 'text-emerald-500', bg: 'bg-emerald-50 dark:bg-emerald-500/10', border: 'border-emerald-200 dark:border-emerald-500/20' },
    rejected: { zh: '已驳回', en: 'Rejected', color: 'text-rose-500', bg: 'bg-rose-50 dark:bg-rose-500/10', border: 'border-rose-200 dark:border-rose-500/20' }
  };

  const getStatusLabel = (status: string) => {
    const meta = STATUS_MAP[status] || STATUS_MAP.draft;
    return zh ? meta.zh : meta.en;
  };

  const getHeaders = useCallback(() => {
    const token = localStorage.getItem('netops_token') || '';
    return {
      'Content-Type': 'application/json',
      'Authorization': token ? `Bearer ${token}` : ''
    };
  }, []);

  const handleFormat = () => {
    if (!editForm.content) return;
    const formatted = editForm.content.split('\n').map(l => l.trimEnd()).join('\n');
    setEditForm({ ...editForm, content: formatted });
    showToast(zh ? '格式已整理' : 'Formatted', 'info');
  };

  const fetchScripts = useCallback(async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams({
        q: searchQuery.trim(),
        platform: platformFilter === 'All' ? '' : platformFilter,
        category: categoryFilter === 'all' ? '' : categoryFilter,
        script_type: typeFilter === 'All' ? '' : typeFilter,
        status: statusFilter === 'All' ? '' : statusFilter,
        page: String(currentPage),
        page_size: String(pageSize),
      });
      const res = await fetch(`/api/scripts?${params.toString()}`, { headers: getHeaders() });
      if (res.ok) {
        const payload = await res.json();
        if (Array.isArray(payload)) {
          setScripts(payload);
          setTotalScripts(payload.length);
        } else {
          const data = payload?.data || payload || {};
          setScripts(Array.isArray(data.items) ? data.items : []);
          setTotalScripts(Number(data.total || 0));
        }
      }
    } catch (err) {} finally { setLoading(false); }
  }, [getHeaders, searchQuery, platformFilter, categoryFilter, typeFilter, statusFilter, currentPage, pageSize]);

  const fetchUsers = async () => {
    try {
      const res = await fetch('/api/users', { headers: getHeaders() });
      if (res.ok) setUsers(await res.json());
      const meRes = await fetch('/api/session', { headers: getHeaders() });
      if (meRes.ok) {
        const data = await meRes.json();
        setCurrentUser(data.user?.username || 'admin');
      }
    } catch (err) {}
  };

  useEffect(() => {
    fetchScripts();
  }, [fetchScripts]);

  useEffect(() => {
    fetchUsers();
  }, [getHeaders]);

  const handleAction = async (targetStatus: string, reason?: string) => {
    const isEdit = modalMode === 'edit';
    const url = isEdit ? `/api/scripts/${encodeURIComponent(editForm.id!)}` : '/api/scripts';
    
    const payload = {
      ...editForm,
      status: targetStatus,
      rejected_reason: reason || '',
      updated_at: new Date().toISOString()
    };

    try {
      const res = await fetch(url, {
        method: isEdit ? 'PUT' : 'POST',
        headers: getHeaders(),
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        showToast(zh ? '操作成功' : 'Success', 'success');
        setIsModalOpen(false);
        setShowConfirmModal(false);
        setShowRejectPrompt(false);
        fetchScripts();
      }
    } catch (err) {
      showToast(zh ? '同步失败' : 'Failed', 'error');
    }
  };

  const availableReviewers = useMemo(() => 
    users.filter(u => u.username !== currentUser && u.username.toLowerCase().includes(auditorSearch.toLowerCase())), 
  [users, currentUser, auditorSearch]);

  // Platform filter groups: 按厂商族匹配，每个厂商可能对应多个 platform code
  // Linux → linux/ubuntu/centos…   Cisco → cisco_ios/cisco_nxos/cisco_asa…   华为 → huawei_vrp/huawei_vrpv8…
  const PLATFORM_GROUPS: Record<string, string[]> = {
    'All': [],
    'Linux': ['Linux', 'linux', 'ubuntu', 'centos', 'debian', 'redhat'],
    'Cisco': ['cisco_ios', 'cisco_nxos', 'cisco_xr', 'cisco_asa', 'cisco_ftd', 'Cisco'],
    'Huawei': ['huawei_vrp', 'huawei_vrpv8', 'huawei', 'Huawei'],
    'H3C': ['h3c_comware', 'hp_comware', 'H3C'],
    'Juniper': ['juniper_junos', 'juniper', 'Juniper'],
    'Arista': ['arista_eos', 'Arista'],
  };

  // 平台选项：value 必须与后端/seed 中的 code 完全一致
  const PLATFORM_OPTIONS: Array<{ value: string; zh: string; en: string }> = [
    { value: 'Linux',          zh: 'Linux',              en: 'Linux' },
    { value: 'cisco_ios',      zh: 'Cisco IOS / IOS-XE', en: 'Cisco IOS / IOS-XE' },
    { value: 'cisco_nxos',     zh: 'Cisco NX-OS',        en: 'Cisco NX-OS' },
    { value: 'cisco_xr',       zh: 'Cisco IOS-XR',       en: 'Cisco IOS-XR' },
    { value: 'cisco_asa',      zh: 'Cisco ASA',          en: 'Cisco ASA' },
    { value: 'huawei_vrp',     zh: '华为 VRPv5',         en: 'Huawei VRPv5' },
    { value: 'huawei_vrpv8',   zh: '华为 VRPv8',         en: 'Huawei VRPv8' },
    { value: 'h3c_comware',    zh: 'H3C Comware',        en: 'H3C Comware' },
    { value: 'juniper_junos',  zh: 'Juniper JunOS',      en: 'Juniper JunOS' },
    { value: 'arista_eos',     zh: 'Arista EOS',         en: 'Arista EOS' },
  ];

  // 脚本类型选项：cli = 网络设备命令行；shell/python = 主机执行脚本
  const SCRIPT_TYPE_OPTIONS: Array<{ value: string; zh: string; en: string }> = [
    { value: 'shell',  zh: 'Shell',          en: 'Shell' },
    { value: 'python', zh: 'Python',         en: 'Python' },
    { value: 'cli',    zh: 'CLI 网络命令行', en: 'CLI (Network)' },
  ];
  const matchesPlatformGroup = (scriptPlatform: string, group: string): boolean => {
    if (group === 'All') return true;
    const codes = PLATFORM_GROUPS[group] || [group];
    if (codes.length === 0) return true;
    const p = (scriptPlatform || '').toLowerCase();
    return codes.some(c => c.toLowerCase() === p);
  };

  // Search/filtering and pagination are server-side. The browser keeps only
  // the current page instead of loading the entire script catalog.
  const filteredScripts = scripts;
  const paginatedScripts = scripts;

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, platformFilter, categoryFilter, typeFilter, statusFilter]);

  const isSystemScript = editForm.submitter_name === 'system' || editForm.author === 'system';
  const isReviewMode = editForm.status === 'pending_audit' && editForm.approver_username === currentUser;
  const isReadOnly = isReviewMode || (editForm.status === 'pending_audit' && editForm.submitter_name === currentUser) || isSystemScript;

  const inputClass = `w-full bg-slate-50 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700 rounded-xl px-4 py-2.5 text-[13px] outline-none transition-all ${isReadOnly ? 'text-slate-400 cursor-not-allowed opacity-70' : 'text-slate-700 dark:text-slate-100 focus:ring-2 focus:ring-[#00a9ce]/20'}`;
  const labelClass = "text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest mb-1.5 flex items-center gap-1.5";

  return (
    <div className="flex flex-col h-full bg-transparent overflow-hidden">
      <PageHero
        icon={Terminal}
        title={zh ? '操作管理' : 'Ops'}
        subtitle={zh ? '自动化脚本生命周期管理' : 'Script lifecycle management'}
        accent={BRAND_COLOR}
        actions={
          <>
            <div className="relative">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-300 dark:text-slate-600" size={14} />
              <input
                type="text"
                placeholder={zh ? "搜索脚本..." : "Search..."}
                value={searchQuery}
                onChange={(e) => { setSearchQuery(e.target.value); setCurrentPage(1); }}
                className="pl-11 pr-4 py-2 bg-slate-100/50 dark:bg-slate-800/40 border border-transparent dark:border-white/5 rounded-xl text-[12px] w-64 focus:w-80 transition-all outline-none text-slate-700 dark:text-white"
              />
            </div>
            <button
              onClick={() => { setModalMode('create'); setEditForm({ platform: 'Linux', script_type: 'shell', version: 'v1.0.0', status: 'draft' }); setIsModalOpen(true); }}
              className="px-6 py-2.5 text-white rounded-xl text-[13px] font-bold shadow-lg shadow-[#00a9ce]/15 active:scale-[0.98] transition-all flex items-center gap-2"
              style={{ backgroundColor: BRAND_COLOR }}
            >
              <Plus size={16} />
              {zh ? '新增脚本' : 'Create'}
            </button>
          </>
        }
      />

      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6 no-scrollbar">
        <div className="flex flex-col gap-4 bg-slate-50/50 dark:bg-slate-900/10 p-5 rounded-2xl border border-slate-100 dark:border-white/5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
             <div className="flex flex-col gap-2">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">{zh ? '适用平台' : 'Platform'}</span>
                <div className="flex items-center gap-1.5 p-1 bg-slate-200/20 dark:bg-slate-800/30 rounded-xl border border-slate-100/50 dark:border-white/5 flex-wrap">
                  {['All', 'Linux', 'Cisco', 'Huawei', 'H3C', 'Juniper', 'Arista'].map(p => (
                    <button key={p} onClick={() => { setPlatformFilter(p); setCurrentPage(1); }} className={`px-4 py-1.5 rounded-lg text-[11px] font-bold transition-all ${platformFilter === p ? 'bg-[#00a9ce] text-white shadow-sm' : 'text-slate-400 hover:text-[#00a9ce]'}`}>{p}</button>
                  ))}
                </div>
             </div>
             
             <div className="flex flex-col gap-2">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">{zh ? '脚本分类' : 'Category'}</span>
                <div className="flex items-center gap-1.5 p-1 bg-slate-200/20 dark:bg-slate-800/30 rounded-xl border border-slate-100/50 dark:border-white/5 flex-wrap">
                  {(zh ? [
                    { key: 'all', label: '全部' },
                    { key: 'inspection', label: '巡检采集' },
                    { key: 'change', label: '配置下发' },
                    { key: 'system', label: '系统内置' }
                  ] : [
                    { key: 'all', label: 'All' },
                    { key: 'inspection', label: 'Inspection / Collect' },
                    { key: 'change', label: 'Change / Push' },
                    { key: 'system', label: 'System Built-in' }
                  ]).map(c => (
                    <button key={c.key} onClick={() => { setCategoryFilter(c.key as any); setCurrentPage(1); }} className={`px-4 py-1.5 rounded-lg text-[11px] font-bold transition-all ${categoryFilter === c.key ? 'bg-[#00a9ce] text-white shadow-sm' : 'text-slate-400 hover:text-[#00a9ce]'}`}>{c.label}</button>
                  ))}
                </div>
             </div>
          </div>

          <div className="h-px bg-slate-100 dark:bg-white/5 w-full" />

          <div className="flex flex-wrap items-center gap-6">
             {/* Type Dropdown */}
             <div className="flex items-center gap-2">
               <span className="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">{zh ? '语言类型' : 'Type'}:</span>
               <select
                 value={typeFilter}
                 onChange={(e) => { setTypeFilter(e.target.value); setCurrentPage(1); }}
                 className="bg-white dark:bg-slate-900/60 border border-slate-200 dark:border-white/5 rounded-xl px-3 py-1.5 text-[11.5px] font-bold text-slate-600 dark:text-slate-300 outline-none focus:ring-1 focus:ring-[#00a9ce]"
               >
                 <option value="All">{zh ? '全部类型' : 'All Types'}</option>
                 <option value="shell">Shell</option>
                 <option value="python">Python</option>
                 <option value="cli">CLI</option>
               </select>
             </div>

             {/* Status Dropdown */}
             <div className="flex items-center gap-2">
               <span className="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">{zh ? '审核状态' : 'Status'}:</span>
               <select
                 value={statusFilter}
                 onChange={(e) => { setStatusFilter(e.target.value); setCurrentPage(1); }}
                 className="bg-white dark:bg-slate-900/60 border border-slate-200 dark:border-white/5 rounded-xl px-3 py-1.5 text-[11.5px] font-bold text-slate-600 dark:text-slate-300 outline-none focus:ring-1 focus:ring-[#00a9ce]"
               >
                 <option value="All">{zh ? '全部状态' : 'All Status'}</option>
                 <option value="draft">{zh ? '草稿' : 'Draft'}</option>
                 <option value="pending_audit">{zh ? '待审核' : 'Pending Audit'}</option>
                 <option value="released">{zh ? '已发布' : 'Released'}</option>
                 <option value="rejected">{zh ? '已驳回' : 'Rejected'}</option>
               </select>
             </div>
          </div>
        </div>

        <div className="rounded-[24px] border border-slate-100 dark:border-white/5 overflow-hidden bg-white dark:bg-slate-900/20 shadow-lg">
          <div className="overflow-x-auto no-scrollbar">
            <table className="nx-data-table text-left text-sm">
              <thead>
                <tr className="bg-slate-50/50 dark:bg-slate-800/30 border-b border-slate-100 dark:border-white/5">
                  <th className="px-6 py-4 text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">{zh ? '脚本名称' : 'Name'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">{zh ? '适用平台' : 'OS/Platform'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">{zh ? '分类' : 'Category'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">{zh ? '类型' : 'Type'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">{zh ? '状态' : 'Status'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">{zh ? '提交人' : 'Author'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">{zh ? '描述' : 'Description'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider w-28 text-right">{zh ? '操作' : 'Actions'}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                <AnimatePresence mode="popLayout">
                  {paginatedScripts.length > 0 ? (
                    paginatedScripts.map((script) => {
                      const isSystem = script.submitter_name === 'system' || script.author === 'system';
                      return (
                        <motion.tr
                          key={script.id}
                          layout
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          exit={{ opacity: 0 }}
                          className="hover:bg-slate-50/40 dark:hover:bg-slate-800/20 transition-colors group"
                        >
                          <td className="px-6 py-3.5">
                            <div className="font-bold text-slate-700 dark:text-slate-200 text-[13px]">{script.name}</div>
                            <div className="text-[10px] text-slate-400 dark:text-slate-500 font-mono mt-0.5">{script.id}</div>
                          </td>
                          <td className="px-6 py-3.5 text-[12px] font-semibold text-slate-600 dark:text-slate-300">
                            {script.platform}
                          </td>
                          <td className="px-6 py-3.5">
                            <span className={`px-2 py-0.5 rounded text-[11px] font-medium ${script.category === 'change' ? 'bg-amber-500/10 text-amber-500' : 'bg-cyan-500/10 text-[#00a9ce]'}`}>
                              {script.category === 'change' ? (zh ? '配置下发' : 'Change') : (script.category === 'standard' ? (zh ? '性能指标' : 'Metric') : (zh ? '周期巡检' : 'Inspection'))}
                            </span>
                          </td>
                          <td className="px-6 py-3.5">
                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md text-[10px] font-bold uppercase bg-slate-100 dark:bg-slate-800/80 text-slate-500 dark:text-slate-400 border border-slate-200/50 dark:border-slate-700/50">
                              {script.script_type}
                            </span>
                          </td>
                          <td className="px-6 py-3.5">
                            <span className={`inline-flex px-2.5 py-0.5 rounded-full text-[9px] font-bold uppercase border ${STATUS_MAP[script.status]?.bg || STATUS_MAP.draft.bg} ${STATUS_MAP[script.status]?.color || STATUS_MAP.draft.color} ${STATUS_MAP[script.status]?.border || STATUS_MAP.draft.border}`}>
                              {getStatusLabel(script.status)}
                            </span>
                          </td>
                          <td className="px-6 py-3.5 text-[12px] text-slate-500 dark:text-slate-400 font-medium">
                            {script.submitter_name || script.author || 'system'}
                          </td>
                          <td className="px-6 py-3.5 text-[12px] text-slate-400 dark:text-slate-500 max-w-xs truncate" title={script.description}>
                            {script.description || '—'}
                          </td>
                          <td className="px-6 py-3.5 text-right">
                            <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                              <button
                                onClick={() => {
                                  setModalMode('create');
                                  setEditForm({
                                    ...script,
                                    id: `${script.id}_copy`,
                                    name: zh ? `${script.name} - 副本` : `${script.name} (Copy)`,
                                    status: 'draft',
                                    submitter_name: currentUser,
                                    approver_username: '',
                                    rejected_reason: '',
                                  });
                                  setIsModalOpen(true);
                                }}
                                className="p-1.5 text-slate-400 hover:text-[#00a9ce] dark:hover:text-[#00a9ce] transition-colors"
                                title={zh ? '克隆/复制为自定义脚本' : 'Clone/Copy as custom script'}
                              >
                                <Copy size={14} />
                              </button>
                              <button onClick={() => { setModalMode('edit'); setEditForm(script); setIsModalOpen(true); }} className="p-1.5 text-slate-400 hover:text-[#00a9ce] dark:hover:text-[#00a9ce] transition-colors"><Edit3 size={14} /></button>
                              {!isSystem && (
                                <button onClick={() => { if(window.confirm(zh?'删除？':'Delete?')) fetch(`/api/scripts/${script.id}`, {method:'DELETE', headers:getHeaders()}).then(fetchScripts) }} className="p-1.5 text-slate-400 hover:text-red-500 dark:hover:text-red-400 transition-colors"><Trash2 size={14} /></button>
                              )}
                            </div>
                          </td>
                        </motion.tr>
                      );
                    })
                  ) : (
                    <tr>
                      <td colSpan={8} className="px-6 py-12 text-center text-[12px] text-slate-400 italic">
                        {zh ? '暂无匹配的脚本数据' : 'No scripts found matching the filters'}
                      </td>
                    </tr>
                  )}
                </AnimatePresence>
              </tbody>
            </table>
          </div>
        </div>

      </div>


      <div className="px-10 py-5 bg-transparent border-t border-slate-200/10">
        <Pagination currentPage={currentPage} totalItems={totalScripts} itemsPerPage={pageSize} onPageChange={setCurrentPage} onItemsPerPageChange={(size) => { setPageSize(size); setCurrentPage(1); }} language={language} />
      </div>

      {/* Main Modal */}
      <AnimatePresence>
        {isModalOpen && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-6">
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setIsModalOpen(false)} className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
            <motion.div
              layout
              initial={{ opacity: 0, scale: 0.98 }}
              animate={{ opacity: 1, scale: 1, width: '1020px', height: '760px' }}
              exit={{ opacity: 0, scale: 0.98 }}
              className="relative bg-white dark:bg-slate-900 shadow-2xl flex flex-col overflow-hidden border border-white/10 rounded-[32px]"
            >
              <div className="px-10 py-5 border-b border-slate-100 dark:border-white/5 flex items-center justify-between shrink-0">
                <div className="flex items-center gap-4">
                  <div className="flex gap-1.5 mr-2">
                    <div className="w-3 h-3 rounded-full bg-red-500/80" />
                    <div className="w-3 h-3 rounded-full bg-yellow-500/80" />
                    <div className="w-3 h-3 rounded-full bg-green-500/80" />
                  </div>
                  <h3 className="text-[15px] font-bold text-slate-800 dark:text-white flex items-center gap-3">
                    {isReviewMode ? (zh ? '脚本审核' : 'Review Script') : (modalMode === 'create' ? (zh ? '新建脚本' : 'New Script') : (zh ? '脚本详情' : 'Script Detail'))}
                    {modalMode === 'edit' && (
                       <span className={`px-2 py-0.5 rounded-md text-[9px] font-bold border ${STATUS_MAP[editForm.status!]?.bg} ${STATUS_MAP[editForm.status!]?.color} ${STATUS_MAP[editForm.status!]?.border}`}>
                          {getStatusLabel(editForm.status!)}
                       </span>
                    )}
                  </h3>
                </div>
                <button onClick={() => setIsModalOpen(false)} className="p-2 text-slate-400 hover:text-slate-800 transition-all"><X size={20} /></button>
              </div>

              <div className="flex-1 flex overflow-hidden">
                <div className="w-[280px] p-8 border-r border-slate-100 dark:border-white/5 space-y-8 overflow-y-auto no-scrollbar">
                   <section className="space-y-5">
                      <div>
                         <label className={labelClass}>{zh ? '脚本名称' : 'NAME'}</label>
                         <input readOnly={isReadOnly} className={inputClass} value={editForm.name ?? ''} onChange={e => setEditForm({...editForm, name: e.target.value})} />
                      </div>
                      <div>
                         <label className={labelClass}>{zh ? '唯一标识' : 'ID'}</label>
                         <input disabled={modalMode === 'edit' || isReadOnly} className={inputClass} value={editForm.id ?? ''} onChange={e => setEditForm({...editForm, id: e.target.value.replace(/[^a-zA-Z0-9_\-]/g, '')})} />
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                         <div>
                            <label className={labelClass}>{zh ? '类型' : 'TYPE'}</label>
                            <select disabled={isReadOnly} className={inputClass} value={editForm.script_type ?? 'shell'} onChange={e => setEditForm({...editForm, script_type: e.target.value})}>
                              {SCRIPT_TYPE_OPTIONS.map(opt => (
                                <option key={opt.value} value={opt.value}>{zh ? opt.zh : opt.en}</option>
                              ))}
                              {/* 兜底：如果当前值不在已知列表中，仍然渲染原值，避免被静默改写 */}
                              {editForm.script_type && !SCRIPT_TYPE_OPTIONS.some(o => o.value === editForm.script_type) && (
                                <option value={editForm.script_type}>{editForm.script_type}</option>
                              )}
                            </select>
                         </div>
                         <div>
                            <label className={labelClass}>{zh ? '平台' : 'OS'}</label>
                            <select disabled={isReadOnly} className={inputClass} value={editForm.platform ?? 'Linux'} onChange={e => setEditForm({...editForm, platform: e.target.value})}>
                              {PLATFORM_OPTIONS.map(opt => (
                                <option key={opt.value} value={opt.value}>{zh ? opt.zh : opt.en}</option>
                              ))}
                              {editForm.platform && !PLATFORM_OPTIONS.some(o => o.value === editForm.platform) && (
                                <option value={editForm.platform}>{editForm.platform}</option>
                              )}
                            </select>
                         </div>
                      </div>
                      <div>
                         <label className={labelClass}>{zh ? '脚本分类' : 'CATEGORY'}</label>
                         <select disabled={isReadOnly} className={inputClass} value={editForm.category ?? 'inspection'} onChange={e => setEditForm({...editForm, category: e.target.value})}>
                            <option value="inspection">{zh ? '周期巡检/数据采集' : 'Inspection / Collection'}</option>
                            <option value="change">{zh ? '自动化变更/配置下发' : 'Automation Change'}</option>
                         </select>
                      </div>
                      <div>
                         <label className={labelClass}>{zh ? '描述信息' : 'DESC'}</label>
                         <textarea readOnly={isReadOnly} className={inputClass + " h-32 resize-none"} value={editForm.description ?? ''} onChange={e => setEditForm({...editForm, description: e.target.value})} />
                      </div>
                   </section>
                   
                   {editForm.rejected_reason && (
                     <section className="p-5 bg-rose-500/5 border border-rose-500/10 rounded-2xl">
                        <label className={labelClass + " text-rose-500"}><MessageSquare size={11} /> {zh ? '驳回原因' : 'REASON'}</label>
                        <p className="text-[12px] text-rose-600 dark:text-rose-400 leading-relaxed font-medium mt-2">{editForm.rejected_reason}</p>
                     </section>
                   )}
                </div>

                <div className="flex-1 flex flex-col bg-slate-50/30 dark:bg-black/10">
                   <div className="h-10 bg-slate-100/50 dark:bg-black/20 border-b border-slate-200/50 dark:border-white/5 flex items-center justify-between px-6 shrink-0">
                      <div className="flex items-center gap-2 text-[10px] font-bold text-slate-500 uppercase tracking-widest">
                         <Terminal size={14} className="text-[#00a9ce]" />
                         {zh ? '编辑器' : 'EDITOR'} / {editForm.script_type}
                      </div>
                      {!isReadOnly && (
                        <button onClick={handleFormat} className="px-3 py-1 bg-[#00a9ce]/10 text-[#00a9ce] rounded-lg text-[10px] font-bold border border-[#00a9ce]/20 flex items-center gap-1.5 hover:bg-[#00a9ce]/20 transition-all">
                          <Wand2 size={12} /> {zh ? '格式化' : 'FORMAT'}
                        </button>
                      )}
                   </div>
                   <textarea readOnly={isReadOnly} spellCheck={false} className={`flex-1 bg-transparent font-mono text-[13px] p-8 focus:outline-none resize-none leading-6 no-scrollbar ${isReadOnly ? 'text-slate-500 opacity-60' : 'text-slate-700 dark:text-slate-300'}`} value={editForm.content ?? ''} onChange={e => setEditForm({...editForm, content: e.target.value})} />
                   
                   <div className="h-20 bg-white dark:bg-black/10 border-t border-slate-100 dark:border-white/5 px-10 flex items-center justify-end gap-3 shrink-0">
                      {isReviewMode ? (
                        <>
                          <button onClick={() => setShowRejectPrompt(true)} className="px-10 py-2.5 bg-red-500/10 text-red-500 rounded-xl text-[12px] font-bold border border-red-500/20 hover:bg-red-500 hover:text-white transition-all uppercase tracking-widest">{zh ? '驳回审核' : 'REJECT'}</button>
                          <button onClick={() => handleAction('released')} className="px-14 py-2.5 bg-green-600 text-white rounded-xl text-[12px] font-bold shadow-lg shadow-green-600/20 active:scale-[0.98] transition-all uppercase tracking-widest">{zh ? '通过并发布' : 'APPROVE'}</button>
                        </>
                      ) : isReadOnly ? (
                        <button onClick={() => setIsModalOpen(false)} className="px-10 py-2.5 bg-slate-100 text-slate-500 rounded-xl text-[12px] font-bold transition-all uppercase tracking-widest">{zh ? '关闭窗口' : 'CLOSE'}</button>
                      ) : (
                        <>
                          <button onClick={() => handleAction('draft')} className="px-10 py-2.5 bg-slate-100 dark:bg-white/5 text-slate-500 dark:text-slate-400 rounded-xl text-[12px] font-bold transition-all uppercase tracking-widest">{zh ? '保存草稿' : 'DRAFT'}</button>
                          <button onClick={() => setShowConfirmModal(true)} className="px-14 py-2.5 bg-[#00a9ce] text-white rounded-xl text-[12px] font-bold shadow-xl shadow-[#00a9ce]/20 active:scale-[0.98] transition-all uppercase tracking-widest">{zh ? '提交审核' : 'SUBMIT'}</button>
                        </>
                      )}
                   </div>
                </div>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Searchable Confirm Audit Modal */}
      <AnimatePresence>
        {showConfirmModal && (
          <div className="fixed inset-0 z-[120] flex items-center justify-center p-6">
             <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setShowConfirmModal(false)} className="absolute inset-0 bg-black/60 backdrop-blur-md" />
             <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className="relative w-full max-w-sm bg-white dark:bg-slate-900 rounded-[32px] p-10 shadow-2xl border border-white/10">
                <Shield size={32} className="text-[#00a9ce] mb-6" />
                <h3 className="text-lg font-bold text-slate-800 dark:text-white mb-2">{zh ? '指派审核人' : 'Assign Reviewer'}</h3>
                
                <div className="mt-6 mb-8 relative">
                   <label className={labelClass}>{zh ? '审核人搜索' : 'SEARCH AUDITOR'}</label>
                   <div className="relative">
                      <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" size={14} />
                      <input 
                        type="text" 
                        placeholder={zh ? "输入用户名搜索..." : "Search user..."}
                        value={auditorSearch}
                        onFocus={() => setShowAuditorDropdown(true)}
                        onChange={(e) => setAuditorSearch(e.target.value)}
                        className="w-full bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl pl-11 pr-4 py-3 text-[13px] text-slate-700 dark:text-white outline-none focus:ring-2 focus:ring-[#00a9ce]/20"
                      />
                   </div>

                   <AnimatePresence>
                      {showAuditorDropdown && (
                        <motion.div 
                          initial={{ opacity: 0, y: -10 }} 
                          animate={{ opacity: 1, y: 0 }} 
                          exit={{ opacity: 0, y: -10 }}
                          className="absolute z-[130] left-0 right-0 mt-2 bg-white dark:bg-slate-800 border border-slate-100 dark:border-white/10 rounded-2xl shadow-2xl max-h-48 overflow-y-auto no-scrollbar"
                        >
                           {availableReviewers.length > 0 ? (
                             availableReviewers.map(u => (
                               <div 
                                 key={u.username} 
                                 onClick={() => { setEditForm({...editForm, approver_username: u.username}); setAuditorSearch(u.username); setShowAuditorDropdown(false); }}
                                 className={`px-5 py-3 text-[13px] cursor-pointer hover:bg-[#00a9ce]/10 transition-all flex items-center justify-between ${editForm.approver_username === u.username ? 'bg-[#00a9ce]/10 text-[#00a9ce]' : 'text-slate-600 dark:text-slate-300'}`}
                               >
                                  {u.username}
                                  {editForm.approver_username === u.username && <CheckCircle2 size={14} />}
                               </div>
                             ))
                           ) : (
                             <div className="px-5 py-6 text-center text-[12px] text-slate-400 italic">{zh ? '未找到相关用户' : 'No users found'}</div>
                           )}
                        </motion.div>
                      )}
                   </AnimatePresence>
                </div>

                <div className="flex flex-col gap-3">
                  <button 
                    disabled={!editForm.approver_username} 
                    onClick={() => handleAction('pending_audit')} 
                    className="w-full py-4 bg-[#00a9ce] text-white rounded-2xl text-[13px] font-bold shadow-xl shadow-[#00a9ce]/20 disabled:opacity-30 active:scale-[0.98] transition-all"
                  >
                    {zh ? '发送审核申请' : 'SUBMIT FOR REVIEW'}
                  </button>
                  <button onClick={() => setShowConfirmModal(false)} className="w-full py-3 text-[12px] font-bold text-slate-400 hover:text-slate-600 transition-colors uppercase tracking-widest">{zh ? '取消' : 'CANCEL'}</button>
                </div>
             </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Reject Reason Prompt */}
      <AnimatePresence>
        {showRejectPrompt && (
          <div className="fixed inset-0 z-[120] flex items-center justify-center p-6">
             <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setShowRejectPrompt(false)} className="absolute inset-0 bg-black/60 backdrop-blur-md" />
             <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className="relative w-full max-w-sm bg-white dark:bg-slate-900 rounded-[32px] p-10 shadow-2xl border border-white/10">
                <XCircle size={32} className="text-red-500 mb-6" />
                <h3 className="text-lg font-bold text-slate-800 dark:text-white mb-2">{zh ? '驳回审核' : 'Reject Submission'}</h3>
                <p className="text-[12px] text-slate-400 mb-6">{zh ? '请说明驳回原因，提交人将收到反馈。' : 'Provide a reason for rejection.'}</p>
                <textarea value={rejectReason} onChange={e => setRejectReason(e.target.value)} className="w-full bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl px-4 py-3 text-[13px] h-32 resize-none mb-8 outline-none" placeholder={zh ? "请输入驳回原因..." : "Reason..."} />
                <button disabled={!rejectReason.trim()} onClick={() => handleAction('rejected', rejectReason)} className="w-full py-4 bg-red-500 text-white rounded-2xl text-[13px] font-bold shadow-xl shadow-red-500/20 disabled:opacity-30">
                  {zh ? '执行驳回' : 'REJECT'}
                </button>
             </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default ScriptManagementTab;
