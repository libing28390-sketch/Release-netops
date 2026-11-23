import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Ban, History, KeyRound, RefreshCw, X, XCircle } from 'lucide-react';
import { getAIProviderKeyHistory, invalidateAIProviderKey, type AIProvider, type AIProviderKeyHistory } from '../../../api/ai';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import { useFocusTrap } from '../../../hooks/useFocusTrap';
import { ActionButton } from '../../../components/ui/ActionIconButton';
import { EmptyState } from '../../../components/ui/EmptyState';
import { StatusBadge, type StatusTone } from '../../../components/ui/StatusBadge';
import { cn } from '../../../lib/cn';
import type { ProviderPageCopy } from './ProviderManagementTab.copy';

/* Review item L6-d: key invalidation and key history for the Provider page.
 * Neither component ever renders key material -- the history endpoint does
 * not return it, and the invalidate dialog only sends a reason. */

const REASON_MAX = 80;

export const isValidInvalidationReason = (value: string) => {
  const trimmed = value.trim();
  return trimmed.length <= REASON_MAX && !/[\r\n]/.test(value);
};

const formatTime = (value: string | null | undefined, language: string) => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(language === 'en' ? 'en-US' : 'zh-CN', { hour12: false });
};

const versionTone = (status: string): StatusTone => {
  switch (status) {
    case 'active': return 'success';
    case 'invalidated': return 'danger';
    default: return 'neutral';
  }
};

const versionLabel = (status: string, copy: ProviderPageCopy) => {
  switch (status) {
    case 'active': return copy.statusActive;
    case 'retired': return copy.statusRetired;
    case 'invalidated': return copy.statusInvalidated;
    default: return status;
  }
};

const actionLabel = (action: string, copy: ProviderPageCopy) => {
  switch (action) {
    case 'rotate': return copy.actionRotate;
    case 'invalidate': return copy.actionInvalidate;
    default: return action;
  }
};

const reasonLabel = (reason: string | null | undefined, copy: ProviderPageCopy) => {
  if (!reason) return '—';
  return copy.reasons[reason] || reason;
};

/* ── Invalidate key ─────────────────────────────────────────────────────── */

interface ProviderKeyInvalidateDialogProps {
  provider: AIProvider;
  copy: ProviderPageCopy;
  onClose: () => void;
  onInvalidated: (updated: AIProvider) => void;
  onError: (message: string) => void;
}

export const ProviderKeyInvalidateDialog: React.FC<ProviderKeyInvalidateDialogProps> = ({ provider, copy, onClose, onInvalidated, onError }) => {
  const dialogRef = useRef<HTMLDivElement>(null);
  const [reason, setReason] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  useEscapeClose(!submitting, onClose);
  useFocusTrap(dialogRef, true, '#provider-invalidate-reason');

  const reasonValid = isValidInvalidationReason(reason);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!acknowledged || !reasonValid || submitting) return;
    setSubmitting(true);
    try {
      const updated = await invalidateAIProviderKey(provider.id, reason);
      onInvalidated(updated);
    } catch (err: unknown) {
      onError(err instanceof Error && err.message ? err.message : copy.invalidateFailed);
      setSubmitting(false);
    }
  };

  return (
    <div ref={dialogRef} className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/40 p-4" role="alertdialog" aria-modal="true" aria-labelledby="provider-invalidate-title" aria-describedby="provider-invalidate-body" tabIndex={-1}>
      <form onSubmit={submit} className="nx-form-dialog-surface flex w-full max-w-md flex-col overflow-hidden">
        <div className="nx-dialog-header flex items-start justify-between gap-4 border-b px-6 py-4">
          <div className="flex min-w-0 items-start gap-3">
            <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-danger-subtle text-danger"><Ban size={16} aria-hidden="true" /></span>
            <div className="min-w-0">
              <h3 id="provider-invalidate-title" className="text-base font-semibold text-fg">{copy.invalidateTitle}</h3>
              <p id="provider-invalidate-body" className="mt-1 text-[13px] leading-5 text-fg-muted">{copy.invalidateBody(provider.name)}</p>
            </div>
          </div>
          <button type="button" onClick={onClose} disabled={submitting} aria-label={copy.invalidateCancel} className="shrink-0 text-fg-subtle transition-colors hover:text-fg disabled:opacity-50">
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="space-y-4 px-6 py-5">
          <div>
            <label htmlFor="provider-invalidate-reason" className="mb-1.5 block text-[13px] font-medium text-fg">{copy.invalidateReason}</label>
            <input
              id="provider-invalidate-reason"
              type="text"
              maxLength={REASON_MAX}
              value={reason}
              placeholder={copy.invalidateReasonPlaceholder}
              onChange={(event) => setReason(event.target.value)}
              aria-invalid={!reasonValid}
              aria-describedby="provider-invalidate-reason-help"
              className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-fg outline-none transition-colors placeholder:text-fg-subtle focus:border-accent focus:ring-2 focus:ring-accent/20"
            />
            <p id="provider-invalidate-reason-help" className={cn('mt-1.5 text-xs leading-5', reasonValid ? 'text-fg-muted' : 'text-danger')}>
              {reasonValid ? copy.invalidateReasonHelp : copy.invalidateReasonTooLong}
            </p>
          </div>
          <label className="flex items-start gap-2 text-[13px] text-fg">
            <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} className="mt-0.5 h-4 w-4 rounded border-line-strong accent-[var(--ui-danger)]" />
            {copy.invalidateConfirmCheck}
          </label>
        </div>
        <div className="nx-dialog-footer flex flex-col-reverse gap-2 border-t px-6 py-4 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} disabled={submitting} className="nx-dialog-action-secondary px-4 py-2">{copy.invalidateCancel}</button>
          <ActionButton type="submit" variant="danger" size="md" icon={submitting ? RefreshCw : Ban} iconClassName={submitting ? 'animate-spin motion-reduce:animate-none' : undefined} disabled={!acknowledged || !reasonValid || submitting}>
            {submitting ? copy.invalidating : copy.invalidateConfirm}
          </ActionButton>
        </div>
      </form>
    </div>
  );
};

/* ── Key history ────────────────────────────────────────────────────────── */

interface ProviderKeyHistoryDrawerProps {
  provider: AIProvider;
  copy: ProviderPageCopy;
  language: string;
  onClose: () => void;
}

export const ProviderKeyHistoryDrawer: React.FC<ProviderKeyHistoryDrawerProps> = ({ provider, copy, language, onClose }) => {
  const drawerRef = useRef<HTMLDivElement>(null);
  const [history, setHistory] = useState<AIProviderKeyHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEscapeClose(true, onClose);
  useFocusTrap(drawerRef, true, '#provider-key-history-close');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setHistory(await getAIProviderKeyHistory(provider.id));
    } catch (err: unknown) {
      setError(err instanceof Error && err.message ? err.message : copy.historyFailed);
    } finally {
      setLoading(false);
    }
  }, [provider.id, copy]);

  useEffect(() => { void load(); }, [load]);

  const versions = history?.versions || [];
  const audit = history?.audit || [];

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/30" onClick={onClose}>
      <div
        ref={drawerRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="provider-key-history-title"
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
        className="flex h-full w-full max-w-2xl flex-col border-l border-line bg-surface shadow-xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div className="flex min-w-0 items-start gap-3">
            <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-muted text-fg-muted"><History size={16} aria-hidden="true" /></span>
            <div className="min-w-0">
              <h3 id="provider-key-history-title" className="truncate text-base font-semibold text-fg">{copy.historyTitle(provider.name)}</h3>
              <p className="mt-0.5 text-xs leading-5 text-fg-muted">{copy.historyBody(history?.retention_days ?? 30)}</p>
            </div>
          </div>
          <button id="provider-key-history-close" type="button" onClick={onClose} aria-label={copy.historyClose} className="shrink-0 rounded-md text-fg-subtle transition-colors hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-4">
          {loading ? (
            <div role="status" aria-live="polite" className="flex items-center gap-2 text-[13px] text-fg-muted">
              <RefreshCw size={15} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />{copy.historyLoading}
            </div>
          ) : error ? (
            <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-danger/30 bg-danger-subtle px-4 py-3 text-[13px] text-danger">
              <span className="flex items-start gap-2"><XCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />{error}</span>
              <ActionButton type="button" variant="danger" onClick={() => void load()}>{copy.historyRetry}</ActionButton>
            </div>
          ) : versions.length === 0 && audit.length === 0 ? (
            <EmptyState icon={KeyRound} title={copy.historyEmpty} description={copy.historyEmptyBody} />
          ) : (
            <>
              <section aria-labelledby="provider-key-versions-heading">
                <h4 id="provider-key-versions-heading" className="mb-2 text-sm font-semibold text-fg">{copy.historyVersions}</h4>
                {versions.length === 0 ? (
                  <p className="text-[13px] text-fg-muted">{copy.historyEmpty}</p>
                ) : (
                  <div className="overflow-x-auto rounded-lg border border-line">
                    <table className="w-full text-[13px]">
                      <thead>
                        <tr>
                          <th scope="col">{copy.colVersion}</th>
                          <th scope="col">{copy.colStatus}</th>
                          <th scope="col">{copy.colCreated}</th>
                          <th scope="col">{copy.colCreatedBy}</th>
                          <th scope="col">{copy.colEnded}</th>
                          <th scope="col">{copy.colCiphertext}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {versions.map((version) => (
                          <tr key={version.key_version}>
                            <td className="font-mono tabular-nums">v{version.key_version}</td>
                            <td><StatusBadge tone={versionTone(version.status)} dot>{versionLabel(version.status, copy)}</StatusBadge></td>
                            <td className="whitespace-nowrap tabular-nums text-fg-muted">{formatTime(version.created_at, language)}</td>
                            <td className="text-fg-muted">{version.created_by || '—'}</td>
                            <td className="whitespace-nowrap tabular-nums text-fg-muted">{formatTime(version.invalidated_at || version.retired_at, language)}</td>
                            <td className="text-fg-muted">{version.ciphertext_retained ? copy.ciphertextRetained : copy.ciphertextDeleted}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>

              <section aria-labelledby="provider-key-audit-heading">
                <h4 id="provider-key-audit-heading" className="mb-2 text-sm font-semibold text-fg">{copy.historyAudit}</h4>
                {audit.length === 0 ? (
                  <p className="text-[13px] text-fg-muted">{copy.historyAuditEmpty}</p>
                ) : (
                  <div className="overflow-x-auto rounded-lg border border-line">
                    <table className="w-full text-[13px]">
                      <thead>
                        <tr>
                          <th scope="col">{copy.colTime}</th>
                          <th scope="col">{copy.colAction}</th>
                          <th scope="col">{copy.colVersion}</th>
                          <th scope="col">{copy.colActor}</th>
                          <th scope="col">{copy.colReason}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {audit.map((entry, index) => (
                          <tr key={`${entry.created_at || ''}-${entry.action}-${index}`}>
                            <td className="whitespace-nowrap tabular-nums text-fg-muted">{formatTime(entry.created_at, language)}</td>
                            <td>
                              <StatusBadge tone={entry.action === 'invalidate' ? 'danger' : 'accent'}>{actionLabel(entry.action, copy)}</StatusBadge>
                            </td>
                            <td className="font-mono tabular-nums text-fg-muted">{entry.key_version != null ? `v${entry.key_version}` : '—'}</td>
                            <td className="text-fg-muted">{entry.actor || '—'}</td>
                            <td className="text-fg-muted">{reasonLabel(entry.reason_code, copy)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
