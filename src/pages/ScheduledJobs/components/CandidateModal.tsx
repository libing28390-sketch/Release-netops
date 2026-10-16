import React, { useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion } from 'motion/react';
import { X, Target } from 'lucide-react';
import { useEscapeClose } from '../../../hooks/useEscapeClose';

interface CandidateModalProps {
  isOpen: boolean;
  onClose: () => void;
  candidateList: Array<{ ip: string; hostname: string; tags: any[]; selected: boolean }>;
  toggleCandidateSelected: (idx: number) => void;
  toggleAllCandidates: () => void;
  confirmAddCandidates: () => void;
  language: string;
}

export const CandidateModal: React.FC<CandidateModalProps> = ({
  isOpen,
  onClose,
  candidateList,
  toggleCandidateSelected,
  toggleAllCandidates,
  confirmAddCandidates,
  language,
}) => {
  useEscapeClose(isOpen, onClose);

  const zh = language === 'zh';
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const selectAllRef = useRef<HTMLInputElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const selectedCount = candidateList.filter(candidate => candidate.selected).length;
  const allSelected = candidateList.length > 0 && selectedCount === candidateList.length;
  const partiallySelected = selectedCount > 0 && !allSelected;

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = partiallySelected;
    }
  }, [isOpen, partiallySelected]);

  useEffect(() => {
    if (!isOpen) return;

    const activeElement = document.activeElement;
    returnFocusRef.current = activeElement instanceof HTMLElement && activeElement !== document.body
      ? activeElement
      : null;

    const focusFrame = window.requestAnimationFrame(() => {
      const firstControl = dialogRef.current?.querySelector<HTMLElement>('[data-autofocus="true"]');
      (firstControl ?? dialogRef.current)?.focus();
    });

    const trapTabNavigation = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;

      const dialog = dialogRef.current;
      if (!dialog) return;

      const focusableElements = Array.from(dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), a[href], select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ));

      if (focusableElements.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      const focusIsOutsideDialog = !dialog.contains(document.activeElement);

      if (event.shiftKey && (document.activeElement === firstElement || focusIsOutsideDialog)) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && (document.activeElement === lastElement || focusIsOutsideDialog)) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    document.addEventListener('keydown', trapTabNavigation);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener('keydown', trapTabNavigation);
    };
  }, [isOpen]);

  const restoreFocus = () => {
    returnFocusRef.current?.focus();
    returnFocusRef.current = null;
  };

  return createPortal(
    <AnimatePresence onExitComplete={restoreFocus}>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[100] flex items-center justify-center p-2 sm:p-4"
        >
          <div aria-hidden="true" className="fixed inset-0 bg-black/45" onClick={onClose} />
          <motion.div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            tabIndex={-1}
            initial={{ opacity: 0, scale: 0.97, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: 10 }}
            className="relative z-10 flex max-h-[min(82dvh,44rem)] min-h-0 w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-slate-100 bg-white shadow-2xl"
            onClick={event => event.stopPropagation()}
          >
            <div className="flex shrink-0 items-center justify-between gap-3 border-b border-white/10 bg-gradient-to-r from-slate-900 to-[#0f172a] px-4 py-3 text-white sm:px-5">
              <div className="flex min-w-0 items-center gap-2.5">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-cyan-400/20 bg-cyan-500/20 text-cyan-400">
                  <Target size={16} aria-hidden="true" />
                </div>
                <div className="min-w-0">
                  <h3 id={titleId} className="text-sm font-bold">
                    {zh ? '选择匹配的目标设备' : 'Select Matched Target Devices'}
                  </h3>
                  <p className="text-[10px] text-slate-400">
                    {zh ? `共检索到 ${candidateList.length} 台候选目标` : `Found ${candidateList.length} candidate device(s)`}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label={zh ? '关闭候选设备选择' : 'Close candidate selection'}
                className="shrink-0 rounded-lg p-2 text-slate-400 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
              >
                <X size={16} aria-hidden="true" />
              </button>
            </div>

            <div className="flex shrink-0 items-center justify-between gap-2 border-b border-slate-200/80 bg-slate-50 px-4 py-2.5 text-xs text-slate-600 sm:px-5">
              <label className="flex cursor-pointer select-none items-center gap-2 font-bold hover:text-slate-900">
                <input
                  ref={selectAllRef}
                  type="checkbox"
                  checked={allSelected}
                  aria-checked={partiallySelected ? 'mixed' : allSelected}
                  disabled={candidateList.length === 0}
                  onChange={toggleAllCandidates}
                  className="h-4 w-4 shrink-0 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500 disabled:cursor-not-allowed disabled:opacity-50"
                />
                <span>{zh ? (allSelected ? '取消全选' : '全选') : (allSelected ? 'Clear selection' : 'Select all')}</span>
              </label>
              <span className="shrink-0 rounded border border-slate-200 bg-white px-2 py-1 font-mono text-[10px] font-bold text-slate-700 shadow-2xs sm:text-[11px]">
                {zh ? `已勾选 ${selectedCount} / ${candidateList.length} 台` : `${selectedCount} / ${candidateList.length} selected`}
              </span>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3 custom-scrollbar sm:p-4">
              {candidateList.length === 0 ? (
                <div role="status" className="flex min-h-24 items-center justify-center px-4 text-center text-sm text-slate-500">
                  {zh ? '没有找到可添加的候选目标' : 'No candidate targets found'}
                </div>
              ) : (
                <div className="space-y-1.5">
                  {candidateList.map((candidate, idx) => (
                    <label
                      key={candidate.ip}
                      className={`flex cursor-pointer items-start gap-2.5 rounded-xl border px-3 py-2 transition-colors focus-within:ring-2 focus-within:ring-cyan-500/50 ${
                        candidate.selected
                          ? 'border-cyan-400 bg-cyan-50/70 text-slate-900'
                          : 'border-slate-200/80 bg-white text-slate-600 hover:border-slate-300'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={candidate.selected}
                        onChange={() => toggleCandidateSelected(idx)}
                        aria-label={zh
                          ? `选择 ${candidate.ip}${candidate.hostname ? `，${candidate.hostname}` : ''}`
                          : `Select ${candidate.ip}${candidate.hostname ? `, ${candidate.hostname}` : ''}`}
                        data-autofocus={idx === 0 ? 'true' : undefined}
                        className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500"
                      />
                      <span className="flex min-w-0 flex-1 flex-col gap-1 sm:flex-row sm:items-center sm:gap-2">
                        <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-0.5">
                          <span className="min-w-0 break-all font-mono text-[11px] font-semibold text-[#0f172a] sm:shrink-0 sm:text-xs">
                            {candidate.ip}
                          </span>
                          {candidate.hostname ? (
                            <span className="min-w-0 flex-1 truncate text-xs text-slate-600">
                              {candidate.hostname}
                            </span>
                          ) : (
                            <span className="min-w-0 flex-1 text-[11px] italic text-amber-600/90">
                              {zh ? '手动输入目标 (非资产表)' : 'Manual Target'}
                            </span>
                          )}
                        </span>
                        {candidate.tags.length > 0 && (
                          <span className="flex max-w-40 shrink-0 flex-wrap items-center gap-1">
                            {candidate.tags.slice(0, 2).map((tag, tagIndex) => (
                              <span
                                key={tag.id ?? `${tag.label}-${tagIndex}`}
                                className="inline-flex max-w-20 items-center gap-1 rounded border border-black/5 bg-white px-1.5 py-0.5 text-[9px] font-medium"
                              >
                                <span
                                  className="h-1.5 w-1.5 shrink-0 rounded-full"
                                  style={{ backgroundColor: tag.color || '#94a3b8' }}
                                  aria-hidden="true"
                                />
                                <span className="truncate">{zh ? (tag.label_zh || tag.label) : tag.label}</span>
                              </span>
                            ))}
                            {candidate.tags.length > 2 && (
                              <span className="text-[9px] text-slate-400">+{candidate.tags.length - 2}</span>
                            )}
                          </span>
                        )}
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </div>

            <div className="flex shrink-0 items-center justify-end gap-2 border-t border-slate-100 bg-slate-50/80 px-4 py-3 sm:px-5">
              <button
                type="button"
                onClick={onClose}
                className="rounded-xl border border-slate-200 px-3.5 py-2 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 sm:px-4"
              >
                {zh ? '取消' : 'Cancel'}
              </button>
              <button
                type="button"
                onClick={confirmAddCandidates}
                disabled={selectedCount === 0}
                className="rounded-xl bg-[#164e63] px-4 py-2 text-xs font-bold text-white shadow-md shadow-cyan-950/10 transition-colors hover:bg-[#0891b2] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-40 sm:px-5"
              >
                {zh ? `确认添加 (${selectedCount}台)` : `Add Selected (${selectedCount})`}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
};
