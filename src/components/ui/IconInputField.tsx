import React from 'react';
import type { LucideIcon } from 'lucide-react';
import { cn } from '../../lib/cn';

export type IconInputFieldTheme = 'light' | 'dark';

export interface IconInputFieldProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'id' | 'value' | 'onChange' | 'size'> {
  id: string;
  label: string;
  icon: LucideIcon;
  value: string;
  onChange: React.ChangeEventHandler<HTMLInputElement>;
  error?: string;
  theme?: IconInputFieldTheme;
  labelClassName?: string;
}

/** Shared labelled input with a leading icon and a consistent validation state. */
export const IconInputField: React.FC<IconInputFieldProps> = ({
  id,
  label,
  icon: Icon,
  value,
  onChange,
  error,
  theme = 'light',
  labelClassName,
  className,
  type = 'text',
  'aria-describedby': ariaDescribedBy,
  'aria-invalid': ariaInvalid,
  ...inputProps
}) => {
  const isDark = theme === 'dark';
  const errorId = `${id}-error`;
  const describedBy = [ariaDescribedBy, error ? errorId : undefined].filter(Boolean).join(' ') || undefined;

  return (
    <div className="min-w-0">
      <label
        htmlFor={id}
        className={cn(
          'mb-1.5 block text-[11px] font-medium',
          isDark ? 'text-white/50' : 'text-slate-600',
          labelClassName,
        )}
      >
        {label}
      </label>
      <div className="relative">
        <Icon
          size={14}
          aria-hidden="true"
          className={cn(
            'pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2',
            error ? 'text-rose-400' : isDark ? 'text-white/30' : 'text-slate-400',
          )}
        />
        <input
          {...inputProps}
          id={id}
          type={type}
          value={value}
          onChange={onChange}
          aria-invalid={error ? true : ariaInvalid ?? false}
          aria-describedby={describedBy}
          className={cn(
            'h-[38px] w-full rounded-xl border pl-9 pr-3.5 text-xs outline-none transition-all focus:ring-2',
            isDark
              ? 'bg-black/20 text-white placeholder-white/50'
              : 'bg-white text-slate-800 placeholder-slate-500',
            error
              ? 'border-rose-400 focus:border-rose-500 focus:ring-rose-500/15'
              : isDark
                ? 'border-white/15 focus:border-cyan-400 focus:ring-cyan-500/20'
                : 'border-slate-200 focus:border-cyan-500 focus:ring-cyan-500/10',
            className,
          )}
        />
      </div>
      {error && (
        <p id={errorId} className="mt-1 text-[10px] leading-4 text-rose-600">
          {error}
        </p>
      )}
    </div>
  );
};

export default IconInputField;
