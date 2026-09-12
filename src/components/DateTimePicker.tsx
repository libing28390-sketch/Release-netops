import React, { useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
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

/* ── Scrollable time column (compact) ── */
const ITEM_H = 24; // px per row
const COL_H = 120; // 5 visible items
const TimeColumn: React.FC<{ count: number; value: number; onChange: (v: number) => void }> = ({ count, value, onChange }) => {
  const listRef = useRef<HTMLDivElement>(null);
  const didMount = useRef(false);

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const target = value * ITEM_H - (COL_H - ITEM_H) / 2;
    if (!didMount.current) {
      el.scrollTop = Math.max(0, target);
      didMount.current = true;
    } else {
      el.scrollTo({ top: Math.max(0, target), behavior: 'smooth' });
    }
  }, [value]);

  return (
    <div
      ref={listRef}
      className="overflow-y-auto rounded-lg bg-black/[0.02]"
      style={{ scrollbarWidth: 'none', height: COL_H, width: 42 }}
    >
      <style>{`.time-col::-webkit-scrollbar{display:none}`}</style>
      <div className="time-col">
        {Array.from({ length: count }, (_, i) => {
          const active = i === value;
          return (
            <button
              key={i}
              type="button"
              onClick={() => onChange(i)}
              className={`
                w-full flex items-center justify-center font-mono transition-all duration-150
                ${active
                  ? 'bg-[#00bceb] text-white font-semibold rounded-md shadow-sm'
                  : 'text-[#00172D]/45 hover:text-[#00172D] hover:bg-black/[0.04] rounded'}
              `}
              style={{ height: ITEM_H, fontSize: 11, lineHeight: `${ITEM_H}px` }}
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
  const [dropUp, setDropUp] = useState(false);
  const [dropdownPos, setDropdownPos] = useState<{ top: number; left: number } | null>(null);

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
      const dropdownW = mode === 'datetime' ? 380 : 280;
      const dropdownH = 340;

      const boundaryLeft = boundaryRect ? boundaryRect.left + 8 : 8;
      const boundaryRight = boundaryRect ? boundaryRect.right - 8 : window.innerWidth - 8;
      const boundaryTop = boundaryRect ? boundaryRect.top + 8 : 8;
      const boundaryBottom = boundaryRect ? boundaryRect.bottom - 8 : window.innerHeight - 8;

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
        <label className="block text-xs font-semibold text-black/50 mb-1.5">
          {label} {required && <span className="text-rose-500 ml-0.5">*</span>}
        </label>
      )}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-2.5 text-sm border border-black/10 rounded-xl outline-none hover:border-[#00bceb]/40 focus:border-[#00bceb]/50 bg-white text-left transition-colors"
      >
        <Calendar size={14} className="text-black/30 flex-shrink-0" />
        <span className={displayValue ? 'text-[#00172D]' : 'text-black/30'}>
          {displayValue || placeholder || (zh ? '选择时间...' : 'Select time...')}
        </span>
      </button>

      {open && dropdownPos && createPortal(
        <div
          ref={dropdownRef}
          className="fixed z-[9999] bg-white rounded-xl border border-black/10 shadow-lg"
          style={{ top: dropdownPos.top, left: dropdownPos.left, width: mode === 'datetime' ? 380 : 280 }}
        >
          {/* Calendar Header */}
          <div className="flex items-center justify-between px-3 pt-2.5 pb-1">
            <button type="button" onClick={prevMonth} className="p-1 rounded-lg hover:bg-black/5 text-black/40 hover:text-black/70 transition-colors">
              <ChevronLeft size={16} />
            </button>
            <span className="text-sm font-bold text-[#00172D]">{monthLabel}</span>
            <button type="button" onClick={nextMonth} className="p-1 rounded-lg hover:bg-black/5 text-black/40 hover:text-black/70 transition-colors">
              <ChevronRight size={16} />
            </button>
          </div>

          {/* Calendar + Time side by side */}
          <div className="flex">
            {/* Left: Calendar */}
            <div className={mode === 'datetime' ? 'flex-1 min-w-0' : 'w-full'}>
              {/* Weekday Headers */}
              <div className="grid grid-cols-7 px-2.5">
                {weekdays.map(w => (
                  <div key={w} className="text-center text-[10px] font-bold text-black/30 uppercase py-0.5">{w}</div>
                ))}
              </div>

              {/* Day Grid */}
              <div className="grid grid-cols-7 px-2.5 pb-1">
                {cells.map((c, i) => {
                  const selected = c.current && isSelected(c.day);
                  const todayMark = c.current && isToday(c.day);
                  return (
                    <button
                      key={i}
                      type="button"
                      onClick={() => c.current && selectDay(c.day)}
                      className={`
                        h-[26px] text-[11px] rounded-md transition-all
                        ${!c.current ? 'text-black/15 cursor-default' : 'hover:bg-[#00bceb]/10 cursor-pointer'}
                        ${selected ? 'bg-[#00bceb] text-white font-bold hover:bg-[#0891b2]' : ''}
                        ${todayMark && !selected ? 'font-bold text-[#00bceb] ring-1 ring-[#00bceb]/30' : ''}
                        ${c.current && !selected && !todayMark ? 'text-[#00172D]' : ''}
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
              <div className="w-[100px] flex flex-col border-l border-black/5 px-2 py-1">
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-1">
                    <Clock size={10} className="text-black/30" />
                    <span className="text-[9px] font-bold text-black/35 uppercase tracking-wider">{zh ? '时间' : 'TIME'}</span>
                  </div>
                  <button type="button" onClick={setNow} className="text-[9px] font-semibold text-[#00bceb] hover:text-[#0891b2] transition-colors px-1 py-0.5 rounded hover:bg-[#00bceb]/10">
                    {zh ? '现在' : 'Now'}
                  </button>
                </div>
                <div className="flex items-center justify-center gap-1 flex-1">
                  <TimeColumn count={24} value={selHour} onChange={setSelHour} />
                  <span className="text-black/20 font-bold text-sm">:</span>
                  <TimeColumn count={60} value={selMinute} onChange={setSelMinute} />
                </div>
              </div>
            )}
          </div>

          {/* Footer: Clear + Confirm */}
          <div className="border-t border-black/5 px-3 py-2 flex items-center justify-between">
            <button
              type="button"
              onClick={handleClear}
              className="inline-flex items-center gap-1 text-xs text-black/40 hover:text-red-500 transition-colors"
            >
              <X size={12} />
              {zh ? '清除' : 'Clear'}
            </button>
            <button
              type="button"
              onClick={handleConfirm}
              className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-[#00bceb] text-white text-xs font-semibold hover:bg-[#0891b2] transition-all"
            >
              <Check size={12} />
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
