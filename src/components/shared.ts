// Shared CSS class constants used across page components
export const sectionHeaderRowClass = 'flex justify-between items-end';
export const sectionToolbarClass = 'flex gap-4 items-center bg-[var(--ui-surface)] p-4 rounded-xl border border-[var(--ui-border)] shadow-sm';
export const primaryActionBtnClass = 'inline-flex items-center gap-2 rounded-md border border-[var(--ui-accent)] bg-[var(--ui-accent)] px-4 py-2 text-[13px] font-semibold leading-5 text-white transition-colors hover:border-[var(--ui-accent-hover)] hover:bg-[var(--ui-accent-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50';
export const secondaryActionBtnClass = 'inline-flex items-center gap-2 rounded-md border border-[var(--ui-border)] bg-[var(--ui-surface)] px-4 py-2 text-[13px] font-semibold leading-5 text-[var(--ui-fg)] transition-colors hover:bg-[var(--ui-surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50';
export const darkActionBtnClass = 'inline-flex items-center gap-2 rounded-md border border-[var(--ui-fg)] bg-[var(--ui-fg)] px-4 py-2 text-[13px] font-semibold leading-5 text-[var(--ui-surface)] transition-colors hover:opacity-85 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50';
export const alertPanelClass = 'rounded-xl border border-[var(--ui-border)] bg-[var(--ui-surface)] shadow-sm';

export const severityBadgeClass = (severity?: string) => {
  switch (String(severity || '').toLowerCase()) {
    case 'critical': return 'bg-red-100 text-red-700 ring-1 ring-red-200';
    case 'major': return 'bg-orange-100 text-orange-700 ring-1 ring-orange-200';
    case 'high': return 'bg-rose-100 text-rose-700 ring-1 ring-rose-200';
    case 'warning': return 'bg-amber-100 text-amber-700 ring-1 ring-amber-200';
    case 'minor': return 'bg-emerald-100 text-emerald-700 ring-1 ring-emerald-200';
    case 'info': return 'bg-sky-100 text-sky-700 ring-1 ring-sky-200';
    case 'medium': return 'bg-yellow-100 text-yellow-700 ring-1 ring-yellow-200';
    default: return 'bg-slate-100 text-slate-700 ring-1 ring-slate-200';
  }
};

export const alertWorkflowBadgeClass = (status?: string) => {
  switch (String(status || '').toLowerCase()) {
    case 'resolved': return 'bg-emerald-100 text-emerald-700';
    case 'investigating': return 'bg-blue-100 text-blue-700';
    case 'acknowledged': return 'bg-sky-100 text-sky-700';
    case 'suppressed': return 'bg-slate-100 text-slate-700';
    default: return 'bg-red-100 text-red-700';
  }
};

export const complianceStatusBadgeClass = (status?: string) => {
  switch (String(status || '').toLowerCase()) {
    case 'open': return 'bg-red-100 text-red-700';
    case 'in_progress': return 'bg-blue-100 text-blue-700';
    case 'accepted_risk': return 'bg-purple-100 text-purple-700';
    case 'resolved': return 'bg-emerald-100 text-emerald-700';
    default: return 'bg-slate-100 text-slate-700';
  }
};

export const auditStatusBadgeClass = (status?: string) => {
  switch (String(status || '').toLowerCase()) {
    case 'success': case 'completed': case 'allowed': return 'bg-emerald-100 text-emerald-700';
    case 'failed': case 'error': case 'denied': return 'bg-red-100 text-red-700';
    case 'warning': case 'partial': return 'bg-amber-100 text-amber-700';
    default: return 'bg-slate-100 text-slate-700';
  }
};

export const parseJsonObject = (value?: string) => {
  if (!value) return {};
  try { return JSON.parse(value); } catch { return { raw: value }; }
};
