import React from 'react';

const controlClass = 'mt-1 w-full rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2 text-xs text-[var(--ui-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)] disabled:cursor-not-allowed disabled:opacity-70';

export interface FormSelectOption {
  value: string;
  label: string;
}

interface SharedFieldProps {
  label: string;
  helperText?: React.ReactNode;
  helperTone?: 'neutral' | 'warning';
  helperRole?: 'status' | 'alert';
  className?: string;
  controlClassName?: string;
  disabled?: boolean;
}

export interface SelectFieldProps extends SharedFieldProps {
  value: string;
  onChange: (value: string) => void;
  options: FormSelectOption[];
  language: 'zh' | 'en';
  placeholder?: string;
}

export const SelectField: React.FC<SelectFieldProps> = ({
  label,
  value,
  onChange,
  options,
  language,
  placeholder,
  helperText,
  helperTone = 'neutral',
  helperRole,
  className = '',
  controlClassName = '',
  disabled,
}) => {
  const id = React.useId();
  const helperId = `${id}-help`;
  return (
    <div className={`text-xs font-semibold text-[var(--muted-text)] ${className}`}>
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-describedby={helperText ? helperId : undefined}
        disabled={disabled}
        className={`${controlClass} ${controlClassName}`}
      >
        <option value="">{placeholder || (language === 'zh' ? '请选择' : 'Select')}</option>
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
      {helperText && (
        <p
          id={helperId}
          role={helperRole}
          className={`mt-1 text-[10px] font-normal leading-4 ${helperTone === 'warning' ? 'text-amber-700' : 'text-[var(--muted-text)]'}`}
        >
          {helperText}
        </p>
      )}
    </div>
  );
};

export interface TextFieldProps extends SharedFieldProps {
  value: string;
  onChange: (value: string) => void;
  type?: 'text' | 'number' | 'email';
  min?: number;
  max?: number;
  step?: number | 'any';
  placeholder?: string;
  suggestions?: string[];
  multiline?: boolean;
  rows?: number;
}

export const TextField: React.FC<TextFieldProps> = ({
  label,
  value,
  onChange,
  type = 'text',
  min,
  max,
  step,
  placeholder,
  suggestions,
  helperText,
  className = '',
  controlClassName = '',
  disabled,
  multiline,
  rows = 2,
}) => {
  const id = React.useId();
  const helperId = `${id}-help`;
  const suggestionsId = `${id}-suggestions`;
  const describedBy = helperText ? helperId : undefined;
  return (
    <div className={`text-xs font-semibold text-[var(--muted-text)] ${className}`}>
      <label htmlFor={id}>{label}</label>
      {multiline ? (
        <textarea
          id={id}
          rows={rows}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          aria-describedby={describedBy}
          disabled={disabled}
          className={`${controlClass} ${controlClassName}`}
        />
      ) : (
        <input
          id={id}
          type={type}
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          list={suggestions?.length ? suggestionsId : undefined}
          aria-describedby={describedBy}
          disabled={disabled}
          className={`${controlClass} ${controlClassName}`}
        />
      )}
      {suggestions?.length && !multiline && (
        <datalist id={suggestionsId}>
          {suggestions.map((suggestion) => <option key={suggestion} value={suggestion} />)}
        </datalist>
      )}
      {helperText && <p id={helperId} className="mt-1 text-[10px] font-normal leading-4 text-[var(--muted-text)]">{helperText}</p>}
    </div>
  );
};
