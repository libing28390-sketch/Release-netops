import React, { useState, useEffect } from 'react';

interface CpuMemBarProps {
  cpu: number;
  mem: number;
  language?: string;
  empty?: boolean;
}

const barColor = (v: number) =>
  v > 80 ? 'bg-red-500' : v > 60 ? 'bg-amber-400' : 'bg-emerald-500';

const textColor = (v: number) =>
  v > 80 ? 'text-red-500' : v > 60 ? 'text-amber-500' : 'text-black/40 dark:text-white/40';

const CpuMemBar: React.FC<CpuMemBarProps> = ({ cpu, mem, language, empty = false }) => {
  const zh = language === 'zh';
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const frame = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(frame);
  }, []);

  if (empty) {
    return (
      <span className="text-[10px] text-black/20 dark:text-white/15">
        —
      </span>
    );
  }

  return (
    <div className="space-y-1.5 min-w-[80px]">
      <div className="flex items-center gap-1.5" title={`CPU ${cpu}%`}>
        <span className="text-[9px] font-semibold text-black/35 dark:text-white/35 w-7 shrink-0 font-mono">CPU</span>
        <div className="flex-1 h-[5px] rounded-full bg-black/5 dark:bg-white/8 overflow-hidden min-w-[40px] max-w-[56px]">
          <div
            className={`h-full rounded-full ${barColor(cpu)} transition-all duration-700 ease-out`}
            style={{ width: mounted ? `${cpu}%` : '0%' }}
          />
        </div>
        <span className={`text-[9px] font-semibold tabular-nums w-7 text-right font-mono ${textColor(cpu)}`}>
          {cpu}%
        </span>
      </div>
      <div className="flex items-center gap-1.5" title={`MEM ${mem}%`}>
        <span className="text-[9px] font-semibold text-black/35 dark:text-white/35 w-7 shrink-0 font-mono">MEM</span>
        <div className="flex-1 h-[5px] rounded-full bg-black/5 dark:bg-white/8 overflow-hidden min-w-[40px] max-w-[56px]">
          <div
            className={`h-full rounded-full ${barColor(mem)} transition-all duration-700 ease-out`}
            style={{ width: mounted ? `${mem}%` : '0%' }}
          />
        </div>
        <span className={`text-[9px] font-semibold tabular-nums w-7 text-right font-mono ${textColor(mem)}`}>
          {mem}%
        </span>
      </div>
    </div>
  );
};

export default CpuMemBar;
