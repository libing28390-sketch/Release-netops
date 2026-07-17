import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Tags, Plus, Search, X, Edit3, Trash2, RefreshCw, ChevronDown, ChevronRight, Hash,
  Server, Shield, Cpu, Globe, Layers, Settings2, BarChart3, Check, AlertCircle
} from 'lucide-react';
import type { TagDefinition, TagCategory } from '../types';
import { TAG_CATEGORY_LABELS } from '../types';
import PageHero from '../components/PageHero';

/* ─── Props ─── */
interface TagManagementTabProps {
  language: string;
  t: (key: string) => string;
  currentUser?: { role?: string };
}

/* ─── Category icon/color mapping ─── */
const CATEGORY_META: Record<string, { icon: typeof Tags; color: string; bg: string }> = {
  device_type: { icon: Server,   color: 'text-violet-600',  bg: 'bg-violet-50 border-violet-200' },
  vendor:      { icon: Layers,   color: 'text-blue-600',    bg: 'bg-blue-50 border-blue-200' },
  os:          { icon: Cpu,      color: 'text-emerald-600', bg: 'bg-emerald-50 border-emerald-200' },
  role:        { icon: Shield,   color: 'text-amber-600',   bg: 'bg-amber-50 border-amber-200' },
  env:         { icon: Globe,    color: 'text-cyan-600',    bg: 'bg-cyan-50 border-cyan-200' },
  function:    { icon: Settings2, color: 'text-rose-600',   bg: 'bg-rose-50 border-rose-200' },
  status:      { icon: BarChart3, color: 'text-emerald-600', bg: 'bg-emerald-50 border-emerald-200' },
  custom:      { icon: Hash,     color: 'text-slate-600',   bg: 'bg-slate-50 border-slate-200' },
};

const CATEGORIES: TagCategory[] = ['device_type', 'vendor', 'os', 'role', 'env', 'function', 'status'];

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
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set(CATEGORIES));
  const [stats, setStats] = useState<{ total_definitions: number; total_assignments: number; tagged_devices: number; categories: Record<string, number> } | null>(null);

  // Modal state
  const [showModal, setShowModal] = useState(false);
  const [editingTag, setEditingTag] = useState<TagDefinition | null>(null);
  const [formData, setFormData] = useState({
    category: 'custom' as TagCategory,
    value: '',
    label: '',
    label_zh: '',
    color: '',
    icon: '',
    description: '',
    sort_order: 0,
  });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');

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
    if (!search.trim()) return tags;
    const q = search.toLowerCase();
    return tags.filter(
      t => t.value.toLowerCase().includes(q) ||
           t.label.toLowerCase().includes(q) ||
           (t.label_zh && t.label_zh.toLowerCase().includes(q)) ||
           (t.description && t.description.toLowerCase().includes(q))
    );
  }, [tags, search]);

  const grouped = useMemo(() => {
    const m: Record<string, TagDefinition[]> = {};
    for (const cat of CATEGORIES) m[cat] = [];
    for (const tag of filtered) {
      const cat = tag.category || 'custom';
      if (!m[cat]) m[cat] = [];
      m[cat].push(tag);
    }
    // sort each group by sort_order, then value
    for (const arr of Object.values(m)) {
      arr.sort((a, b) => (a.sort_order - b.sort_order) || a.value.localeCompare(b.value));
    }
    return m;
  }, [filtered]);

  /* ── Toggle category expand ── */
  const toggleCategory = (cat: string) => {
    setExpandedCategories(prev => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  /* ── Modal: open for create / edit ── */
  const openCreateModal = () => {
    setEditingTag(null);
    setFormData({ category: 'custom', value: '', label: '', label_zh: '', color: '', icon: '', description: '', sort_order: 0 });
    setFormError('');
    setShowModal(true);
  };

  const openEditModal = (tag: TagDefinition) => {
    setEditingTag(tag);
    setFormData({
      category: tag.category,
      value: tag.value,
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
    if (!formData.value.trim() || !formData.label.trim()) {
      setFormError(zh ? '标签值和英文标签不能为空' : 'Value and label are required');
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

      <div className="flex-1 overflow-auto px-6 py-5 space-y-5">
      {/* ── Header card with stats ── */}
      <div className="rounded-[28px] border border-black/5 bg-white shadow-[0_16px_36px_rgba(11,35,64,0.06)]">
        {/* ── Stats strip ── */}
        {stats && (
          <div className="grid grid-cols-2 gap-px bg-black/[0.02] sm:grid-cols-4 rounded-t-[28px] overflow-hidden">
            {[
              { label: zh ? '标签定义' : 'Definitions', value: stats.total_definitions, color: 'text-[#06b6d4]' },
              { label: zh ? '标签分配' : 'Assignments', value: stats.total_assignments, color: 'text-violet-600' },
              { label: zh ? '已标记设备' : 'Tagged Devices', value: stats.tagged_devices, color: 'text-emerald-600' },
              { label: zh ? '标签分类' : 'Categories', value: Object.keys(stats.categories).length, color: 'text-amber-600' },
            ].map((s, i) => (
              <div key={i} className="flex items-center gap-3 bg-white px-5 py-3.5">
                <BarChart3 size={16} className={s.color} />
                <div>
                  <p className="text-xs text-black/40">{s.label}</p>
                  <p className={`text-lg font-bold ${s.color}`}>{s.value}</p>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── Search + filter row ── */}
        <div className="flex flex-col gap-3 px-5 py-4 border-t border-black/5 sm:flex-row sm:items-center">
          <label className="relative min-w-[240px] flex-1">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-black/30" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder={zh ? '搜索标签名称、值或描述...' : 'Search tag name, value or description...'}
              className="w-full rounded-xl border border-black/10 bg-white py-3 pl-9 pr-9 text-sm text-[#164e63] outline-none placeholder:text-black/30 focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10 transition-all"
            />
            {search && (
              <button onClick={() => setSearch('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-black/30 hover:text-black/60">
                <X size={14} />
              </button>
            )}
          </label>

          {/* Category filter chips */}
          <div className="flex flex-wrap gap-1.5">
            <button
              onClick={() => setCategoryFilter('')}
              className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-xs font-semibold transition-all ${
                categoryFilter === '' ? 'border-[#06b6d4] bg-[#ecfeff] text-[#0e7490]' : 'border-black/10 bg-white text-black/50 hover:border-black/20'
              }`}
            >
              {zh ? '全部' : 'All'}
            </button>
            {CATEGORIES.filter(c => c !== 'custom').map(cat => {
              const meta = CATEGORY_META[cat];
              const catLabel = TAG_CATEGORY_LABELS[cat];
              return (
                <button
                  key={cat}
                  onClick={() => setCategoryFilter(categoryFilter === cat ? '' : cat)}
                  className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-xs font-semibold transition-all ${
                    categoryFilter === cat ? 'border-[#06b6d4] bg-[#ecfeff] text-[#0e7490]' : 'border-black/10 bg-white text-black/50 hover:border-black/20'
                  }`}
                >
                  {meta && <meta.icon size={12} />}
                  {zh ? catLabel?.zh : catLabel?.en}
                </button>
              );
            })}
          </div>

          <span className="ml-auto whitespace-nowrap rounded-xl bg-[#f0f9ff] px-3 py-2.5 text-sm font-medium text-[#164e63]">
            {zh ? `${filtered.length} 个标签` : `${filtered.length} tags`}
          </span>
        </div>
      </div>

      {/* ── Category groups ── */}
      <div className="space-y-3">
        {CATEGORIES.map(cat => {
          const items = grouped[cat] || [];
          if (categoryFilter && categoryFilter !== cat) return null;
          if (items.length === 0 && categoryFilter !== cat) return null;
          const meta = CATEGORY_META[cat] || CATEGORY_META.custom;
          const catLabel = TAG_CATEGORY_LABELS[cat];
          const isExpanded = expandedCategories.has(cat);
          const CatIcon = meta.icon;

          return (
            <div key={cat} className="rounded-2xl border border-black/5 bg-white shadow-sm overflow-hidden">
              {/* category header */}
              <button
                onClick={() => toggleCategory(cat)}
                className="flex w-full items-center gap-3 px-5 py-3.5 text-left transition-colors hover:bg-black/[0.015]"
              >
                <span className={`flex h-8 w-8 items-center justify-center rounded-lg border ${meta.bg}`}>
                  <CatIcon size={16} className={meta.color} />
                </span>
                <div className="flex-1">
                  <p className="text-sm font-semibold text-[#164e63]">
                    {zh ? catLabel?.zh : catLabel?.en}
                  </p>
                  <p className="text-[11px] text-black/40">{items.length} {zh ? '个标签' : 'tags'}</p>
                </div>
                {isExpanded ? <ChevronDown size={16} className="text-black/30" /> : <ChevronRight size={16} className="text-black/30" />}
              </button>

              {/* tag list */}
              {isExpanded && (
                <div className="border-t border-black/5 px-5 py-3">
                  {items.length === 0 ? (
                    <p className="py-4 text-center text-xs text-black/30">
                      {zh ? '暂无标签' : 'No tags in this category'}
                    </p>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {items.map(tag => (
                        <div key={tag.id} className="contents">
                          <TagChip
                            tag={tag}
                            zh={zh}
                            onEdit={canManageTags && tag.category !== 'status' ? () => openEditModal(tag) : undefined}
                            onDelete={canManageTags ? () => setDeleteTarget(tag) : undefined}
                          />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {loading && (
        <div className="flex items-center justify-center py-12">
          <RefreshCw size={20} className="animate-spin text-[#06b6d4]" />
        </div>
      )}

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

              {/* Value */}
              <div>
                <label className="text-xs font-semibold text-black/50">{zh ? '标签值 (唯一标识)' : 'Value (unique ID)'}</label>
                <input
                  value={formData.value}
                  onChange={e => setFormData(p => ({ ...p, value: e.target.value.toLowerCase().replace(/[^a-z0-9\-_.]/g, '') }))}
                  disabled={!!editingTag}
                  placeholder="e.g. cisco-ios-xe"
                  className="mt-1 w-full rounded-xl border border-black/10 bg-white px-3 py-2.5 text-sm font-mono text-[#164e63] outline-none focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10 disabled:opacity-50"
                />
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
              <button
                onClick={() => void handleSave()}
                disabled={saving}
                className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#06b6d4] px-5 text-sm font-semibold text-white transition-all hover:bg-[#0891b2] disabled:opacity-50"
              >
                {saving ? <RefreshCw size={14} className="animate-spin" /> : <Check size={14} />}
                {editingTag ? (zh ? '保存' : 'Save') : (zh ? '创建' : 'Create')}
              </button>
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
              <button
                onClick={() => void handleDelete()}
                disabled={deleting || deleteTarget.built_in === 1}
                className="inline-flex h-10 items-center gap-2 rounded-xl bg-red-500 px-6 text-sm font-semibold text-white transition-all hover:bg-red-600 disabled:opacity-40"
              >
                {deleting ? <RefreshCw size={14} className="animate-spin" /> : <Trash2 size={14} />}
                {zh ? '删除' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
      </div>
    </div>
  );
}

/* ────────────────────────────────────────── */
/* Tag chip sub-component */
interface TagChipProps {
  tag: TagDefinition;
  zh: boolean;
  onEdit?: () => void;
  onDelete?: () => void;
}

function TagChip({ tag, zh, onEdit, onDelete }: TagChipProps) {
  const displayLabel = zh ? (tag.label_zh || tag.label) : tag.label;
  const chipColor = tag.color || '#64748b';

  return (
    <div
      className="group relative inline-flex items-center gap-1.5 rounded-xl border bg-white px-3 py-2 text-sm shadow-sm transition-all hover:shadow-md"
      style={{ borderColor: `${chipColor}30` }}
    >
      {/* color dot */}
      <span
        className="h-2.5 w-2.5 flex-shrink-0 rounded-full"
        style={{ backgroundColor: chipColor }}
      />
      <span className="font-medium text-[#164e63]">{displayLabel}</span>
      <span className="ml-0.5 text-[10px] font-mono text-black/30">{tag.value}</span>

      {/* built-in badge */}
      {tag.built_in === 1 && (
        <span className="ml-1 rounded bg-black/[0.04] px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-black/30">
          {zh ? '内置' : 'Built-in'}
        </span>
      )}

      {tag.category === 'status' && (
        <span className="ml-1 rounded bg-emerald-50 px-1.5 py-0.5 text-[9px] font-bold tracking-wider text-emerald-600">
          {zh ? '系统维护' : 'System'}
        </span>
      )}

      {/* hover action buttons */}
      <span className="ml-1 hidden items-center gap-0.5 group-hover:inline-flex">
        {onEdit && <button onClick={onEdit} className="rounded-md p-1 text-black/30 transition-colors hover:bg-[#ecfeff] hover:text-[#0891b2]" title={zh ? '编辑' : 'Edit'}>
          <Edit3 size={12} />
        </button>}
        {tag.built_in !== 1 && (
          onDelete && <button onClick={onDelete} className="rounded-md p-1 text-black/30 transition-colors hover:bg-red-50 hover:text-red-500" title={zh ? '删除' : 'Delete'}>
            <Trash2 size={12} />
          </button>
        )}
      </span>
    </div>
  );
}
