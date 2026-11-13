import React from 'react';
import { AlertTriangle, Loader2, LockKeyhole, RefreshCw } from 'lucide-react';
import { ActionButton } from '../ui/ActionIconButton';

interface StateProps {
  title: string;
  message?: string;
  actionLabel?: string;
  onAction?: () => void;
}

export const LoadingState: React.FC<{ label?: string }> = ({ label = '加载中…' }) => (
  <div className="flex min-h-36 items-center justify-center gap-2 rounded-xl border border-[var(--ui-border)] bg-[var(--ui-surface)] p-8 text-sm text-[var(--muted-text)]" role="status">
    <Loader2 size={18} className="animate-spin" aria-hidden="true" />
    {label}
  </div>
);

export const EmptyState: React.FC<{ title: string; message?: string }> = ({ title, message }) => (
  <div className="flex min-h-36 flex-col items-center justify-center rounded-xl border border-dashed border-[var(--ui-border)] bg-[var(--ui-surface)] p-8 text-center">
    <div className="text-sm font-semibold text-[var(--heading-text)]">{title}</div>
    {message && <div className="mt-1 text-xs text-[var(--muted-text)]">{message}</div>}
  </div>
);

export const ErrorState: React.FC<StateProps> = ({ title, message, actionLabel = '重试', onAction }) => (
  <div className="flex min-h-36 flex-col items-center justify-center rounded-xl border border-rose-200 bg-rose-50/60 p-8 text-center dark:border-rose-900/50 dark:bg-rose-950/20" role="alert">
    <AlertTriangle size={20} className="text-rose-600" aria-hidden="true" />
    <div className="mt-2 text-sm font-semibold text-rose-800 dark:text-rose-200">{title}</div>
    {message && <div className="mt-1 max-w-lg text-xs text-rose-700 dark:text-rose-300">{message}</div>}
    {onAction && <ActionButton icon={RefreshCw} variant="danger" size="sm" onClick={onAction} className="mt-3">{actionLabel}</ActionButton>}
  </div>
);

export const ForbiddenState: React.FC<{ message?: string }> = ({ message = '当前账号没有访问专线中心的权限。' }) => (
  <div className="flex min-h-48 flex-col items-center justify-center rounded-xl border border-amber-200 bg-amber-50/70 p-8 text-center dark:border-amber-900/50 dark:bg-amber-950/20" role="alert">
    <LockKeyhole size={22} className="text-amber-700 dark:text-amber-300" aria-hidden="true" />
    <div className="mt-2 text-sm font-semibold text-amber-900 dark:text-amber-200">无权访问</div>
    <div className="mt-1 text-xs text-amber-800 dark:text-amber-300">{message}</div>
  </div>
);
