import React from 'react';
import { AlertTriangle, X } from 'lucide-react';
import { motion } from 'motion/react';

interface DeleteConfirmModalProps {
  open: boolean;
  language: string;
  isDeletingSelected: boolean;
  selectedDeviceCount: number;
  onClose: () => void;
  onConfirm: () => void;
}

const DeleteConfirmModal: React.FC<DeleteConfirmModalProps> = ({
  open,
  language,
  isDeletingSelected,
  selectedDeviceCount,
  onClose,
  onConfirm,
}) => {
  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="bg-white rounded-2xl w-full max-w-md shadow-2xl overflow-hidden"
      >
        <div className="p-6 border-b border-black/5 flex justify-between items-center bg-red-50">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-red-100 text-red-600 rounded-lg">
              <AlertTriangle size={20} />
            </div>
            <h2 className="text-lg font-semibold text-red-900">
              {isDeletingSelected ? 'Delete Selected Devices' : 'Delete Device'}
            </h2>
          </div>
          <button onClick={onClose} title={language === 'zh' ? '关闭删除确认窗口' : 'Close delete confirmation'} className="text-red-900/40 hover:text-red-900">
            <X size={20} />
          </button>
        </div>

        <div className="p-6">
          <p className="text-sm text-black/60">
            {isDeletingSelected
              ? `Are you sure you want to delete ${selectedDeviceCount} selected devices? This action cannot be undone.`
              : 'Are you sure you want to delete this device? This action cannot be undone.'}
          </p>
        </div>

        <div className="p-6 border-t border-black/5 bg-black/[0.02] flex justify-end gap-3">
          <button onClick={onClose} className="px-6 py-2 text-sm font-medium text-black/60 hover:text-black">
            Cancel
          </button>
          <button onClick={onConfirm} className="px-8 py-2 bg-red-600 text-white rounded-xl text-sm font-medium hover:bg-red-700 transition-all shadow-lg shadow-red-600/20">
            Delete
          </button>
        </div>
      </motion.div>
    </div>
  );
};

export default DeleteConfirmModal;