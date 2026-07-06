import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Asset } from '../types';

interface BatchTagModalProps {
  isOpen: boolean;
  onClose: () => void;
  selectedCount: number;
  batchTagValue: string;
  setBatchTagValue: (val: string) => void;
  batchTag: () => void;
  language: string;
}

export const BatchTagModal: React.FC<BatchTagModalProps> = ({
  isOpen,
  onClose,
  selectedCount,
  batchTagValue,
  setBatchTagValue,
  batchTag,
  language,
}) => {
  const zh = language === 'zh';

  return (
    <AnimatePresence>
      {isOpen && (
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
            <h3 className="text-sm font-bold text-black/80 mb-3">{zh ? '批量添加标签' : 'Assign Tag to Selected'}</h3>
            <p className="text-[10px] text-black/25 mb-3">{selectedCount} {zh ? '个资产将被标记' : 'assets selected'}</p>
            <input
              value={batchTagValue}
              onChange={e => setBatchTagValue(e.target.value)}
              placeholder={zh ? '输入标签内容...' : 'Enter tag value...'}
              className="w-full bg-white border border-black/8 rounded-lg px-3 py-2 text-xs text-black/65 placeholder:text-black/15 focus:outline-none focus:border-[#00bceb]/25 mb-4"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={onClose}
                className="px-3 py-1.5 rounded-lg bg-black/[0.01] border border-black/5 text-black/40 text-xs"
              >
                {zh ? '取消' : 'Cancel'}
              </button>
              <button
                onClick={batchTag}
                disabled={!batchTagValue.trim()}
                className="px-4 py-1.5 rounded-lg bg-[#00bceb] text-white text-xs font-bold hover:bg-[#00a5d0] disabled:opacity-50"
              >
                {zh ? '应用' : 'Apply'}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};
