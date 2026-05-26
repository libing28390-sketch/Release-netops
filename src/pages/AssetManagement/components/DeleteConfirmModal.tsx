import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Trash2, X } from 'lucide-react';
import { Asset } from '../types';

interface DeleteConfirmModalProps {
  isOpen: boolean;
  onClose: () => void;
  deleteTarget: Asset | null;
  handleDelete: () => void;
  language: string;
}

export const DeleteConfirmModal: React.FC<DeleteConfirmModalProps> = ({
  isOpen,
  onClose,
  deleteTarget,
  handleDelete,
  language,
}) => {
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
            className="bg-white rounded-xl w-full max-w-sm p-5 shadow-2xl border border-black/5"
            onClick={e => e.stopPropagation()}
            initial={{ scale: 0.96, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.96, opacity: 0 }}
          >
            <div className="flex items-center gap-3 mb-3">
              <div className="h-9 w-9 rounded-full bg-red-50 flex items-center justify-center">
                <Trash2 size={16} className="text-red-500" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-black/80">{zh ? '确认删除' : 'Confirm Delete'}</h3>
                <p className="text-[10px] text-black/25 mt-0.5">{deleteTarget.hostname || deleteTarget.asset_tag}</p>
              </div>
            </div>
            <p className="text-[11px] text-black/35 mb-4">{zh ? '删除后不可恢复，是否继续？' : 'This action cannot be undone. Continue?'}</p>
            <div className="flex justify-end gap-2">
              <button
                onClick={onClose}
                className="px-3 py-1.5 rounded-lg bg-black/[0.01] border border-black/5 text-black/40 text-xs hover:bg-black/[0.02]"
              >
                {zh ? '取消' : 'Cancel'}
              </button>
              <button
                onClick={handleDelete}
                className="px-3 py-1.5 rounded-lg bg-red-600 text-white text-xs font-bold hover:bg-red-700"
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
