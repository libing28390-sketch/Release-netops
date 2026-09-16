import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Tags, Plus, Search, X, Pencil, Trash2, RefreshCw, Hash, ChevronDown, ChevronRight,
  Server, Shield, Cpu, Globe, Layers, Settings2, BarChart3, Check, AlertCircle
} from 'lucide-react';
import type { TagDefinition, TagCategory, TagStatistics } from '../types';
import { TAG_CATEGORY_LABELS } from '../types';
import PageHero from '../components/PageHero';
import Pagination from '../components/Pagination';
import { DataTable } from '../components/DataTable';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../components/ui/ActionIconButton';

/* ─── Props ─── */
interface TagManagementTabProps {
  language: string;
  t: (key: string) => string;
  currentUser?: { role?: string };
}

/* ─── Category icon/color mapping ─── */
const CATEGORY_META: Record<string, { icon: typeof Tags; color: string; bg: string }> = {
  business:    { icon: Layers, color: 'text-blue-600', bg: 'bg-blue-50 border-blue-200' },
  environment: { icon: Globe, color: 'text-cyan-600', bg: 'bg-cyan-50 border-cyan-200' },
  network_zone:{ icon: Server, color: 'text-violet-600', bg: 'bg-violet-50 border-violet-200' },
  operations:  { icon: Settings2, color: 'text-rose-600', bg: 'bg-rose-50 border-rose-200' },
  security:    { icon: Shield, color: 'text-red-600', bg: 'bg-red-50 border-red-200' },
  project:     { icon: Hash, color: 'text-slate-600', bg: 'bg-slate-50 border-slate-200' },
  lifecycle:   { icon: BarChart3, color: 'text-amber-600', bg: 'bg-amber-50 border-amber-200' },
  technology:  { icon: Cpu, color: 'text-indigo-600', bg: 'bg-indigo-50 border-indigo-200' },
  system_auto: { icon: Cpu, color: 'text-emerald-600', bg: 'bg-emerald-50 border-emerald-200' },
};

const CATEGORIES: TagCategory[] = ['business', 'environment', 'network_zone', 'operations', 'security', 'project', 'lifecycle', 'technology', 'system_auto'];

/* ─── Helper ─── */
function getToken() {
  return localStorage.getItem('netops_token') || '';
}

function authHeaders() {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
}

/* ─────────────────────────────────────────── */
export default function TagManagementTab({ language, currentUser }: TagManagementTabProps) {
  const zh = language === 'zh';
  const canManageTags = currentUser?.role === 'Administrator';

  /* ── State ── */
  const [tags, setTags] = useState<TagDefinition[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<TagCategory | ''>('');
  const [usageFilter, setUsageFilter] = useState<'all' | 'used' | 'unused'>('all');
  const [activityFilter, setActivityFilter] = useState<'all' | 'active' | 'inactive'>('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [categoryPanelCollapsed, setCategoryPanelCollapsed] = useState(false);
  const [stats, setStats] = useState<TagStatistics | null>(null);

  // Modal state
  const [showModal, setShowModal] = useState(false);
  const [editingTag, setEditingTag] = useState<TagDefinition | null>(null);
  const [formData, setFormData] = useState({
    category: 'business' as TagCategory,
    code: '',
    label: '',
    label_zh: '',
    color: '',
    icon: '',
    description: '',
    sort_order: 0,
  });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');
  const normalizedTagCode = formData.code.trim().toLowerCase();
  const tagCodeIsValid = /^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$/.test(normalizedTagCode)
    && normalizedTagCode.length <= 96;

  // Delete state
  const [deleteTarget, setDeleteTarget] = useState<TagDefinition | null>(null);
  const [deleting, setDeleting] = useState(false);

  /* ── Fetch tags ── */
  const fetchTags = useCallback(async () => {
    setLoading(true);
    try {
      const url = categoryFilter
        ? `/api/tags/definitions?category=${categoryFilter}`
        : '/api/tags/definitions';
      const resp = await fetch(url, { headers: authHeaders() });
      if (!resp.ok) throw new Error('Failed');
      const json = await resp.json();
      setTags(json.data || []);
    } catch {
      setTags([]);
    } finally {
      setLoading(false);
    }
  }, [categoryFilter]);

  const fetchStats = useCallback(async () => {
    try {
      const resp = await fetch('/api/tags/statistics', { headers: authHeaders() });
      if (!resp.ok) return;
      const json = await resp.json();
      setStats(json.data || null);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { void fetchTags(); }, [fetchTags]);
  useEffect(() => { void fetchStats(); }, [fetchStats]);

  /* ── Filtered + grouped ── */
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return tags
      .filter(tag => {
        if (usageFilter === 'used' && (tag.assignment_count || 0) === 0) return false;
        if (usageFilter === 'unused' && (tag.assignment_count || 0) > 0) return false;
        if (activityFilter === 'active' && tag.is_active === 0) return false;
        if (activityFilter === 'inactive' && tag.is_active !== 0) return false;
        if (!q) return true;
        return tag.code.toLowerCase().includes(q) ||
          tag.label.toLowerCase().includes(q) ||
          (tag.label_zh && tag.label_zh.toLowerCase().includes(q)) ||
          (tag.description && tag.description.toLowerCase().includes(q));
      })
      .sort((a, b) => (a.sort_order - b.sort_order) || a.code.localeCompare(b.code));
  }, [activityFilter, search, tags, usageFilter]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const paginatedTags = useMemo(() => {
    const start = (safePage - 1) * pageSize;
    return filtered.slice(start, start + pageSize);
  }, [filtered, pageSize, safePage]);

  useEffect(() => {
    setPage(1);
  }, [activityFilter, categoryFilter, search, usageFilter, pageSize]);

  useEffect(() => {
    if (page > pageCount) setPage(pageCount);
  }, [page, pageCount]);

  const hasFilters = Boolean(search || categoryFilter || usageFilter !== 'all' || activityFilter !== 'all');

  const clearFilters = () => {
    setSearch('');
    setCategoryFilter('');
    setUsageFilter('all');
    setActivityFilter('all');
  };

  /* ── Modal: open for create / edit ── */
  const openCreateModal = () => {
    setEditingTag(null);
    setFormData({ category: 'business', code: '', label: '', label_zh: '', color: '', icon: '', description: '', sort_order: 0 });
    setFormError('');
    setShowModal(true);
  };

  const openEditModal = (tag: TagDefinition) => {
    setEditingTag(tag);
    setFormData({
      category: tag.category,
      code: tag.code,
      label: tag.label,
      label_zh: tag.label_zh || '',
      color: tag.color || '',
      icon: tag.icon || '',
      description: tag.description || '',
      sort_order: tag.sort_order ?? 0,
    });
    setFormError('');
    setShowModal(true);
  };

  /* ── Save (create / update) ── */
  const handleSave = async () => {
    if (!formData.code.trim() || !formData.label.trim()) {
      setFormError(zh ? '标签代码和英文标签不能为空' : 'Code and label are required');
      return;
    }
    if (!tagCodeIsValid) {
      setFormError(zh
        ? '标签代码必须以小写字母开头，仅可使用小写字母、数字、点、短横线或下划线，最长 96 个字符'
        : 'Code must start with a lowercase letter and contain only lowercase letters, digits, dot, dash, or underscore (max 96 characters)');
      return;
    }
    setSaving(true);
    setFormError('');
    try {
      if (editingTag) {
        // update
        const resp = await fetch(`/api/tags/definitions/${editingTag.id}`, {
          method: 'PUT',
          headers: authHeaders(),
          body: JSON.stringify({
            label: formData.label,
            label_zh: formData.label_zh,
            color: formData.color,
            icon: formData.icon,
            description: formData.description,
            sort_order: formData.sort_order,
          }),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          throw new Error(err.detail || 'Update failed');
        }
      } else {
        // create
        const resp = await fetch('/api/tags/definitions', {
          method: 'POST',
          headers: authHeaders(),
          body: JSON.stringify(formData),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          throw new Error(err.detail || 'Create failed');
        }
      }
      setShowModal(false);
      void fetchTags();
      void fetchStats();
    } catch (e: unknown) {
      setFormError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  /* ── Delete ── */
  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      const resp = await fetch(`/api/tags/definitions/${deleteTarget.id}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || 'Delete failed');
      }
      setDeleteTarget(null);
      void fetchTags();
      void fetchStats();
    } catch {
      // silently handle
    } finally {
      setDeleting(false);
    }
  };

  /* ────────────── render ────────────── */
  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={Tags}
        eyebrow={zh ? '资产与配置 / 标签管理' : 'Assets & Config / Tag Management'}
        title={zh ? '标签管理' : 'Tag Management'}
        subtitle={zh ? '管理设备分类标签，支持按类型、厂商、系统、角色、环境、功能等维度进行标签化分组。' : 'Manage device classification tags across type, vendor, OS, role, environment, and function dimensions.'}
        actions={
          <>
            {canManageTags && <button
              onClick={openCreateModal}
              className="inline-flex h-11 items-center justify-center gap-2 rounded-2xl bg-[#06b6d4] px-4 text-sm font-semibold text-white shadow-[0_12px_24px_rgba(6,182,212,0.22)] transition-all duration-200 hover:-translate-y-0.5 hover:bg-[#0891b2]"
            >
              <Plus size={14} />
              {zh ? '新建标签' : 'New Tag'}
            </button>}
            <button
              onClick={() => { void fetchTags(); void fetchStats(); }}
              className="inline-flex h-11 items-center justify-center gap-2 rounded-2xl border border-black/10 bg-white px-4 text-sm font-medium text-[#164e63] transition-all hover:border-[#06b6d4]/30 hover:bg-[#ecfeff]"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              {zh ? '刷新' : 'Refresh'}
            </button>
          </>
        }
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-4">
        {stats && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[
              { label: zh ? '标签总数' : 'Total Tags', value: stats.total_definitions, color: 'text-[#06b6d4]' },
              { label: zh ? '已使用标签' : 'Used Tags', value: stats.used_definitions, color: 'text-violet-600' },
              { label: zh ? '未使用标签' : 'Unused Tags', value: stats.unused_definitions, color: 'text-amber-600' },
              { label: zh ? '已标记设备' : 'Tagged Devices', value: stats.tagged_devices, color: 'text-emerald-600' },
            ].map((s, i) => (
              <div key={i} className="flex items-center gap-3 rounded-2xl border border-black/5 bg-white px-5 py-3.5 shadow-sm">
                <BarChart3 size={16} className={s.color} />
                <div>
                  <p className="text-xs text-black/40">{s.label}</p>
                  <p className={`text-lg font-bold ${s.color}`}>{s.value}</p>
                </div>
              </div>
            ))}
          </div>
        )}

        <div className={`grid grid-cols-1 items-start gap-4 ${categoryPanelCollapsed ? 'lg:grid-cols-[52px_minmax(0,1fr)]' : 'lg:grid-cols-[220px_minmax(0,1fr)]'}`}>
          <aside className="h-fit rounded-2xl border border-black/5 bg-white p-3 shadow-sm">
            <button
              type="button"
              onClick={() => setCategoryPanelCollapsed(collapsed => !collapsed)}
              className={`flex w-full items-center rounded-xl py-2 text-xs font-bold text-[#164e63] transition-colors hover:bg-[#ecfeff] ${categoryPanelCollapsed ? 'justify-center px-0' : 'justify-between px-2'}`}
              title={categoryPanelCollapsed ? (zh ? '展开标签分类' : 'Expand categories') : (zh ? '折叠标签分类' : 'Collapse categories')}
              aria-label={categoryPanelCollapsed ? (zh ? '展开标签分类' : 'Expand categories') : (zh ? '折叠标签分类' : 'Collapse categories')}
            >
              <span className="flex items-center gap-2"><Tags size={14} /><span className={categoryPanelCollapsed ? 'hidden' : ''}>{zh ? '标签分类' : 'Categories'}</span></span>
              {categoryPanelCollapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
            </button>
            {!categoryPanelCollapsed && <>
            <button
              onClick={() => setCategoryFilter('')}
              className={`flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-left text-xs font-semibold transition-all ${
                categoryFilter === '' ? 'bg-[#ecfeff] text-[#0e7490]' : 'text-black/55 hover:bg-black/[0.025]'
              }`}
            >
              <span className="flex items-center gap-2"><Tags size={14} />{zh ? '全部标签' : 'All Tags'}</span>
              <span className="tabular-nums text-[11px]">{stats?.total_definitions ?? tags.length}</span>
            </button>
            {CATEGORIES.map(cat => {
              const meta = CATEGORY_META[cat];
              const catLabel = TAG_CATEGORY_LABELS[cat];
              const CatIcon = meta?.icon || Tags;
              return (
                <button
                  key={cat}
                  onClick={() => setCategoryFilter(cat)}
                  className={`mt-0.5 flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-left text-xs font-semibold transition-all ${
                    categoryFilter === cat ? 'bg-[#ecfeff] text-[#0e7490]' : 'text-black/55 hover:bg-black/[0.025]'
                  }`}
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <CatIcon size={14} className={meta?.color} />
                    <span className="truncate">{zh ? catLabel?.zh : catLabel?.en}</span>
                  </span>
                  <span className="tabular-nums text-[11px]">{stats?.categories[cat] ?? 0}</span>
                </button>
              );
            })}
            </>}
          </aside>

          <section className="min-w-0 overflow-hidden rounded-2xl border border-black/5 bg-white shadow-sm">
            <div className="flex flex-col gap-3 border-b border-black/5 p-4 xl:flex-row xl:items-center">
              <label className="relative min-w-[240px] flex-1">
                <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-black/30" />
                <input
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder={zh ? '搜索名称、代码或描述...' : 'Search name, code, or description...'}
                  className="w-full rounded-xl border border-black/10 bg-white py-2.5 pl-9 pr-9 text-sm text-[#164e63] outline-none placeholder:text-black/30 focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10"
                />
                {search && (
                  <button onClick={() => setSearch('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-black/30 hover:text-black/60">
                    <X size={14} />
                  </button>
                )}
              </label>
              <select
                value={usageFilter}
                onChange={e => setUsageFilter(e.target.value as typeof usageFilter)}
                className="rounded-xl border border-black/10 bg-white px-3 py-2.5 text-xs font-semibold text-[#164e63] outline-none"
                aria-label={zh ? '使用状态' : 'Usage status'}
              >
                <option value="all">{zh ? '全部使用状态' : 'All usage states'}</option>
                <option value="used">{zh ? '已使用' : 'Used'}</option>
                <option value="unused">{zh ? '未使用' : 'Unused'}</option>
              </select>
              <select
                value={activityFilter}
                onChange={e => setActivityFilter(e.target.value as typeof activityFilter)}
                className="rounded-xl border border-black/10 bg-white px-3 py-2.5 text-xs font-semibold text-[#164e63] outline-none"
                aria-label={zh ? '启用状态' : 'Activity status'}
              >
                <option value="all">{zh ? '全部启用状态' : 'All activity states'}</option>
                <option value="active">{zh ? '已启用' : 'Active'}</option>
                <option value="inactive">{zh ? '已停用' : 'Inactive'}</option>
              </select>
              {hasFilters && (
                <button onClick={clearFilters} className="h-10 rounded-xl px-3 text-xs font-semibold text-[#0891b2] hover:bg-[#ecfeff]">
                  {zh ? '清空筛选' : 'Clear filters'}
                </button>
              )}
              <span className="whitespace-nowrap rounded-xl bg-[#f0f9ff] px-3 py-2.5 text-xs font-semibold text-[#164e63]">
                {zh ? `${filtered.length} 个标签` : `${filtered.length} tags`}
              </span>
            </div>

            <div className="overflow-x-auto">
              <DataTable className="min-w-[820px] text-left">
                <thead className="bg-slate-50/80 text-[11px] font-bold uppercase tracking-wider text-black/40">
                  <tr>
                    <th className="px-4 py-3">{zh ? '标签' : 'Tag'}</th>
                    <th className="px-4 py-3">{zh ? '代码' : 'Code'}</th>
                    <th className="px-4 py-3">{zh ? '分类' : 'Category'}</th>
                    <th className="px-4 py-3">{zh ? '来源' : 'Source'}</th>
                    <th className="px-4 py-3 text-right">{zh ? '分配数' : 'Assignments'}</th>
                    <th className="px-4 py-3">{zh ? '状态' : 'Status'}</th>
                    <th className="px-4 py-3 text-right">{zh ? '操作' : 'Actions'}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-black/5">
                  {!loading && paginatedTags.map(tag => (
                    <TagTableRow
                      key={tag.id}
                      tag={tag}
                      zh={zh}
                      canManage={canManageTags}
                      onEdit={() => openEditModal(tag)}
                      onDelete={() => setDeleteTarget(tag)}
                    />
                  ))}
                </tbody>
              </DataTable>
              {loading && (
                <div className="flex items-center justify-center py-16">
                  <RefreshCw size={20} className="animate-spin text-[#06b6d4]" />
                </div>
              )}
              {!loading && filtered.length === 0 && (
                <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
                  <Tags size={28} className="text-black/20" />
                  <p className="text-sm font-semibold text-black/45">{zh ? '没有符合条件的标签' : 'No matching tags'}</p>
                  <p className="text-xs text-black/30">{zh ? '可调整筛选条件，或清空筛选查看全部标签。' : 'Adjust the filters or clear them to view all tags.'}</p>
                </div>
              )}
            </div>
            {!loading && filtered.length > 0 && (
              <Pagination
                currentPage={safePage}
                totalItems={filtered.length}
                itemsPerPage={pageSize}
                onPageChange={setPage}
                onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }}
                language={language}
              />
            )}
          </section>
        </div>

      {/* ── Create / Edit Modal ── */}
      {showModal && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={() => setShowModal(false)}>
          <div className="w-full max-w-lg rounded-3xl border border-black/8 bg-white p-6 shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="mb-5 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-[#164e63]">
                {editingTag ? (zh ? '编辑标签' : 'Edit Tag') : (zh ? '新建标签' : 'New Tag')}
              </h3>
              <button onClick={() => setShowModal(false)} className="rounded-lg p-1.5 text-black/40 transition-colors hover:bg-black/5 hover:text-black/60">
                <X size={18} />
              </button>
            </div>

            <div className="space-y-4">
              {/* Category */}
              <div>
                <label className="text-xs font-semibold text-black/50">{zh ? '分类' : 'Category'}</label>
                <select
                  value={formData.category}
                  onChange={e => setFormData(p => ({ ...p, category: e.target.value as TagCategory }))}
                  disabled={!!editingTag}
                  className="mt-1 w-full rounded-xl border border-black/10 bg-white px-3 py-2.5 text-sm text-[#164e63] outline-none focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10 disabled:opacity-50"
                >
                  {CATEGORIES.map(c => (
                    <option key={c} value={c}>{zh ? TAG_CATEGORY_LABELS[c]?.zh : TAG_CATEGORY_LABELS[c]?.en}</option>
                  ))}
                </select>
              </div>

              {/* Stable code */}
              <div>
                <label className="text-xs font-semibold text-black/50">{zh ? '标签代码 (唯一标识)' : 'Tag code (stable ID)'}</label>
                <input
                  value={formData.code}
                  onChange={e => setFormData(p => ({ ...p, code: e.target.value.toLowerCase() }))}
                  disabled={!!editingTag}
                  placeholder="e.g. env.production"
                  className={`mt-1 w-full rounded-xl border bg-white px-3 py-2.5 text-sm font-mono text-[#164e63] outline-none focus:ring-2 disabled:opacity-50 ${
                    formData.code && !tagCodeIsValid
                      ? 'border-red-300 focus:border-red-400 focus:ring-red-100'
                      : 'border-black/10 focus:border-[#06b6d4]/40 focus:ring-[#06b6d4]/10'
                  }`}
                />
                <p className={`mt-1 text-[10px] ${formData.code && !tagCodeIsValid ? 'text-red-500' : 'text-black/30'}`}>
                  {zh
                    ? '格式：小写字母开头，可包含数字、点、短横线和下划线，例如 business.sales'
                    : 'Format: start with a lowercase letter; digits, dot, dash, and underscore are allowed, e.g. business.sales'}
                </p>
              </div>

              {/* label (en) + label_zh */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-black/50">{zh ? '英文标签' : 'Label (EN)'}</label>
                  <input
                    value={formData.label}
                    onChange={e => setFormData(p => ({ ...p, label: e.target.value }))}
                    placeholder="Cisco IOS-XE"
                    className="mt-1 w-full rounded-xl border border-black/10 bg-white px-3 py-2.5 text-sm text-[#164e63] outline-none focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-black/50">{zh ? '中文标签' : 'Label (ZH)'}</label>
                  <input
                    value={formData.label_zh}
                    onChange={e => setFormData(p => ({ ...p, label_zh: e.target.value }))}
                    placeholder="思科 IOS-XE"
                    className="mt-1 w-full rounded-xl border border-black/10 bg-white px-3 py-2.5 text-sm text-[#164e63] outline-none focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10"
                  />
                </div>
              </div>

              {/* Color + Icon */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-black/50">{zh ? '颜色' : 'Color'}</label>
                  <div className="mt-1 flex items-center gap-2">
                    <input
                      type="color"
                      value={formData.color || '#06b6d4'}
                      onChange={e => setFormData(p => ({ ...p, color: e.target.value }))}
                      className="h-10 w-10 cursor-pointer rounded-lg border border-black/10"
                    />
                    <input
                      value={formData.color}
                      onChange={e => setFormData(p => ({ ...p, color: e.target.value }))}
                      placeholder="#06b6d4"
                      className="flex-1 rounded-xl border border-black/10 bg-white px-3 py-2.5 text-sm font-mono text-[#164e63] outline-none focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10"
                    />
                  </div>
                </div>
                <div>
                  <label className="text-xs font-semibold text-black/50">{zh ? '图标' : 'Icon'}</label>
                  <input
                    value={formData.icon}
                    onChange={e => setFormData(p => ({ ...p, icon: e.target.value }))}
                    placeholder="server, shield, cpu..."
                    className="mt-1 w-full rounded-xl border border-black/10 bg-white px-3 py-2.5 text-sm text-[#164e63] outline-none focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10"
                  />
                </div>
              </div>

              {/* Description */}
              <div>
                <label className="text-xs font-semibold text-black/50">{zh ? '描述' : 'Description'}</label>
                <textarea
                  value={formData.description}
                  onChange={e => setFormData(p => ({ ...p, description: e.target.value }))}
                  rows={2}
                  className="mt-1 w-full resize-none rounded-xl border border-black/10 bg-white px-3 py-2.5 text-sm text-[#164e63] outline-none focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10"
                />
              </div>

              {/* Sort order */}
              <div>
                <label className="text-xs font-semibold text-black/50">{zh ? '排序权重' : 'Sort Order'}</label>
                <input
                  type="number"
                  value={formData.sort_order}
                  onChange={e => setFormData(p => ({ ...p, sort_order: parseInt(e.target.value) || 0 }))}
                  className="mt-1 w-24 rounded-xl border border-black/10 bg-white px-3 py-2.5 text-sm text-[#164e63] outline-none focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10"
                />
              </div>

              {/* Error */}
              {formError && (
                <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
                  <AlertCircle size={14} />
                  {formError}
                </div>
              )}
            </div>

            {/* Actions */}
            <div className="mt-6 flex justify-end gap-2">
              <button
                onClick={() => setShowModal(false)}
                className="h-10 rounded-xl border border-black/10 bg-white px-5 text-sm font-medium text-black/60 transition-all hover:bg-black/[0.02]"
              >
                {zh ? '取消' : 'Cancel'}
              </button>
              <ActionButton
                icon={saving ? RefreshCw : Check}
                iconClassName={saving ? 'animate-spin' : undefined}
                variant="primary"
                onClick={() => void handleSave()}
                disabled={saving}
              >
                {editingTag ? (zh ? '保存' : 'Save') : (zh ? '创建' : 'Create')}
              </ActionButton>
            </div>
          </div>
        </div>
      )}

      {/* ── Delete Confirm Modal ── */}
      {deleteTarget && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={() => setDeleteTarget(null)}>
          <div className="w-full max-w-sm rounded-3xl border border-black/8 bg-white p-6 shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="flex flex-col items-center gap-3 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-red-50">
                <Trash2 size={20} className="text-red-500" />
              </div>
              <h3 className="text-lg font-semibold text-[#164e63]">
                {zh ? '删除标签' : 'Delete Tag'}
              </h3>
              <p className="text-sm text-black/50">
                {zh
                  ? `确认删除标签「${deleteTarget.label_zh || deleteTarget.label}」？此操作不可撤销。`
                  : `Confirm deleting tag "${deleteTarget.label}"? This cannot be undone.`}
              </p>
              {deleteTarget.built_in === 1 && (
                <div className="flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
                  <AlertCircle size={14} />
                  {zh ? '内置标签不允许删除' : 'Built-in tags cannot be deleted'}
                </div>
              )}
            </div>
            <div className="mt-5 flex justify-center gap-2">
              <button
                onClick={() => setDeleteTarget(null)}
                className="h-10 rounded-xl border border-black/10 bg-white px-6 text-sm font-medium text-black/60 transition-all hover:bg-black/[0.02]"
              >
                {zh ? '取消' : 'Cancel'}
              </button>
              <ActionButton
                icon={deleting ? RefreshCw : Trash2}
                iconClassName={deleting ? 'animate-spin' : undefined}
                variant="danger"
                size="md"
                onClick={() => void handleDelete()}
                disabled={deleting || deleteTarget.built_in === 1}
              >
                {zh ? '删除' : 'Delete'}
              </ActionButton>
            </div>
          </div>
        </div>
      )}
      </div>
    </div>
  );
}

/* ────────────────────────────────────────── */
/* Compact table row */
interface TagTableRowProps {
  tag: TagDefinition;
  zh: boolean;
  canManage: boolean;
  onEdit: () => void;
  onDelete: () => void;
}

function TagTableRow({ tag, zh, canManage, onEdit, onDelete }: TagTableRowProps) {
  const displayLabel = zh ? (tag.label_zh || tag.label) : tag.label;
  const chipColor = tag.color || '#64748b';
  const categoryLabel = TAG_CATEGORY_LABELS[tag.category];
  const assignmentCount = tag.assignment_count || 0;

  return (
    <tr className="group text-xs text-[#164e63] transition-colors hover:bg-cyan-50/30">
      <td className="px-4 py-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <span className="mt-1 h-2.5 w-2.5 flex-none rounded-full" style={{ backgroundColor: chipColor }} />
          <div className="min-w-0">
            <p className="truncate font-semibold" title={displayLabel}>{displayLabel}</p>
            <p className="mt-0.5 max-w-[300px] truncate text-[11px] text-black/35" title={tag.description || ''}>
              {tag.description || (zh ? '暂无描述' : 'No description')}
            </p>
          </div>
        </div>
      </td>
      <td className="px-4 py-3 font-mono text-[11px] text-black/55">{tag.code}</td>
      <td className="px-4 py-3">{zh ? categoryLabel?.zh : categoryLabel?.en}</td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap gap-1">
          <span className="rounded-md bg-slate-100 px-2 py-1 text-[10px] font-semibold text-slate-600">
            {tag.is_system === 1 ? (zh ? '系统' : 'System') : tag.built_in === 1 ? (zh ? '内置' : 'Built-in') : (zh ? '自定义' : 'Custom')}
          </span>
        </div>
      </td>
      <td className="px-4 py-3 text-right">
        <span className={`font-mono font-bold ${assignmentCount > 0 ? 'text-violet-600' : 'text-black/30'}`}>{assignmentCount}</span>
      </td>
      <td className="px-4 py-3">
        <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[10px] font-bold ${
          tag.is_active === 0 ? 'bg-slate-100 text-slate-500' : 'bg-emerald-50 text-emerald-700'
        }`}>
          <span className={`h-1.5 w-1.5 rounded-full ${tag.is_active === 0 ? 'bg-slate-400' : 'bg-emerald-500'}`} />
          {tag.is_active === 0 ? (zh ? '已停用' : 'Inactive') : (zh ? '已启用' : 'Active')}
        </span>
      </td>
      <td className="px-4 py-3">
        <ActionIconGroup label={zh ? '标签操作' : 'Tag actions'}>
          {canManage && tag.is_system !== 1 && (
            <ActionIconButton
              icon={Pencil}
              label={zh ? '编辑' : 'Edit'}
              variant="accent"
              onClick={onEdit}
            />
          )}
          {canManage && tag.built_in !== 1 && (
            <ActionIconButton
              icon={Trash2}
              label={zh ? '删除' : 'Delete'}
              variant="danger"
              onClick={onDelete}
            />
          )}
          {!canManage && <span className="text-black/25">—</span>}
        </ActionIconGroup>
      </td>
    </tr>
  );
}
