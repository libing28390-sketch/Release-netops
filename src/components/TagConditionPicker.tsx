import React, { useState, useRef, useEffect, useMemo } from 'react';
import { Search, X, Tag, Plus, Ban, Layers } from 'lucide-react';
import type { TagDefinition, TagCategory } from '../types';
import { TAG_CATEGORY_LABELS } from '../types';

/* ═══════════════════════════════════════════════════════ */
/*  Data model — AND-of-ORs + exclude                     */
/*  groups are ANDed; tags within a group are ORed         */
/*  Example: A AND (B OR C) NOT D                          */
/*    → { groups: [{tag_ids:["A"]},{tag_ids:["B","C"]}],   */
/*        exclude_tag_ids: ["D"] }                          */
/* ═══════════════════════════════════════════════════════ */

export interface TagConditionGroup {
  tag_ids: string[];
}

export interface TagFilterConfig {
  groups: TagConditionGroup[];
  exclude_tag_ids: string[];
}

export const EMPTY_TAG_FILTER: TagFilterConfig = { groups: [], exclude_tag_ids: [] };

export const serializeTagFilter = (cfg: TagFilterConfig): string => JSON.stringify(cfg);

export const parseTagFilter = (raw: string): TagFilterConfig => {
  try {
    const o = JSON.parse(raw);
    // New format
    if (Array.isArray(o.groups)) {
      return {
        groups: o.groups.map((g: { tag_ids?: string[] }) => ({
          tag_ids: Array.isArray(g.tag_ids) ? g.tag_ids : [],
        })).filter((g: TagConditionGroup) => g.tag_ids.length > 0),
        exclude_tag_ids: Array.isArray(o.exclude_tag_ids) ? o.exclude_tag_ids : [],
      };
    }
    // Old format backward compat: { tag_ids, exclude_tag_ids, match_mode }
    if (Array.isArray(o.tag_ids)) {
      const mode = o.match_mode === 'or' ? 'or' : 'and';
      const tags: string[] = o.tag_ids;
      return {
        groups: mode === 'and'
          ? tags.map(id => ({ tag_ids: [id] }))           // each tag own group → all ANDed
          : (tags.length > 0 ? [{ tag_ids: tags }] : []), // one group → ORed
        exclude_tag_ids: Array.isArray(o.exclude_tag_ids) ? o.exclude_tag_ids : [],
      };
    }
    return { ...EMPTY_TAG_FILTER };
  } catch {
    return { ...EMPTY_TAG_FILTER };
  }
};

/* ═══════════════════════════════════════════════════════ */
/*  Inline tag dropdown (reusable)                         */
/* ═══════════════════════════════════════════════════════ */

interface TagDropdownProps {
  allTags: TagDefinition[];
  excludeIds: Set<string>;
  onSelect: (tagId: string) => void;
  language: string;
  placeholder?: string;
}

const TagDropdown: React.FC<TagDropdownProps> = ({ allTags, excludeIds, onSelect, language, placeholder }) => {
  const zh = language === 'zh';
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const filtered = useMemo(() => {
    const base = allTags.filter(t => !excludeIds.has(t.id));
    if (!search) return base;
    const q = search.toLowerCase();
    return base.filter(t =>
      t.label.toLowerCase().includes(q) || t.label_zh.toLowerCase().includes(q) || t.value.toLowerCase().includes(q)
    );
  }, [allTags, search, excludeIds]);

  const grouped = useMemo(() => {
    const result: Record<string, TagDefinition[]> = {};
    for (const cat of Object.keys(TAG_CATEGORY_LABELS) as TagCategory[]) {
      const items = filtered.filter(t => t.category === cat);
      if (items.length > 0) result[cat] = items;
    }
    return result;
  }, [filtered]);

  return (
    <div ref={ref} className="relative">
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/20" size={12} />
        <input
          ref={inputRef}
          type="text"
          value={search}
          onChange={e => { setSearch(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          placeholder={placeholder || (zh ? '搜索标签…' : 'Search tags…')}
          className="w-full pl-7 pr-2 py-1.5 rounded-lg border border-black/[0.06] text-[11px] bg-white focus:outline-none focus:ring-1 focus:ring-cyan-500/20 focus:border-cyan-400/50 transition-all placeholder:text-black/20"
        />
      </div>
      {open && (
        <div className="absolute z-30 mt-1 w-full min-w-[220px] rounded-lg border border-black/8 bg-white shadow-xl overflow-hidden max-h-48 overflow-y-auto">
          {Object.keys(grouped).length === 0 ? (
            <div className="px-3 py-3 text-center text-[10px] text-black/25">
              {search ? (zh ? '无匹配标签' : 'No match') : (zh ? '无可选标签' : 'No tags available')}
            </div>
          ) : (
            (Object.entries(grouped) as [string, TagDefinition[]][]).map(([cat, tags]) => (
              <div key={cat}>
                <div className="px-2.5 py-0.5 text-[8px] font-bold uppercase tracking-widest text-black/25 bg-black/[0.015] sticky top-0">
                  {zh ? TAG_CATEGORY_LABELS[cat as TagCategory].zh : TAG_CATEGORY_LABELS[cat as TagCategory].en}
                </div>
                {tags.map(tag => (
                  <button
                    key={tag.id}
                    type="button"
                    onClick={() => { onSelect(tag.id); setSearch(''); setOpen(false); inputRef.current?.focus(); }}
                    className="flex items-center gap-2 w-full px-2.5 py-1.5 text-left hover:bg-cyan-50/60 transition-colors"
                  >
                    <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: tag.color || '#94a3b8' }} />
                    <span className="text-[11px] text-black/70 truncate">{zh ? (tag.label_zh || tag.label) : tag.label}</span>
                    {tag.label_zh && tag.label && (
                      <span className="text-[9px] text-black/15 truncate">{zh ? tag.label : tag.label_zh}</span>
                    )}
                  </button>
                ))}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
};

/* ═══════════════════════════════════════════════════════ */
/*  Main component                                         */
/* ═══════════════════════════════════════════════════════ */

interface TagConditionPickerProps {
  value: TagFilterConfig;
  onChange: (v: TagFilterConfig) => void;
  language: string;
}

const TagConditionPicker: React.FC<TagConditionPickerProps> = ({ value, onChange, language }) => {
  const zh = language === 'zh';
  const [allTags, setAllTags] = useState<TagDefinition[]>([]);
  const [showExclude, setShowExclude] = useState(value.exclude_tag_ids.length > 0);

  useEffect(() => {
    const token = localStorage.getItem('netops_token');
    const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};
    fetch('/api/tags/definitions', { headers })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(j => setAllTags(Array.isArray(j) ? j : (j.data ?? [])))
      .catch(() => {});
  }, []);

  const tagMap = useMemo(() => new Map(allTags.map(t => [t.id, t])), [allTags]);

  const allUsedIds = useMemo(() => {
    const s = new Set<string>();
    for (const g of value.groups) for (const id of g.tag_ids) s.add(id);
    for (const id of value.exclude_tag_ids) s.add(id);
    return s;
  }, [value]);

  const totalSelected = useMemo(() => {
    let n = value.exclude_tag_ids.length;
    for (const g of value.groups) n += g.tag_ids.length;
    return n;
  }, [value]);

  /* ─── Mutations ─── */
  const addGroup = () => onChange({ ...value, groups: [...value.groups, { tag_ids: [] }] });
  const removeGroup = (gi: number) => onChange({ ...value, groups: value.groups.filter((_, i) => i !== gi) });

  const addTagToGroup = (gi: number, tagId: string) => {
    const groups = value.groups.map((g, i) => i === gi ? { ...g, tag_ids: [...g.tag_ids, tagId] } : g);
    onChange({ ...value, groups });
  };
  const removeTagFromGroup = (gi: number, tagId: string) => {
    const groups = value.groups.map((g, i) => i === gi ? { ...g, tag_ids: g.tag_ids.filter(id => id !== tagId) } : g).filter(g => g.tag_ids.length > 0);
    onChange({ ...value, groups });
  };

  const addExclude = (tagId: string) => onChange({ ...value, exclude_tag_ids: [...value.exclude_tag_ids, tagId] });
  const removeExclude = (tagId: string) => {
    const next = value.exclude_tag_ids.filter(id => id !== tagId);
    if (next.length === 0) setShowExclude(false);
    onChange({ ...value, exclude_tag_ids: next });
  };

  /* ─── Chip renderer ─── */
  const renderChip = (tagId: string, onRemove: () => void, variant: 'include' | 'exclude' = 'include') => {
    const tag = tagMap.get(tagId);
    if (!tag) return null;
    const isExclude = variant === 'exclude';
    return (
      <span
        key={tagId}
        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[11px] font-medium ${
          isExclude ? 'bg-red-50 border border-red-200/60 text-red-700' : 'bg-cyan-50 border border-cyan-200/60 text-cyan-800'
        }`}
      >
        {isExclude ? (
          <Ban size={10} className="shrink-0 text-red-400" />
        ) : (
          <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: tag.color || '#06b6d4' }} />
        )}
        {zh ? (tag.label_zh || tag.label) : tag.label}
        <button type="button" onClick={onRemove} className={`ml-0.5 transition-colors ${isExclude ? 'text-red-300 hover:text-red-500' : 'text-cyan-400 hover:text-red-400'}`}>
          <X size={10} />
        </button>
      </span>
    );
  };

  /* ─── Expression preview ─── */
  const expressionPreview = useMemo(() => {
    if (totalSelected === 0) return '';
    const parts: string[] = [];
    for (const g of value.groups) {
      if (g.tag_ids.length === 0) continue;
      const labels = g.tag_ids.map(id => { const t = tagMap.get(id); return t ? (zh ? (t.label_zh || t.label) : t.label) : id; });
      parts.push(labels.length === 1 ? labels[0] : `(${labels.join(zh ? ' 或 ' : ' OR ')})`);
    }
    let expr = parts.join(zh ? ' 且 ' : ' AND ');
    if (value.exclude_tag_ids.length > 0) {
      const exLabels = value.exclude_tag_ids.map(id => { const t = tagMap.get(id); return t ? (zh ? (t.label_zh || t.label) : t.label) : id; });
      expr += (expr ? (zh ? ' 且 ' : ' AND ') : '') + `NOT(${exLabels.join(', ')})`;
    }
    return expr;
  }, [value, tagMap, zh, totalSelected]);

  return (
    <div className="space-y-2.5">
      {/* Expression preview */}
      {expressionPreview && (
        <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-[#f0fdfa] border border-cyan-200/40">
          <Layers size={12} className="text-cyan-500 mt-0.5 shrink-0" />
          <p className="text-[11px] text-[#164e63] font-medium leading-relaxed break-all">{expressionPreview}</p>
        </div>
      )}

      {/* Condition groups */}
      {value.groups.map((group, gi) => (
        <div key={gi}>
          {gi > 0 && (
            <div className="flex items-center gap-2 py-1">
              <div className="flex-1 border-t border-dashed border-cyan-300/40" />
              <span className="text-[9px] font-bold uppercase tracking-widest text-cyan-500/70 select-none">{zh ? '且 AND' : 'AND'}</span>
              <div className="flex-1 border-t border-dashed border-cyan-300/40" />
            </div>
          )}
          <div className="rounded-xl border border-black/[0.06] bg-[#fafcfd] p-2.5 space-y-2 group/card">
            <div className="flex items-center justify-between">
              <span className="text-[9px] font-bold uppercase tracking-widest text-black/30">
                {zh ? `条件组 ${gi + 1}` : `Group ${gi + 1}`}
                {group.tag_ids.length > 1 && (
                  <span className="ml-1.5 text-amber-500 normal-case tracking-normal">
                    ({zh ? '组内标签为「或」关系' : 'tags ORed within group'})
                  </span>
                )}
              </span>
              <button type="button" onClick={() => removeGroup(gi)} className="opacity-0 group-hover/card:opacity-100 p-0.5 rounded text-black/20 hover:text-red-500 hover:bg-red-50 transition-all" title={zh ? '删除条件组' : 'Remove group'}>
                <X size={12} />
              </button>
            </div>
            {group.tag_ids.length > 0 && (
              <div className="flex flex-wrap gap-1.5 items-center">
                {group.tag_ids.map((tagId, ti) => (
                  <React.Fragment key={tagId}>
                    {ti > 0 && <span className="text-[9px] font-bold text-amber-500/70 select-none">{zh ? '或' : 'OR'}</span>}
                    {renderChip(tagId, () => removeTagFromGroup(gi, tagId))}
                  </React.Fragment>
                ))}
              </div>
            )}
            <TagDropdown
              allTags={allTags}
              excludeIds={allUsedIds}
              onSelect={tagId => addTagToGroup(gi, tagId)}
              language={language}
              placeholder={zh ? '搜索并添加标签到此组…' : 'Search & add tag to this group…'}
            />
          </div>
        </div>
      ))}

      {/* Exclude section */}
      {showExclude && (
        <div>
          {value.groups.length > 0 && (
            <div className="flex items-center gap-2 py-1">
              <div className="flex-1 border-t border-dashed border-red-300/40" />
              <span className="text-[9px] font-bold uppercase tracking-widest text-red-400/70 select-none">{zh ? '排除 NOT' : 'NOT'}</span>
              <div className="flex-1 border-t border-dashed border-red-300/40" />
            </div>
          )}
          <div className="rounded-xl border border-red-100 bg-red-50/30 p-2.5 space-y-2">
            {value.exclude_tag_ids.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {value.exclude_tag_ids.map(id => renderChip(id, () => removeExclude(id), 'exclude'))}
              </div>
            )}
            <TagDropdown
              allTags={allTags}
              excludeIds={allUsedIds}
              onSelect={addExclude}
              language={language}
              placeholder={zh ? '搜索要排除的标签…' : 'Search tag to exclude…'}
            />
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2 flex-wrap">
        <button type="button" onClick={addGroup} className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-dashed border-cyan-300/50 text-[10px] font-semibold text-cyan-600 hover:bg-cyan-50 hover:border-cyan-400/60 transition-all">
          <Plus size={11} />
          {zh ? '添加条件组' : 'Add Group'}
        </button>
        {!showExclude && (
          <button type="button" onClick={() => setShowExclude(true)} className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-dashed border-red-200/50 text-[10px] font-semibold text-red-400 hover:bg-red-50 hover:border-red-300/60 transition-all">
            <Ban size={11} />
            {zh ? '排除标签' : 'Exclude Tags'}
          </button>
        )}
      </div>

      {/* Hint */}
      {totalSelected === 0 && (
        <p className="text-[10px] text-black/25 flex items-center gap-1">
          <Tag size={9} />
          {zh ? '点击「添加条件组」构建条件，组间 AND，组内 OR。例如 A 且 (B 或 C)' : 'Click "Add Group" to build. Groups ANDed, tags within ORed. e.g. A AND (B OR C)'}
        </p>
      )}
    </div>
  );
};

export default TagConditionPicker;
