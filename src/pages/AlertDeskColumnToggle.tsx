import React, { useEffect, useState } from 'react';
import { SlidersHorizontal } from 'lucide-react';
import {
  ALERT_DESK_COLUMN_DEFS,
  type AlertDeskColumnKey,
  type AlertDeskColumnVisibility,
  defaultAlertDeskColumnVisibility,
} from './alertDeskColumns';

interface AlertDeskColumnToggleProps {
  columns: AlertDeskColumnVisibility;
  onChange: (key: AlertDeskColumnKey, visible: boolean) => void;
  onReset: () => void;
  language: string;
}

const AlertDeskColumnToggle: React.FC<AlertDeskColumnToggleProps> = ({ columns, onChange, onReset, language }) => {
  const [open, setOpen] = useState(false);
  const ref = React.useRef<HTMLDivElement>(null);
  const zh = language === 'zh';
  const visibleCount = ALERT_DESK_COLUMN_DEFS.filter(({ key }) => columns[key]).length;

  useEffect(() => {
    if (!open) return;
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', closeOnOutsideClick);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('mousedown', closeOnOutsideClick);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="alert-desk-column-options"
        onClick={() => setOpen((value) => !value)}
        title={zh ? '列显示设置' : 'Column visibility'}
        className="inline-flex items-center gap-1.5 rounded-xl border border-black/10 bg-white px-3 py-2.5 text-xs font-semibold text-[#164e63] transition-colors hover:bg-black/[0.03]"
      >
        <SlidersHorizontal size={13} />
        <span>{zh ? '列设置' : 'Columns'}</span>
      </button>
      {open && (
        <div className="absolute right-0 top-full z-50 mt-1.5 max-h-[70vh] w-56 overflow-y-auto rounded-2xl border border-gray-100 bg-white py-2 shadow-xl shadow-black/10 dark:border-zinc-800 dark:bg-zinc-900 dark:shadow-black/40">
          <div id="alert-desk-column-options" className="mb-1 border-b border-gray-100 px-3 pb-1.5 text-[10px] font-bold uppercase tracking-wider text-gray-400 dark:border-zinc-800">
            {zh ? '自定义展示列' : 'Visible columns'}
          </div>
          <div className="border-b border-gray-100 pb-1 dark:border-zinc-800">
            {ALERT_DESK_COLUMN_DEFS.map(({ key, zh: labelZh, en: labelEn }) => (
              <label key={key} className="flex cursor-pointer items-center gap-2.5 px-3 py-1.5 text-xs text-gray-700 transition-colors hover:bg-gray-50 dark:text-zinc-300 dark:hover:bg-zinc-800">
                <input
                  type="checkbox"
                  checked={columns[key]}
                  disabled={columns[key] && visibleCount <= 1}
                  aria-label={zh ? labelZh : labelEn}
                  onChange={(event) => onChange(key, event.target.checked)}
                  className="h-3.5 w-3.5 cursor-pointer rounded border-gray-300 accent-blue-600"
                />
                <span className="font-medium">{zh ? labelZh : labelEn}</span>
              </label>
            ))}
          </div>
          <button
            type="button"
            onClick={() => { onReset(); setOpen(false); }}
            className="mt-1 w-full cursor-pointer px-3 py-2 text-left text-xs font-semibold text-blue-600 hover:bg-blue-50 dark:text-blue-400 dark:hover:bg-blue-950/30"
          >
            {zh ? '恢复默认列' : 'Restore default columns'}
          </button>
        </div>
      )}
    </div>
  );
};

export default AlertDeskColumnToggle;
