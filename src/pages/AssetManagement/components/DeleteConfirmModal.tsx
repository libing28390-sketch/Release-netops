import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { AlertTriangle, Trash2 } from 'lucide-react';
import { Asset } from '../types';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import { useFocusTrap } from '../../../hooks/useFocusTrap';

interface DeleteConfirmModalProps {
  isOpen: boolean;
  onClose: () => void;
  deleteTarget: Asset | null;
  handleDelete: () => void;
  error?: string | null;
  language: string;
}

export const DeleteConfirmModal: React.FC<DeleteConfirmModalProps> = ({
  isOpen,
  onClose,
  deleteTarget,
  handleDelete,
  error,
  language,
}) => {
  const dialogRef = React.useRef<HTMLDivElement>(null);
  const dialogTitleId = React.useId();
  const dialogDescriptionId = React.useId();
  const dialogOpen = isOpen && Boolean(deleteTarget);
  useEscapeClose(dialogOpen, onClose);
  useFocusTrap(dialogRef, dialogOpen, '[data-delete-cancel]');
  const zh = language === 'zh';

  return (
    <AnimatePresence>
      {isOpen && deleteTarget && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            ref={dialogRef}
            role="alertdialog"
            aria-modal="true"
            aria-labelledby={dialogTitleId}
            aria-describedby={dialogDescriptionId}
            className="nx-form-dialog-surface w-full max-w-sm rounded-xl border p-5 shadow-2xl"
            onClick={e => e.stopPropagation()}
            initial={{ scale: 0.96, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.96, opacity: 0 }}
          >
            <div className="nx-dialog-header -mx-5 -mt-5 mb-4 flex items-center gap-3 border-b px-5 py-4">
              <div className="h-9 w-9 rounded-full bg-red-50 flex items-center justify-center">
                <Trash2 size={16} className="text-red-500" />
              </div>
              <div>
                <h3 id={dialogTitleId} className="text-sm font-bold">{zh ? '确认删除' : 'Confirm Delete'}</h3>
                <p className="mt-0.5 text-xs text-[var(--ui-fg-muted)]">{deleteTarget.hostname || deleteTarget.asset_tag}</p>
              </div>
            </div>
            <p id={dialogDescriptionId} className="mb-4 text-sm text-[var(--ui-fg-muted)]">{zh ? '删除后不可恢复，是否继续？' : 'This action cannot be undone. Continue?'}</p>
            {error && (
              <div role="alert" className="mb-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11px] leading-4 text-red-700">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}
            <div className="nx-form-dialog-footer -mx-5 -mb-5 flex justify-end gap-2 px-5 py-3">
              <button
                type="button"
                onClick={onClose}
                data-delete-cancel
                className="nx-dialog-action-secondary rounded-lg border px-3 py-1.5 text-xs"
              >
                {zh ? '取消' : 'Cancel'}
              </button>
              <button
                type="button"
                onClick={handleDelete}
                className="nx-dialog-action-danger rounded-lg border px-3 py-1.5 text-xs font-bold"
              >
                {zh ? '删除' : 'Delete'}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};
