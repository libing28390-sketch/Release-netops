import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  FileCode, Plus, Search, RefreshCw, Edit2, Trash2, X, Save, Eye, Copy,
  CheckCircle2, AlertCircle, Loader2, PlayCircle, Download, Upload,
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import PageHero from '../components/PageHero';
import Pagination from '../components/Pagination';
import { alertPanelClass } from '../components/shared';
import { useAlertOverlayDismiss } from './alertManagementShared';

interface Props {
  t: (key: string) => string;
  language: string;
}

interface Template {
  filename: string;
  platform: string;
  command: string;
  source: 'builtin' | 'custom';
  stem?: string;
}

interface TestResult {
  records: Array<Record<string, any>>;
  count: number;
  fields: string[];
}

const SAMPLE_PLATFORMS = [
  { value: '', label: '全部平台', labelEn: 'All Platforms' },
  { value: 'cisco_ios', label: 'Cisco IOS' },
  { value: 'cisco_nxos', label: 'Cisco NX-OS' },
  { value: 'cisco_xr', label: 'Cisco IOS-XR' },
  { value: 'cisco_asa', label: 'Cisco ASA' },
  { value: 'huawei_vrp', label: '华为 VRPv5' },
  { value: 'huawei_vrpv8', label: '华为 VRPv8' },
  { value: 'hp_comware', label: 'H3C Comware' },
  { value: 'juniper_junos', label: 'Juniper JunOS' },
  { value: 'arista_eos', label: 'Arista EOS' },
  { value: 'paloalto_panos', label: 'Palo Alto' },
  { value: 'fortinet', label: 'Fortinet' },
  { value: 'hillstone_stoneos', label: '山石 StoneOS' },
  { value: 'ruijie_os', label: '锐捷 RGOS' },
];

const DEFAULT_TEMPLATE_CONTENT = `Value EXAMPLE_FIELD (\\S+)

Start
  # 示例：匹配 "CPU: 23%"
  ^CPU:\\s+\${EXAMPLE_FIELD}% -> Record
`;

const TextFSMTemplatesTab: React.FC<Props> = ({ language }) => {
  const isZh = language === 'zh';

  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [platformFilter, setPlatformFilter] = useState('');
  const [sourceFilter, setSourceFilter] = useState<'' | 'builtin' | 'custom'>('');

  const [editorOpen, setEditorOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<Template | null>(null);
  const [editorPlatform, setEditorPlatform] = useState('');
  const [editorCommand, setEditorCommand] = useState('');
  const [editorContent, setEditorContent] = useState(DEFAULT_TEMPLATE_CONTENT);
  const [editorReadonly, setEditorReadonly] = useState(false);
  const [saving, setSaving] = useState(false);

  const [sampleOutput, setSampleOutput] = useState('');
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [testError, setTestError] = useState('');
  const [testing, setTesting] = useState(false);

  const [confirmDelete, setConfirmDelete] = useState<Template | null>(null);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const showToast = (type: 'success' | 'error', text: string) => {
    setToast({ type, text });
    setTimeout(() => setToast(null), 3500);
  };

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [total, setTotal] = useState(0);

  const authHeaders = useMemo(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

  const fetchTemplates = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (platformFilter) params.set('platform', platformFilter);
      if (search) params.set('search', search);
      if (sourceFilter) params.set('source', sourceFilter);
      params.set('page', String(page));
      params.set('page_size', String(pageSize));
      
      const res = await fetch(`/api/textfsm/templates?${params.toString()}`, { headers: authHeaders });
      if (res.ok) {
        const json = await res.json();
        setTemplates(json?.data?.items || []);
        setTotal(json?.data?.total || 0);
      }
    } catch (e) { /* noop */ }
    setLoading(false);
  }, [platformFilter, search, sourceFilter, page, pageSize, authHeaders]);

  useEffect(() => { fetchTemplates(); }, [fetchTemplates]);

  // Reset page on filter change
  useEffect(() => {
    setPage(1);
  }, [search, platformFilter, sourceFilter]);

  useAlertOverlayDismiss(editorOpen, () => setEditorOpen(false));
  useAlertOverlayDismiss(!!confirmDelete, () => setConfirmDelete(null));

  const openNewEditor = () => {
    setEditingTemplate(null);
    setEditorPlatform('cisco_ios');
    setEditorCommand('');
    setEditorContent(DEFAULT_TEMPLATE_CONTENT);
    setEditorReadonly(false);
    setSampleOutput('');
    setTestResult(null);
    setTestError('');
    setEditorOpen(true);
  };

  const openEditor = async (tpl: Template) => {
    try {
      const res = await fetch(`/api/textfsm/templates/${tpl.filename}`, { headers: authHeaders });
      if (!res.ok) throw new Error('Fetch failed');
      const json = await res.json();
      setEditingTemplate(tpl);
      setEditorPlatform(tpl.platform);
      setEditorCommand(tpl.command);
      setEditorContent(json?.data?.content || '');
      setEditorReadonly(tpl.source === 'builtin');
      setSampleOutput('');
      setTestResult(null);
      setTestError('');
      setEditorOpen(true);
    } catch {
      showToast('error', isZh ? '加载模板失败' : 'Failed to load template');
    }
  };

  const generateFilename = () => {
    if (!editorPlatform || !editorCommand) return '';
    const cmd = editorCommand.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    return `${editorPlatform}_${cmd}.textfsm`;
  };

  const handleSave = async () => {
    if (!editorContent.trim()) {
      showToast('error', isZh ? '模板内容不能为空' : 'Content cannot be empty');
      return;
    }
    setSaving(true);
    try {
      const filename = editingTemplate?.filename || generateFilename();
      if (!filename) {
        showToast('error', isZh ? '请填写平台和命令' : 'Platform and command required');
        setSaving(false);
        return;
      }

      const method = editingTemplate ? 'PUT' : 'POST';
      const url = editingTemplate
        ? `/api/textfsm/templates/${editingTemplate.filename}`
        : '/api/textfsm/templates';
      const body = editingTemplate
        ? { content: editorContent }
        : { platform: editorPlatform, command: editorCommand, content: editorContent };

      const res = await fetch(url, {
        method,
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const json = await res.json();
      if (res.ok && json.success) {
        showToast('success', isZh ? '模板已保存' : 'Template saved');
        setEditorOpen(false);
        await fetchTemplates();
      } else {
        showToast('error', json.detail || json.message || (isZh ? '保存失败' : 'Save failed'));
      }
    } catch (e) {
      showToast('error', isZh ? '网络错误' : 'Network error');
    }
    setSaving(false);
  };

  const handleTest = async () => {
    if (!editorContent.trim() || !sampleOutput.trim()) {
      setTestError(isZh ? '请提供模板内容和样本输出' : 'Template and sample required');
      return;
    }
    setTesting(true);
    setTestError('');
    setTestResult(null);
    try {
      const res = await fetch('/api/textfsm/test', {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: editorContent, sample_output: sampleOutput }),
      });
      const json = await res.json();
      if (res.ok && json.success) {
        setTestResult(json.data);
        if (json.data.count === 0) {
          setTestError(json.message || (isZh ? '模板未匹配到任何记录' : 'No records matched'));
        }
      } else {
        setTestError(json.message || (isZh ? '测试失败' : 'Test failed'));
      }
    } catch (e) {
      setTestError(isZh ? '网络错误' : 'Network error');
    }
    setTesting(false);
  };

  const handleDelete = async (tpl: Template) => {
    try {
      const res = await fetch(`/api/textfsm/templates/${tpl.filename}`, {
        method: 'DELETE',
        headers: authHeaders,
      });
      const json = await res.json();
      if (res.ok && json.success) {
        showToast('success', isZh ? '模板已删除' : 'Template deleted');
        setConfirmDelete(null);
        await fetchTemplates();
      } else {
        showToast('error', json.detail || (isZh ? '删除失败' : 'Delete failed'));
      }
    } catch {
      showToast('error', isZh ? '网络错误' : 'Network error');
    }
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden min-h-0">
      <PageHero
        icon={FileCode}
        title={isZh ? 'TextFSM 解析模板' : 'TextFSM Parse Templates'}
        subtitle={isZh ? '管理设备 CLI 输出解析模板，支持自定义覆盖内置模板' : 'Manage CLI output parsing templates; custom templates override built-ins'}
        actions={
          <>
            <button
              onClick={fetchTemplates}
              className="p-2 rounded-lg text-black/40 hover:text-[#00bceb] hover:bg-[#00bceb]/5 transition-colors"
              title={isZh ? '刷新' : 'Refresh'}
            >
              <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
            </button>
            <button
              onClick={openNewEditor}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#00bceb] text-white text-xs font-semibold hover:bg-[#00a5d0] shadow-sm shadow-[#00bceb]/20"
            >
              <Plus size={13} />
              {isZh ? '新建模板' : 'New Template'}
            </button>
          </>
        }
      />

      <div className="flex-1 flex flex-col overflow-hidden px-6 py-5 space-y-3 min-h-0">
      {/* Toast */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: -12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }}
            className={`fixed top-20 right-6 z-50 flex items-center gap-2 px-4 py-2.5 rounded-xl shadow-lg border ${
              toast.type === 'success' ? 'bg-emerald-50 border-emerald-200 text-emerald-800' : 'bg-red-50 border-red-200 text-red-800'
            }`}
          >
            {toast.type === 'success' ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
            <span className="text-sm font-medium">{toast.text}</span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Filters */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1 max-w-md">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-black/30" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={isZh ? '搜索模板名称或命令...' : 'Search filename or command...'}
            className="w-full pl-9 pr-3 py-2 rounded-lg bg-white border border-black/10 text-xs focus:outline-none focus:border-[#00bceb]"
          />
        </div>
        <select
          value={platformFilter}
          onChange={(e) => setPlatformFilter(e.target.value)}
          className="px-3 py-2 rounded-lg bg-white border border-black/10 text-xs focus:outline-none focus:border-[#00bceb]"
        >
          {SAMPLE_PLATFORMS.map((p) => (
            <option key={p.value} value={p.value}>{isZh ? p.label : (p.labelEn || p.label)}</option>
          ))}
        </select>
        <select
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value as any)}
          className="px-3 py-2 rounded-lg bg-white border border-black/10 text-xs focus:outline-none focus:border-[#00bceb]"
        >
          <option value="">{isZh ? '全部来源' : 'All Sources'}</option>
          <option value="builtin">{isZh ? '内置' : 'Built-in'}</option>
          <option value="custom">{isZh ? '自定义' : 'Custom'}</option>
        </select>
      </div>

      <div className={`${alertPanelClass} flex-1 min-h-0 flex flex-col overflow-hidden`}>
        {/* Templates Table */}
        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
          <table className="w-full text-xs">
            <thead className="bg-slate-50/80 text-black/40 text-[11px] font-semibold uppercase tracking-wider sticky top-0 z-10 border-b border-black/5">
              <tr>
                <th className="text-left px-4 py-2.5">{isZh ? '文件名' : 'Filename'}</th>
                <th className="text-left px-4 py-2.5">{isZh ? '平台' : 'Platform'}</th>
                <th className="text-left px-4 py-2.5">{isZh ? '命令' : 'Command'}</th>
                <th className="text-left px-4 py-2.5">{isZh ? '来源' : 'Source'}</th>
                <th className="text-right px-4 py-2.5">{isZh ? '操作' : 'Actions'}</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={5} className="text-center py-10 text-black/30"><Loader2 size={20} className="animate-spin inline-block" /></td></tr>
              )}
              {!loading && templates.length === 0 && (
                <tr><td colSpan={5} className="text-center py-10 text-black/30">{isZh ? '没有匹配的模板' : 'No templates found'}</td></tr>
              )}
              {!loading && templates.map((tpl) => (
                <tr key={tpl.filename} className="border-t border-black/[0.03] hover:bg-slate-50/50 transition-colors">
                  <td className="px-4 py-2.5 font-mono text-[11px] text-black/70">{tpl.filename}</td>
                  <td className="px-4 py-2.5">
                    <span className="px-2 py-0.5 rounded bg-slate-100 text-black/60 text-[10px] font-semibold">{tpl.platform}</span>
                  </td>
                  <td className="px-4 py-2.5 text-black/60">{tpl.command || '—'}</td>
                  <td className="px-4 py-2.5">
                    {tpl.source === 'custom' ? (
                      <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 text-[10px] font-bold">{isZh ? '自定义' : 'Custom'}</span>
                    ) : (
                      <span className="px-2 py-0.5 rounded-full bg-cyan-100 text-cyan-700 text-[10px] font-bold">{isZh ? '内置' : 'Built-in'}</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <div className="inline-flex items-center gap-1">
                      <button
                        onClick={() => openEditor(tpl)}
                        className="p-1.5 rounded text-black/30 hover:text-cyan-600 hover:bg-cyan-50 transition-colors"
                        title={tpl.source === 'builtin' ? (isZh ? '查看' : 'View') : (isZh ? '编辑' : 'Edit')}
                      >
                        {tpl.source === 'builtin' ? <Eye size={13} /> : <Edit2 size={13} />}
                      </button>
                      {tpl.source === 'custom' && (
                        <button
                          onClick={() => setConfirmDelete(tpl)}
                          className="p-1.5 rounded text-black/30 hover:text-red-500 hover:bg-red-50 transition-colors"
                          title={isZh ? '删除' : 'Delete'}
                        >
                          <Trash2 size={13} />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex-shrink-0">
          <Pagination
            currentPage={page}
            totalItems={total}
            itemsPerPage={pageSize}
            onPageChange={setPage}
            onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }}
            language={language}
            alwaysVisible
          />
        </div>
      </div>

      {/* Editor Modal */}
      <AnimatePresence>
        {editorOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
            <motion.div
              initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.97 }}
              className="bg-white rounded-2xl shadow-xl w-full max-w-6xl max-h-[92vh] overflow-hidden flex flex-col"
            >
              <div className="px-5 py-3 border-b border-black/5 flex items-center justify-between bg-slate-50/50">
                <h3 className="text-sm font-bold flex items-center gap-2">
                  <FileCode size={16} className="text-cyan-500" />
                  {editingTemplate
                    ? (editorReadonly ? (isZh ? '查看模板' : 'View Template') : (isZh ? '编辑模板' : 'Edit Template'))
                    : (isZh ? '新建模板' : 'New Template')}
                  {editingTemplate && (
                    <span className="font-mono text-[11px] text-black/40 ml-2">{editingTemplate.filename}</span>
                  )}
                </h3>
                <button onClick={() => setEditorOpen(false)} className="p-1 rounded hover:bg-black/5"><X size={16} /></button>
              </div>

              <div className="flex-1 overflow-y-auto p-5 grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Left: Editor */}
                <div className="flex flex-col gap-3 min-h-0">
                  {!editingTemplate && (
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="text-[11px] font-semibold text-black/50 uppercase tracking-wider">{isZh ? '平台' : 'Platform'}</label>
                        <select
                          value={editorPlatform}
                          onChange={(e) => setEditorPlatform(e.target.value)}
                          className="w-full mt-1 px-2.5 py-1.5 rounded-lg border border-black/10 text-xs focus:outline-none focus:border-[#00bceb]"
                        >
                          {SAMPLE_PLATFORMS.filter((p) => p.value).map((p) => (
                            <option key={p.value} value={p.value}>{p.label}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="text-[11px] font-semibold text-black/50 uppercase tracking-wider">{isZh ? '命令' : 'Command'}</label>
                        <input
                          value={editorCommand}
                          onChange={(e) => setEditorCommand(e.target.value)}
                          placeholder="show processes cpu"
                          className="w-full mt-1 px-2.5 py-1.5 rounded-lg border border-black/10 text-xs focus:outline-none focus:border-[#00bceb]"
                        />
                      </div>
                    </div>
                  )}

                  {!editingTemplate && generateFilename() && (
                    <div className="text-[11px] text-black/40">
                      {isZh ? '文件名:' : 'Filename:'} <span className="font-mono text-black/60">{generateFilename()}</span>
                    </div>
                  )}

                  <div className="flex-1 flex flex-col min-h-0">
                    <label className="text-[11px] font-semibold text-black/50 uppercase tracking-wider mb-1">
                      {isZh ? '模板内容' : 'Template Content'}
                      {editorReadonly && <span className="ml-2 text-amber-600">（{isZh ? '只读' : 'Read-only'}）</span>}
                    </label>
                    <textarea
                      value={editorContent}
                      onChange={(e) => setEditorContent(e.target.value)}
                      readOnly={editorReadonly}
                      className={`flex-1 min-h-[280px] font-mono text-[12px] leading-5 p-3 rounded-lg border border-black/10 focus:outline-none focus:border-[#00bceb] ${editorReadonly ? 'bg-slate-50' : 'bg-white'}`}
                      spellCheck={false}
                    />
                  </div>
                </div>

                {/* Right: Test */}
                <div className="flex flex-col gap-3 min-h-0">
                  <div className="flex-1 flex flex-col min-h-0">
                    <label className="text-[11px] font-semibold text-black/50 uppercase tracking-wider mb-1">
                      {isZh ? '样本输出' : 'Sample Output'}
                    </label>
                    <textarea
                      value={sampleOutput}
                      onChange={(e) => setSampleOutput(e.target.value)}
                      placeholder={isZh ? '粘贴设备真实 CLI 输出...' : 'Paste real CLI output from device...'}
                      className="flex-1 min-h-[140px] font-mono text-[11px] leading-5 p-3 rounded-lg border border-black/10 bg-white focus:outline-none focus:border-[#00bceb]"
                      spellCheck={false}
                    />
                  </div>

                  <button
                    onClick={handleTest}
                    disabled={testing}
                    className="flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-xs font-semibold disabled:opacity-50"
                  >
                    {testing ? <Loader2 size={13} className="animate-spin" /> : <PlayCircle size={13} />}
                    {isZh ? '测试解析' : 'Test Parse'}
                  </button>

                  <div className="flex-1 flex flex-col min-h-0">
                    <label className="text-[11px] font-semibold text-black/50 uppercase tracking-wider mb-1">
                      {isZh ? '解析结果' : 'Parse Result'}
                    </label>
                    <div className="flex-1 min-h-[140px] rounded-lg border border-black/10 bg-slate-50 p-3 overflow-auto">
                      {testError && (
                        <div className="text-xs text-red-600 flex items-start gap-2">
                          <AlertCircle size={14} className="shrink-0 mt-0.5" />
                          <span>{testError}</span>
                        </div>
                      )}
                      {testResult && testResult.count > 0 && (
                        <>
                          <div className="text-[11px] text-emerald-600 font-semibold mb-2">
                            ✓ {isZh ? `解析出 ${testResult.count} 条记录，字段: ${testResult.fields.join(', ')}` : `Parsed ${testResult.count} record(s), fields: ${testResult.fields.join(', ')}`}
                          </div>
                          <pre className="font-mono text-[11px] text-black/70 whitespace-pre-wrap">
                            {JSON.stringify(testResult.records, null, 2)}
                          </pre>
                        </>
                      )}
                      {!testResult && !testError && (
                        <div className="text-xs text-black/30 text-center py-6">
                          {isZh ? '粘贴样本输出后点击"测试解析"' : 'Paste sample output and click "Test Parse"'}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              <div className="px-5 py-3 border-t border-black/5 bg-slate-50/50 flex justify-end gap-2">
                <button
                  onClick={() => setEditorOpen(false)}
                  className="px-4 py-2 rounded-lg text-xs font-semibold text-black/60 hover:bg-black/5"
                >
                  {isZh ? '取消' : 'Cancel'}
                </button>
                {!editorReadonly && (
                  <button
                    onClick={handleSave}
                    disabled={saving}
                    className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#00bceb] text-white text-xs font-semibold hover:bg-[#00a5d0] disabled:opacity-50"
                  >
                    {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                    {isZh ? '保存模板' : 'Save Template'}
                  </button>
                )}
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Delete Confirm */}
      <AnimatePresence>
        {confirmDelete && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.95 }}
              className="bg-white rounded-xl shadow-xl w-full max-w-md overflow-hidden"
            >
              <div className="p-5">
                <div className="flex items-center gap-3 mb-3 text-red-600">
                  <AlertCircle size={22} />
                  <h3 className="text-base font-bold">{isZh ? '确认删除' : 'Confirm Delete'}</h3>
                </div>
                <p className="text-sm text-black/60 mb-2">
                  {isZh ? '确定删除以下自定义模板？此操作不可恢复。' : 'Delete this custom template? This cannot be undone.'}
                </p>
                <p className="font-mono text-xs bg-slate-50 px-3 py-2 rounded mb-4">{confirmDelete.filename}</p>
              </div>
              <div className="px-5 py-3 bg-slate-50/50 border-t border-black/5 flex justify-end gap-2">
                <button
                  onClick={() => setConfirmDelete(null)}
                  className="px-4 py-2 rounded-lg text-xs font-semibold text-black/60 hover:bg-black/5"
                >
                  {isZh ? '取消' : 'Cancel'}
                </button>
                <button
                  onClick={() => handleDelete(confirmDelete)}
                  className="px-4 py-2 rounded-lg text-xs font-semibold bg-red-500 text-white hover:bg-red-600 shadow-sm"
                >
                  {isZh ? '确认删除' : 'Delete'}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
      </div>
    </div>
  );
};

export default TextFSMTemplatesTab;
