import React, { useState, useRef, useEffect } from 'react';
import { ChevronDown, Search, Tag, X } from 'lucide-react';
import type { TagDefinition, TagCategory } from '../types';
import { TAG_CATEGORY_LABELS } from '../types';

interface TagFilterDropdownProps {
  allTags: TagDefinition[];
  selectedTagIds: string[];
  onChange: (tagIds: string[]) => void;
  language: string;
  /** compact style for toolbar inline use */
  compact?: boolean;
  /** Hide system-managed availability tags when this picker is used for assignment. */
  excludeStatusTags?: boolean;
}

const TagFilterDropdown: React.FC<TagFilterDropdownProps> = ({
  allTags, selectedTagIds, onChange, language, compact = true, excludeStatusTags = false,
}) => {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const ref = useRef<HTMLDivElement>(null);
  const isZh = language === 'zh';

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const toggle = (tagId: string) => {
    onChange(
      selectedTagIds.includes(tagId)
        ? selectedTagIds.filter(id => id !== tagId)
        : [...selectedTagIds, tagId]
    );
  };

  const filtered = allTags.filter(t => {
    if (t.is_active === 0) return false;
    if (excludeStatusTags && t.is_system) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return String(t.label || '').toLowerCase().includes(q)
      || String(t.label_zh || '').toLowerCase().includes(q)
      || t.code.toLowerCase().includes(q);
  });

  const grouped = (Object.keys(TAG_CATEGORY_LABELS) as TagCategory[]).reduce<Record<string, TagDefinition[]>>((acc, cat) => {
    const items = filtered.filter(t => t.category === cat);
    if (items.length > 0) acc[cat] = items;
    return acc;
  }, {});

  const count = selectedTagIds.length;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        title={isZh ? '按标签筛选' : 'Filter by tags'}
        className={`inline-flex items-center gap-1 ${compact
          ? 'px-2.5 py-1.5 text-[11px] border border-black/6 dark:border-white/8 rounded-lg bg-transparent outline-none focus:border-[#00bceb]/40'
          : 'px-2.5 py-1.5 border border-gray-100 rounded-lg text-xs bg-gray-50 outline-none focus:border-cyan-300'
        } ${count > 0
          ? 'text-[#0096bd] dark:text-[#5dd8f0] border-[#00bceb]/30 dark:border-[#00bceb]/25'
          : 'text-black/55 dark:text-white/55'
        }`}
      >
        <Tag size={11} />
        {isZh ? '标签' : 'Tags'}
        {count > 0 && (
          <span className="ml-0.5 px-1.5 py-0 rounded-full bg-[#00bceb]/15 text-[10px] font-semibold tabular-nums">
            {count}
          </span>
        )}
        <ChevronDown size={10} className={`ml-0.5 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1 z-50 w-72 rounded-xl border border-black/8 dark:border-white/12
          bg-white dark:bg-[#111b2d] shadow-xl shadow-black/10 dark:shadow-black/40 overflow-hidden">
          {/* Search */}
          <div className="p-2 border-b border-black/5 dark:border-white/8">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 text-black/25 dark:text-white/20" size={12} />
              <input
                type="text"
                placeholder={isZh ? '搜索标签…' : 'Search tags…'}
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="w-full pl-7 pr-3 py-1.5 text-[11px] bg-black/[.03] dark:bg-white/[.05] border border-black/6 dark:border-white/8
                  rounded-lg outline-none focus:border-[#00bceb]/40 text-black/80 dark:text-white/80
                  placeholder:text-black/25 dark:placeholder:text-white/20"
              />
            </div>
          </div>

          {/* Selected summary */}
          {count > 0 && (
            <div className="px-2.5 py-1.5 border-b border-black/5 dark:border-white/8 flex items-center justify-between">
              <span className="text-[10px] text-black/40 dark:text-white/35">
                {count} {isZh ? '已选' : 'selected'}
              </span>
              <button
                onClick={() => onChange([])}
                className="text-[10px] text-red-500/70 hover:text-red-500 transition-colors"
              >
                {isZh ? '清除' : 'Clear'}
              </button>
            </div>
          )}

          {/* Tag list */}
          <div className="max-h-64 overflow-y-auto py-1">
            {Object.keys(grouped).length === 0 ? (
              <div className="px-3 py-4 text-center text-[11px] text-black/30 dark:text-white/25">
                {isZh ? '无匹配标签' : 'No matching tags'}
              </div>
            ) : (
              Object.entries(grouped).map(([cat, tags]) => (
                <div key={cat}>
                  <div className="px-3 py-1 text-[9px] font-bold uppercase tracking-widest text-black/30 dark:text-white/25">
                    {isZh ? TAG_CATEGORY_LABELS[cat as TagCategory].zh : TAG_CATEGORY_LABELS[cat as TagCategory].en}
                  </div>
                  {tags.map(tag => {
                    const sel = selectedTagIds.includes(tag.id);
                    return (
                      <button
                        key={tag.id}
                        onClick={() => toggle(tag.id)}
                        className={`w-full flex items-center gap-2 px-3 py-1 text-left text-[11px] transition-colors
                          ${sel
                            ? 'bg-[#00bceb]/8 text-[#0096bd] dark:text-[#5dd8f0]'
                            : 'text-black/65 dark:text-white/65 hover:bg-black/[.04] dark:hover:bg-white/[.06]'
                          }`}
                      >
                        <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: tag.color || '#94a3b8' }} />
                        <span className="truncate flex-1">{isZh ? (tag.label_zh || tag.label) : tag.label}</span>
                        {sel && <span className="text-[#00bceb] text-xs">✓</span>}
                      </button>
                    );
                  })}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default TagFilterDropdown;
