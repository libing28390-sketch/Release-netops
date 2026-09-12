import React from 'react';
import { Check, ChevronDown, Search, X } from 'lucide-react';
import type { TagDefinition, TagCategory } from '../../../types';
import { TAG_CATEGORY_LABELS } from '../../../types';

type Props = {
  tags: TagDefinition[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  onSave?: () => void;
  language: string;
  assetType?: string;
};

const CATEGORY_ORDER: TagCategory[] = [
  'technology', 'business', 'environment', 'network_zone', 'operations', 'security', 'project', 'lifecycle', 'system_auto',
];

export const AssetTagPicker: React.FC<Props> = ({ tags, selectedIds, onChange, onSave, language, assetType }) => {
  const zh = language === 'zh';
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState('');
  const available = React.useMemo(
    () => tags.filter(tag => tag.is_active !== 0 && !tag.is_system && (!assetType || !tag.resource_types || String(tag.resource_types).includes('device'))),
    [tags, assetType],
  );
  const selected = available.filter(tag => selectedIds.includes(tag.id));
  const normalizedSearch = search.trim().toLowerCase();
  const toggle = (id: string) => {
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter(item => item !== id));
      return;
    }
    const nextTag = available.find(tag => tag.id === id);
    const exclusiveGroup = nextTag?.exclusive_group || '';
    const nextIds = exclusiveGroup
      ? selectedIds.filter(selectedId => available.find(tag => tag.id === selectedId)?.exclusive_group !== exclusiveGroup)
      : selectedIds;
    onChange([...nextIds, id]);
  };
  const remove = (id: string) => onChange(selectedIds.filter(item => item !== id));
  const clear = () => onChange([]);

  return (
    <div className="col-span-2 rounded-xl border border-indigo-100 bg-indigo-50/40 p-3">
      <div className="mb-1 flex items-center justify-between">
        <div>
          <label className="block text-[10px] font-bold uppercase tracking-wider text-indigo-900/65">{zh ? '标签' : 'Tags'}</label>
          <p className="mt-0.5 text-[9px] text-indigo-900/45">
            {zh ? '厂商/平台标签已内置；上方厂商和平台字段变更时会自动推荐，标签用于筛选和自动化。' : 'Built-in vendor/platform tags are recommended from the fields above; tags drive filtering and automation.'}
          </p>
        </div>
        <span className="rounded-full bg-white px-2 py-0.5 text-[9px] font-semibold text-indigo-600">{selected.length}</span>
      </div>
      <div className="mb-2 flex flex-wrap gap-1.5">
        {selected.map(tag => (
          <span key={tag.id} className="inline-flex items-center gap-1 rounded-full bg-white px-2 py-1 text-[9px] font-medium text-black/65 shadow-sm">
            <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: tag.color || '#6366f1' }} />
            {zh ? (tag.label_zh || tag.label) : tag.label}
            <button type="button" onClick={() => remove(tag.id)} className="text-black/25 hover:text-black/60" title={zh ? '移除标签' : 'Remove tag'}><X size={10} /></button>
          </span>
        ))}
        {!selected.length && <span className="py-1 text-[9px] italic text-black/30">{zh ? '未选择标签' : 'No tags selected'}</span>}
      </div>
      <button type="button" onClick={() => setOpen(value => !value)} className="flex w-full items-center justify-between rounded-lg border border-indigo-100 bg-white px-2.5 py-1.5 text-[10px] text-black/55 hover:border-indigo-300">
        <span>{zh ? '选择内置或自定义标签' : 'Choose built-in or custom tags'}</span>
        <ChevronDown size={13} className={open ? 'rotate-180' : ''} />
      </button>
      {open && (
        <div className="mt-1 flex max-h-64 flex-col overflow-hidden rounded-lg border border-black/8 bg-white shadow-lg">
          <div className="relative shrink-0 border-b border-black/5 p-1.5">
            <Search size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-black/25" />
            <input value={search} onChange={event => setSearch(event.target.value)} placeholder={zh ? '搜索标签名称或代码' : 'Search label or code'} className="w-full rounded-md bg-black/[0.03] py-1.5 pl-7 pr-2 text-[10px] outline-none" />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
            {CATEGORY_ORDER.map(category => {
              const items = available.filter(tag => tag.category === category && (!normalizedSearch || `${tag.label} ${tag.label_zh} ${tag.code}`.toLowerCase().includes(normalizedSearch)));
              if (!items.length) return null;
              return <div key={category} className="mb-1.5">
                <div className="px-2 py-1 text-[9px] font-bold uppercase tracking-wider text-black/30">{zh ? TAG_CATEGORY_LABELS[category].zh : TAG_CATEGORY_LABELS[category].en}</div>
                {items.map(tag => {
                  const active = selectedIds.includes(tag.id);
                  return <button key={tag.id} type="button" onClick={() => toggle(tag.id)} className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[10px] ${active ? 'bg-indigo-50 text-indigo-700' : 'text-black/60 hover:bg-black/[0.03]'}`}>
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: tag.color || '#6366f1' }} />
                    <span className="min-w-0 flex-1 truncate">{zh ? (tag.label_zh || tag.label) : tag.label}</span>
                    <span className="font-mono text-[8px] text-black/25">{tag.code}</span>
                    {active && <Check size={11} className="text-indigo-500" />}
                  </button>;
                })}
              </div>;
            })}
          </div>
          <div className="flex shrink-0 items-center justify-between gap-2 border-t border-black/5 bg-slate-50/70 p-1.5">
            <button type="button" onClick={clear} disabled={!selectedIds.length} className="rounded-md px-2 py-1 text-[10px] text-rose-500 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-30">{zh ? '一键清除' : 'Clear all'}</button>
            <div className="flex gap-1.5">
              <button type="button" onClick={() => { setOpen(false); setSearch(''); }} className="rounded-md border border-black/8 bg-white px-2.5 py-1 text-[10px] text-black/55 hover:border-indigo-300">{zh ? '应用选择' : 'Apply selection'}</button>
              {onSave && <button type="button" onClick={() => { setOpen(false); onSave(); }} className="rounded-md bg-[#00bceb] px-2.5 py-1 text-[10px] font-semibold text-white hover:bg-[#00a5d0]">{zh ? '保存资产' : 'Save asset'}</button>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
