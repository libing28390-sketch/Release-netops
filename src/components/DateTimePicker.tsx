import React, { useState, useRef, useEffect, useLayoutEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useEscapeClose } from '../hooks/useEscapeClose';
import { Calendar, Clock, ChevronLeft, ChevronRight, Check, X } from 'lucide-react';

interface DateTimePickerProps {
  value: string;                       // "YYYY-MM-DDTHH:mm" format
  onChange: (value: string) => void;
  language: string;
  label?: string;
  className?: string;
  placeholder?: string;
  /** "datetime" (default) | "date" */
  mode?: 'datetime' | 'date';
  required?: boolean;
}

const WEEKDAYS_ZH = ['一', '二', '三', '四', '五', '六', '日'];
const WEEKDAYS_EN = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];
const MONTHS_ZH = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'];
const MONTHS_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function daysInMonth(year: number, month: number) {
  return new Date(year, month + 1, 0).getDate();
}

function firstDayOfMonth(year: number, month: number) {
  const d = new Date(year, month, 1).getDay();
  return d === 0 ? 6 : d - 1; // Monday = 0
}

function pad(n: number) {
  return n < 10 ? `0${n}` : String(n);
}

/* ── Scrollable time column ── */
const ITEM_H = 32; // px per row
const COL_H = 160; // 5 visible items
const COL_PADDING = (COL_H - ITEM_H) / 2;

export function getTimeColumnScrollTop(
  currentScrollTop: number,
  containerTop: number,
  containerHeight: number,
  selectedTop: number,
  selectedHeight: number,
): number {
  const selectedContentTop = currentScrollTop + selectedTop - containerTop;
  return Math.max(0, selectedContentTop - (containerHeight - selectedHeight) / 2);
}

interface TimeColumnProps {
  count: number;
  value: number;
  label: string;
  onChange: (v: number) => void;
}

const TimeColumn: React.FC<TimeColumnProps> = ({ count, value, label, onChange }) => {
  const listRef = useRef<HTMLDivElement>(null);
  const selectedItemRef = useRef<HTMLButtonElement>(null);
  const hasPositionedRef = useRef(false);

  useLayoutEffect(() => {
    const el = listRef.current;
    const selectedItem = selectedItemRef.current;
    if (!el || !selectedItem) return;

    const containerRect = el.getBoundingClientRect();
    const selectedRect = selectedItem.getBoundingClientRect();
    const targetScrollTop = getTimeColumnScrollTop(
      el.scrollTop,
      containerRect.top,
      el.clientHeight,
      selectedRect.top,
      selectedItem.offsetHeight,
    );

    if (Math.abs(el.scrollTop - targetScrollTop) < 1) {
      hasPositionedRef.current = true;
      return;
    }

    const shouldPositionImmediately = !hasPositionedRef.current
      || (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false)
      || typeof el.scrollTo !== 'function';
    hasPositionedRef.current = true;

    if (shouldPositionImmediately) {
      el.scrollTop = targetScrollTop;
      return;
    }

    el.scrollTo({ top: targetScrollTop, behavior: 'smooth' });
  }, [count, value]);

  return (
    <div
      ref={listRef}
      className="overflow-y-auto rounded-lg bg-[var(--ui-surface-muted)]"
      style={{ scrollbarWidth: 'none', height: COL_H, width: 48 }}
      role="group"
      aria-label={label}
      data-time-column={label}
    >
      <style>{`.time-col::-webkit-scrollbar{display:none}`}</style>
      <div className="time-col" style={{ paddingBlock: COL_PADDING }}>
        {Array.from({ length: count }, (_, i) => {
          const active = i === value;
          return (
            <button
              key={i}
              ref={active ? selectedItemRef : undefined}
              type="button"
              aria-pressed={active}
              data-time-value={i}
              onClick={() => onChange(i)}
              className={`
                w-full flex items-center justify-center font-mono transition-colors duration-100
                ${active
                  ? 'bg-[var(--ui-accent)] text-white font-semibold rounded-md shadow-sm'
                  : 'text-[var(--ui-fg-muted)] hover:text-[var(--ui-fg)] hover:bg-[var(--ui-surface-emphasis)] rounded'}
              `}
              style={{ height: ITEM_H, fontSize: 13, lineHeight: `${ITEM_H}px` }}
            >
              {pad(i)}
            </button>
          );
        })}
      </div>
    </div>
  );
};

const DateTimePicker: React.FC<DateTimePickerProps> = ({
  value,
  onChange,
  language,
  label,
  className = '',
  placeholder,
  mode = 'datetime',
  required = false,
}) => {
  const zh = language === 'zh';
  const containerRef = useRef<HTMLDivElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  useEscapeClose(open, () => setOpen(false));
  const [dropUp, setDropUp] = useState(false);
  const [dropdownPos, setDropdownPos] = useState<{ top: number; left: number; width: number; height: number } | null>(null);

  // Parse initial value
  const parseValue = useCallback((v: string) => {
    if (!v) {
      const now = new Date();
      return {
        year: now.getFullYear(),
        month: now.getMonth(),
        day: now.getDate(),
        hour: now.getHours(),
        minute: now.getMinutes(),
      };
    }
    const [datePart, timePart] = v.split('T');
    const [y, m, d] = datePart.split('-').map(Number);
    const [h, min] = timePart ? timePart.split(':').map(Number) : [0, 0];
    return { year: y, month: m - 1, day: d, hour: h, minute: min };
  }, []);

  const parsed = parseValue(value);
  const [viewYear, setViewYear] = useState(parsed.year);
  const [viewMonth, setViewMonth] = useState(parsed.month);
  const [selYear, setSelYear] = useState(parsed.year);
  const [selMonth, setSelMonth] = useState(parsed.month);
  const [selDay, setSelDay] = useState(parsed.day);
  const [selHour, setSelHour] = useState(parsed.hour);
  const [selMinute, setSelMinute] = useState(parsed.minute);

  // Sync when value changes externally
  useEffect(() => {
    const p = parseValue(value);
    setViewYear(p.year);
    setViewMonth(p.month);
    setSelYear(p.year);
    setSelMonth(p.month);
    setSelDay(p.day);
    setSelHour(p.hour);
    setSelMinute(p.minute);
  }, [value, parseValue]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        containerRef.current && !containerRef.current.contains(target) &&
        dropdownRef.current && !dropdownRef.current.contains(target)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  // Determine drop direction + fixed position for portal
  useEffect(() => {
    if (!open || !containerRef.current) return;
    const updatePosition = () => {
      const rect = containerRef.current!.getBoundingClientRect();
      const boundaryEl = containerRef.current!.closest('[data-dropdown-boundary="true"]') as HTMLElement | null;
      const boundaryRect = boundaryEl?.getBoundingClientRect();
      const preferredWidth = mode === 'datetime' ? 416 : 304;
      const preferredHeight = mode === 'datetime' ? 360 : 328;

      const boundaryLeft = boundaryRect ? boundaryRect.left + 8 : 8;
      const boundaryRight = boundaryRect ? boundaryRect.right - 8 : window.innerWidth - 8;
      const boundaryTop = boundaryRect ? boundaryRect.top + 8 : 8;
      const boundaryBottom = boundaryRect ? boundaryRect.bottom - 8 : window.innerHeight - 8;

      const availableWidth = Math.max(1, Math.min(window.innerWidth - 16, boundaryRight - boundaryLeft));
      const availableHeight = Math.max(200, Math.min(window.innerHeight - 16, boundaryBottom - boundaryTop));
      const dropdownW = Math.min(preferredWidth, availableWidth);
      const dropdownH = Math.min(preferredHeight, availableHeight);

      const spaceBelow = boundaryBottom - rect.bottom;
      const spaceAbove = rect.top - boundaryTop;
      const up = spaceBelow < dropdownH && spaceAbove > dropdownH;
      setDropUp(up);

      let left = rect.left;
      const minLeft = Math.max(8, boundaryLeft);
      const maxLeft = Math.max(minLeft, boundaryRight - dropdownW);
      if (left > maxLeft) left = maxLeft;
      if (left < minLeft) left = minLeft;

      let top = up ? rect.top - dropdownH - 4 : rect.bottom + 4;
      const minTop = Math.max(8, boundaryTop);
      const maxTop = Math.max(minTop, Math.min(window.innerHeight - dropdownH - 8, boundaryBottom - dropdownH));
      if (top > maxTop) top = maxTop;
      if (top < minTop) top = minTop;

      setDropdownPos({
        top,
        left,
        width: dropdownW,
        height: dropdownH,
      });
    };
    updatePosition();
    window.addEventListener('scroll', updatePosition, true);
    window.addEventListener('resize', updatePosition);
    return () => {
      window.removeEventListener('scroll', updatePosition, true);
      window.removeEventListener('resize', updatePosition);
    };
  }, [open, mode]);

  const prevMonth = () => {
    if (viewMonth === 0) { setViewMonth(11); setViewYear(y => y - 1); }
    else setViewMonth(m => m - 1);
  };
  const nextMonth = () => {
    if (viewMonth === 11) { setViewMonth(0); setViewYear(y => y + 1); }
    else setViewMonth(m => m + 1);
  };

  const selectDay = (d: number) => {
    setSelYear(viewYear);
    setSelMonth(viewMonth);
    setSelDay(d);
  };

  const handleConfirm = () => {
    const val = mode === 'date'
      ? `${selYear}-${pad(selMonth + 1)}-${pad(selDay)}`
      : `${selYear}-${pad(selMonth + 1)}-${pad(selDay)}T${pad(selHour)}:${pad(selMinute)}`;
    onChange(val);
    setOpen(false);
  };

  const handleClear = () => {
    onChange('');
    setOpen(false);
  };

  const setNow = () => {
    const now = new Date();
    setViewYear(now.getFullYear());
    setViewMonth(now.getMonth());
    setSelYear(now.getFullYear());
    setSelMonth(now.getMonth());
    setSelDay(now.getDate());
    setSelHour(now.getHours());
    setSelMinute(now.getMinutes());
  };

  // Build calendar grid
  const totalDays = daysInMonth(viewYear, viewMonth);
  const startOffset = firstDayOfMonth(viewYear, viewMonth);
  const prevMonthDays = daysInMonth(viewYear, viewMonth === 0 ? 11 : viewMonth - 1);
  const cells: { day: number; current: boolean }[] = [];
  for (let i = startOffset - 1; i >= 0; i--) cells.push({ day: prevMonthDays - i, current: false });
  for (let d = 1; d <= totalDays; d++) cells.push({ day: d, current: true });
  const remaining = 42 - cells.length;
  for (let d = 1; d <= remaining; d++) cells.push({ day: d, current: false });

  const today = new Date();
  const isToday = (d: number) =>
    viewYear === today.getFullYear() && viewMonth === today.getMonth() && d === today.getDate();
  const isSelected = (d: number) =>
    viewYear === selYear && viewMonth === selMonth && d === selDay;

  const displayValue = value
    ? mode === 'date'
      ? value
      : value.replace('T', ' ')
    : '';

  const weekdays = zh ? WEEKDAYS_ZH : WEEKDAYS_EN;
  const monthLabel = zh
    ? `${viewYear}年${MONTHS_ZH[viewMonth]}`
    : `${MONTHS_EN[viewMonth]} ${viewYear}`;

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      {label && (
        <label className="mb-1.5 block text-[13px] font-semibold text-[var(--ui-fg-muted)]">
          {label} {required && <span className="text-rose-500 ml-0.5">*</span>}
        </label>
      )}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex min-h-10 w-full items-center gap-2 rounded-xl border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2.5 text-sm text-left text-[var(--ui-fg)] outline-none transition-colors hover:border-[var(--ui-border-strong)] focus-visible:border-[var(--ui-accent)] focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)]/20"
      >
        <Calendar size={16} className="flex-shrink-0 text-[var(--ui-fg-muted)]" />
        <span className={displayValue ? 'text-[var(--ui-fg)]' : 'text-[var(--ui-fg-subtle)]'}>
          {displayValue || placeholder || (zh ? '选择时间...' : 'Select time...')}
        </span>
      </button>

      {open && dropdownPos && createPortal(
        <div
          ref={dropdownRef}
          className="fixed z-[9999] overflow-y-auto rounded-2xl border border-[var(--ui-border)] bg-[var(--ui-surface)] shadow-xl"
          style={{ top: dropdownPos.top, left: dropdownPos.left, width: dropdownPos.width, maxHeight: dropdownPos.height }}
        >
          {/* Calendar Header */}
          <div className="flex items-center justify-between px-3 pt-3 pb-2">
            <button type="button" onClick={prevMonth} aria-label={zh ? '上个月' : 'Previous month'} className="flex min-h-9 min-w-9 items-center justify-center rounded-lg text-[var(--ui-fg-muted)] transition-colors hover:bg-[var(--ui-surface-muted)] hover:text-[var(--ui-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)]">
              <ChevronLeft size={18} />
            </button>
            <span className="text-base font-bold text-[var(--ui-fg)]">{monthLabel}</span>
            <button type="button" onClick={nextMonth} aria-label={zh ? '下个月' : 'Next month'} className="flex min-h-9 min-w-9 items-center justify-center rounded-lg text-[var(--ui-fg-muted)] transition-colors hover:bg-[var(--ui-surface-muted)] hover:text-[var(--ui-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)]">
              <ChevronRight size={18} />
            </button>
          </div>

          {/* Calendar + Time side by side */}
          <div className="flex">
            {/* Left: Calendar */}
            <div className={mode === 'datetime' ? 'flex-1 min-w-0' : 'w-full'}>
              {/* Weekday Headers */}
              <div className="grid grid-cols-7 px-3">
                {weekdays.map(w => (
                  <div key={w} className="py-1 text-center text-[11px] font-semibold text-[var(--ui-fg-muted)]">{w}</div>
                ))}
              </div>

              {/* Day Grid */}
              <div className="grid grid-cols-7 px-3 pb-2">
                {cells.map((c, i) => {
                  const selected = c.current && isSelected(c.day);
                  const todayMark = c.current && isToday(c.day);
                  return (
                    <button
                      key={i}
                      type="button"
                      onClick={() => c.current && selectDay(c.day)}
                      className={`
                        h-8 rounded-lg text-xs font-medium transition-colors
                        ${!c.current ? 'cursor-default text-[var(--ui-fg-subtle)]' : 'cursor-pointer hover:bg-[var(--ui-accent-subtle)]'}
                        ${selected ? 'bg-[var(--ui-accent)] font-bold text-white hover:bg-[var(--ui-accent-hover)]' : ''}
                        ${todayMark && !selected ? 'font-bold text-[var(--ui-accent)] ring-1 ring-[var(--ui-accent)]/30' : ''}
                        ${c.current && !selected && !todayMark ? 'text-[var(--ui-fg)]' : ''}
                      `}
                    >
                      {c.day}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Right: Time Selector (only for datetime mode) */}
            {mode === 'datetime' && (
              <div className="flex w-[116px] shrink-0 flex-col border-l border-[var(--ui-border)] px-2.5 py-2">
                <div className="mb-2 flex items-center justify-between">
                  <div className="flex items-center gap-1">
                    <Clock size={14} className="text-[var(--ui-fg-muted)]" />
                    <span className="text-xs font-semibold text-[var(--ui-fg-muted)]">{zh ? '时间' : 'Time'}</span>
                  </div>
                  <button type="button" onClick={setNow} className="min-h-8 rounded-md px-1.5 text-[11px] font-semibold text-[var(--ui-accent)] transition-colors hover:bg-[var(--ui-accent-subtle)] hover:text-[var(--ui-accent-hover)]">
                    {zh ? '现在' : 'Now'}
                  </button>
                </div>
                <div className="flex items-center justify-center gap-1 flex-1">
                  <TimeColumn count={24} value={selHour} label={zh ? '小时' : 'Hour'} onChange={setSelHour} />
                  <span className="text-base font-bold text-[var(--ui-fg-subtle)]">:</span>
                  <TimeColumn count={60} value={selMinute} label={zh ? '分钟' : 'Minute'} onChange={setSelMinute} />
                </div>
              </div>
            )}
          </div>

          {/* Footer: Clear + Confirm */}
          <div className="flex items-center justify-between border-t border-[var(--ui-border)] px-3 py-3">
            <button
              type="button"
              onClick={handleClear}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-lg px-2 text-[13px] font-medium text-[var(--ui-fg-muted)] transition-colors hover:bg-[var(--ui-danger-subtle)] hover:text-[var(--ui-danger)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)]"
            >
              <X size={14} />
              {zh ? '清除' : 'Clear'}
            </button>
            <button
              type="button"
              onClick={handleConfirm}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-[var(--ui-accent)] px-4 py-1.5 text-[13px] font-semibold text-white transition-colors hover:bg-[var(--ui-accent-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)] focus-visible:ring-offset-2"
            >
              <Check size={14} />
              {zh ? '确认' : 'Confirm'}
            </button>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
};

export default DateTimePicker;
