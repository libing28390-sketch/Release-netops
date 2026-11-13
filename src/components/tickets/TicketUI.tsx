import React, { useRef } from 'react';
import { ClipboardList, type LucideIcon } from 'lucide-react';
import { FormDialogShell } from '../ui/FormLayout';
import { ActionButton } from '../ui/ActionIconButton';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import { useFocusTrap } from '../../hooks/useFocusTrap';

export const ticketSurfaceClass = 'rounded-xl border border-[var(--ui-border)] bg-[var(--ui-surface)]';
export const ticketInputClass = 'min-h-10 w-full rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-fg)] outline-none transition-colors placeholder:text-[var(--ui-fg-subtle)] focus:border-[var(--ui-accent)] focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)]/15 disabled:cursor-not-allowed disabled:opacity-50';
export const ticketLabelClass = 'mb-1.5 block text-xs font-medium text-[var(--ui-fg-muted)]';

interface TicketDialogProps {
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  actions?: React.ReactNode;
  onClose: () => void;
  closeDisabled?: boolean;
  language?: string;
  widthClassName?: string;
  className?: string;
  bodyClassName?: string;
  initialFocusSelector?: string;
}

/** Ticket dialogs share sizing, persistent actions, Escape, focus containment and focus return. */
export const TicketDialog: React.FC<TicketDialogProps> = ({
  title, description, children, actions, onClose, closeDisabled = false,
  language = 'zh', widthClassName = 'max-w-3xl', className = '', bodyClassName = '',
  initialFocusSelector,
}) => {
  const dialogRef = useRef<HTMLDivElement>(null);
  useEscapeClose(true, () => { if (!closeDisabled) onClose(); });
  useFocusTrap(dialogRef, true, initialFocusSelector);
  return (
    <div ref={dialogRef} tabIndex={-1} className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/45 p-3 outline-none sm:p-5" onMouseDown={(event) => { if (event.target === event.currentTarget && !closeDisabled) onClose(); }}>
      <FormDialogShell title={title} description={description} onClose={onClose} closeDisabled={closeDisabled} language={language} widthClassName={widthClassName} className={`${actions === null ? '[&>.nx-form-dialog-footer]:hidden' : ''} ${className}`} bodyClassName={bodyClassName} actions={actions === null ? null : <div className="flex flex-wrap items-center justify-end gap-2 px-5 py-3">{actions === undefined ? <ActionButton onClick={onClose} disabled={closeDisabled}>{language === 'zh' ? '关闭' : 'Close'}</ActionButton> : actions}</div>}>
        {children}
      </FormDialogShell>
    </div>
  );
};

export const TicketFacts: React.FC<{ items: Array<{ label: string; value: React.ReactNode }>; className?: string }> = ({ items, className = '' }) => (
  <dl className={`grid min-w-0 grid-cols-1 gap-x-6 gap-y-3 text-[13px] sm:grid-cols-2 xl:grid-cols-3 ${className}`}>
    {items.map((item) => <div key={item.label} className="min-w-0"><dt className="text-xs text-[var(--ui-fg-muted)]">{item.label}</dt><dd className="mt-1 break-words font-medium leading-5 text-[var(--ui-fg)]">{item.value == null || item.value === '' ? '—' : item.value}</dd></div>)}
  </dl>
);

export const TicketEmptyState: React.FC<{ title: string; description?: string; icon?: LucideIcon; action?: React.ReactNode; compact?: boolean }> = ({ title, description, icon: Icon = ClipboardList, action, compact = false }) => (
  <div className={`flex flex-col items-center justify-center px-5 text-center ${compact ? 'min-h-24 py-5' : 'min-h-48 py-10'}`}>
    <span className="mb-3 rounded-xl bg-[var(--ui-surface-muted)] p-3 text-[var(--ui-fg-subtle)]"><Icon size={23} strokeWidth={1.5} /></span>
    <p className="text-sm font-medium text-[var(--ui-fg)]">{title}</p>
    {description && <p className="mt-1.5 max-w-md text-xs leading-5 text-[var(--ui-fg-muted)]">{description}</p>}
    {action && <div className="mt-4">{action}</div>}
  </div>
);
