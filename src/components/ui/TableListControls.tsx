import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Check, ChevronDown, Filter, Search, Settings, X } from 'lucide-react';

export interface ColumnSettingOption {
  key: string;
  label: string;
  required?: boolean;
  isAction?: boolean;
}

interface ColumnSettingsButtonProps {
  columns: readonly ColumnSettingOption[];
  visibleKeys: readonly string[];
  defaultVisibleKeys: readonly string[];
  onApply: (visibleKeys: string[]) => void;
  language: string;
  label?: string;
}

export const ColumnSettingsButton: React.FC<ColumnSettingsButtonProps> = ({
  columns,
  visibleKeys,
  defaultVisibleKeys,
  onApply,
  language,
  label,
}) => {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [draftKeys, setDraftKeys] = useState<string[]>([]);
  const inputId = React.useId();
  const zh = language === 'zh';
  const normalizedVisible = useMemo(() => normalizeKeys(columns, visibleKeys), [columns, visibleKeys]);
  const normalizedDefaults = useMemo(() => normalizeKeys(columns, defaultVisibleKeys), [columns, defaultVisibleKeys]);
  const draftSet = new Set(draftKeys);
  const selectedColumns = columns.filter((column) => draftSet.has(column.key));
  const filteredColumns = columns.filter((column) => column.label.toLocaleLowerCase(zh ? 'zh-CN' : 'en').includes(search.trim().toLocaleLowerCase(zh ? 'zh-CN' : 'en')));

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', closeOnEscape);
    return () => document.removeEventListener('keydown', closeOnEscape);
  }, [open]);

  const beginEditing = () => {
    setDraftKeys(normalizedVisible);
    setSearch('');
    setOpen(true);
  };

  const toggleColumn = (key: string, visible: boolean) => {
    const definition = columns.find((column) => column.key === key);
    if (!definition || (definition.required && !visible)) return;
    setDraftKeys((current) => {
      const next = new Set(current);
      if (visible) next.add(key);
      else next.delete(key);
      const visibleDataColumns = columns.filter((column) => !column.isAction && next.has(column.key));
      if (!visible && !visibleDataColumns.length) return current;
      return normalizeKeys(columns, [...next]);
    });
  };

  const apply = () => {
    onApply(normalizeKeys(columns, draftKeys));
    setOpen(false);
  };

  return (
    <>
      <button
        type="button"
        aria-label={label || (zh ? '自定义列表字段' : 'Customize columns')}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={label || (zh ? '自定义列表字段' : 'Customize columns')}
        onClick={beginEditing}
        className="nx-table-tool-button"
      >
        <Settings size={15} strokeWidth={1.8} />
      </button>
      {open && (
        <div className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/55 p-4" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
          <section role="dialog" aria-modal="true" aria-labelledby={`${inputId}-title`} className="nx-column-settings-dialog flex max-h-[min(680px,88vh)] w-[min(820px,calc(100vw-32px))] flex-col overflow-hidden rounded-sm bg-white shadow-2xl dark:bg-slate-900">
            <header className="flex items-center justify-between border-b border-slate-200 px-6 py-4 dark:border-slate-700">
              <h2 id={`${inputId}-title`} className="text-sm font-semibold text-slate-900 dark:text-slate-100">{zh ? '自定义列表字段' : 'Customize columns'}</h2>
              <button type="button" onClick={() => setOpen(false)} aria-label={zh ? '关闭' : 'Close'} className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:hover:bg-slate-800 dark:hover:text-white"><X size={17} /></button>
            </header>
            <div className="grid min-h-0 flex-1 grid-cols-1 gap-5 overflow-y-auto p-6 md:grid-cols-[1fr_40px_1fr]">
              <div className="flex min-h-[260px] flex-col">
                <div className="mb-3 text-xs font-semibold text-slate-700 dark:text-slate-200">{zh ? '请选择' : 'Available fields'}</div>
                <label htmlFor={`${inputId}-search`} className="relative block">
                  <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input id={`${inputId}-search`} type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={zh ? '请输入关键词进行搜索' : 'Search fields'} className="nx-column-settings-search w-full border border-slate-200 py-2 pl-9 pr-3 text-xs outline-none focus:border-blue-500 dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
                </label>
                <div className="mt-0 flex-1 overflow-y-auto border-x border-b border-slate-200 dark:border-slate-700">
                  <div className="border-b border-slate-200 px-4 py-2.5 text-xs font-semibold text-slate-600 dark:border-slate-700 dark:text-slate-300">{zh ? '字段' : 'Field'}</div>
                  {filteredColumns.map((column) => {
                    const checked = draftSet.has(column.key);
                    return (
                      <label key={column.key} className={`flex min-h-12 cursor-pointer items-center gap-3 border-b border-slate-100 px-3 text-xs text-slate-700 last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:text-slate-200 dark:hover:bg-slate-800/60 ${checked ? 'bg-slate-50/70 dark:bg-slate-800/30' : ''}`}>
                        <input type="checkbox" checked={checked} disabled={column.required} onChange={(event) => toggleColumn(column.key, event.target.checked)} className="h-4 w-4 accent-blue-600 disabled:opacity-45" />
                        <span>{column.label}</span>
                      </label>
                    );
                  })}
                  {filteredColumns.length === 0 && <div className="px-4 py-8 text-center text-xs text-slate-400">{zh ? '没有匹配字段' : 'No fields found'}</div>}
                </div>
              </div>
              <div className="hidden items-center justify-center text-lg text-slate-500 md:flex" aria-hidden="true">↔</div>
              <div className="flex min-h-[260px] flex-col">
                <div className="mb-3 text-xs font-semibold text-slate-700 dark:text-slate-200">{zh ? `已选择(${selectedColumns.length})` : `Selected (${selectedColumns.length})`}</div>
                <div className="flex-1 overflow-y-auto border border-slate-200 dark:border-slate-700">
                  <div className="border-b border-slate-200 px-3 py-2.5 text-xs font-semibold text-slate-600 dark:border-slate-700 dark:text-slate-300">{zh ? '字段' : 'Field'}</div>
                  {selectedColumns.map((column) => (
                    <div key={column.key} className="flex min-h-12 items-center justify-between gap-3 border-b border-slate-100 px-3 text-xs text-slate-700 last:border-0 dark:border-slate-800 dark:text-slate-200">
                      <span className="truncate">{column.label}</span>
                      <button type="button" disabled={column.required} onClick={() => toggleColumn(column.key, false)} aria-label={zh ? `移除${column.label}` : `Remove ${column.label}`} className="shrink-0 rounded-full p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-40 dark:hover:bg-slate-800 dark:hover:text-white"><X size={14} /></button>
                    </div>
                  ))}
                  {selectedColumns.length === 0 && <div className="px-4 py-8 text-center text-xs text-slate-400">{zh ? '请选择至少一个字段' : 'Select at least one field'}</div>}
                </div>
              </div>
            </div>
            <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-slate-200 px-6 py-4 dark:border-slate-700">
              <button type="button" onClick={() => setDraftKeys(normalizedDefaults)} className="mr-auto rounded-sm px-3 py-2 text-xs text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800">{zh ? '恢复默认列' : 'Restore default columns'}</button>
              <button type="button" onClick={() => setOpen(false)} className="rounded-sm border border-slate-200 px-4 py-2 text-xs text-slate-700 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800">{zh ? '取消' : 'Cancel'}</button>
              <button type="button" disabled={selectedColumns.length === 0} onClick={apply} className="inline-flex items-center gap-1.5 rounded-sm bg-blue-600 px-5 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"><Check size={14} />{zh ? '确定' : 'Apply'}</button>
            </footer>
          </section>
        </div>
      )}
    </>
  );
};

function normalizeKeys(columns: readonly ColumnSettingOption[], keys: readonly string[]): string[] {
  const selected = new Set(keys);
  columns.forEach((column) => { if (column.required) selected.add(column.key); });
  const hasVisibleDataColumn = columns.some((column) => !column.isAction && selected.has(column.key));
  if (!hasVisibleDataColumn && columns.length > 0) {
    const fallback = columns.find((column) => !column.isAction) || columns[0];
    selected.add(fallback.key);
  }
  return columns.filter((column) => selected.has(column.key)).map((column) => column.key);
}

export interface TableHeaderFilterOption {
  value: string;
  label: string;
}

interface TableHeaderMultiSelectFilterProps {
  label: string;
  options: readonly TableHeaderFilterOption[];
  selectedValues: readonly string[];
  onApply: (values: string[]) => void;
  language: string;
}

export const TableHeaderMultiSelectFilter: React.FC<TableHeaderMultiSelectFilterProps> = ({ label, options, selectedValues, onApply, language }) => {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<string[]>([]);
  const rootRef = useRef<HTMLSpanElement>(null);
  const zh = language === 'zh';
  const draftSet = new Set(draft);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: MouseEvent) => { if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false); };
    const closeEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', closeOutside);
    document.addEventListener('keydown', closeEscape);
    return () => {
      document.removeEventListener('mousedown', closeOutside);
      document.removeEventListener('keydown', closeEscape);
    };
  }, [open]);

  const beginEditing = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    setDraft([...selectedValues]);
    setOpen((value) => !value);
  };
  const toggle = (value: string) => setDraft((current) => current.includes(value) ? current.filter((item) => item !== value) : [...current, value]);
  const active = selectedValues.length > 0;

  return (
    <span ref={rootRef} className="relative inline-flex align-middle">
      <button type="button" aria-label={zh ? `筛选${label}` : `Filter ${label}`} aria-expanded={open} onClick={beginEditing} className={`nx-table-header-filter ${active ? 'is-active' : ''}`} title={zh ? `筛选${label}` : `Filter ${label}`}>
        <Filter size={12} />
        {active && <span className="nx-table-filter-count">{selectedValues.length}</span>}
        <ChevronDown size={10} className="opacity-70" />
      </button>
      {open && (
        <div className="nx-table-filter-popover" role="dialog" aria-label={zh ? `${label}筛选` : `${label} filter`}>
          <div className="max-h-60 overflow-y-auto py-1">
            <label className="nx-table-filter-option border-b border-slate-100 font-medium dark:border-slate-700">
              <input type="checkbox" checked={draft.length === options.length && options.length > 0} onChange={(event) => setDraft(event.target.checked ? options.map((option) => option.value) : [])} className="h-4 w-4 accent-blue-600" />
              <span>{zh ? '（全选）' : '(Select all)'}</span>
            </label>
            {options.map((option) => (
              <label key={option.value} className="nx-table-filter-option">
                <input type="checkbox" checked={draftSet.has(option.value)} onChange={() => toggle(option.value)} className="h-4 w-4 accent-blue-600" />
                <span>{option.label}</span>
              </label>
            ))}
            {options.length === 0 && <div className="px-3 py-4 text-center text-xs text-slate-400">{zh ? '暂无可选项' : 'No options'}</div>}
          </div>
          <div className="flex items-center justify-end gap-2 border-t border-slate-200 px-2.5 py-2 dark:border-slate-700">
            <button type="button" onClick={() => { onApply(draft); setOpen(false); }} className="rounded-sm bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700">{zh ? '确定' : 'Apply'}</button>
            <button type="button" onClick={() => { setDraft([]); onApply([]); setOpen(false); }} className="rounded-sm px-2.5 py-1.5 text-xs text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800">{zh ? '重置' : 'Reset'}</button>
          </div>
        </div>
      )}
    </span>
  );
};

interface ListToolbarProps {
  children: React.ReactNode;
  className?: string;
  leadingAction?: React.ReactNode;
}

export const ListToolbar: React.FC<ListToolbarProps> = ({ children, className = '', leadingAction }) => (
  <div className={`nx-list-toolbar ${leadingAction ? 'nx-list-toolbar--split' : ''} ${className}`.trim()}>
    {leadingAction ? (
      <>
        <div className="nx-list-toolbar__leading">{leadingAction}</div>
        <div className="nx-list-toolbar__controls">{children}</div>
      </>
    ) : children}
  </div>
);

interface ListSearchInputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> {
  language: string;
  onSearch?: () => void;
  onClear?: () => void;
}

export const ListSearchInput: React.FC<ListSearchInputProps> = ({ language, onSearch, onClear, className = '', onKeyDown, value, ...props }) => {
  const zh = language === 'zh';
  return (
    <div className={`nx-list-search ${className}`.trim()}>
      <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
      <input {...props} value={value} type="search" onKeyDown={(event) => { onKeyDown?.(event); if (event.key === 'Enter') onSearch?.(); }} className="w-full bg-transparent py-2 pl-9 pr-3 text-xs text-slate-800 outline-none placeholder:text-slate-400 dark:text-slate-100" />
      {onClear && Boolean(value) && <button type="button" onClick={onClear} aria-label={zh ? '清空搜索' : 'Clear search'} className="mr-2 inline-flex shrink-0 items-center justify-center rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-white"><X size={13} /></button>}
      {onSearch && <button type="button" onClick={onSearch} className="sr-only">{zh ? '搜索' : 'Search'}</button>}
    </div>
  );
};
