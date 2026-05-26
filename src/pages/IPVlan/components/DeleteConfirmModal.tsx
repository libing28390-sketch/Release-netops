import React from 'react';
import { AlertTriangle } from 'lucide-react';

interface DeleteConfirmModalProps {
  language: string;
  confirmDelete: {
    type: 'subnet' | 'ip' | 'batch-subnet';
    id: string;
    label: string;
  };
  onClose: () => void;
  onConfirm: () => void;
}

const DeleteConfirmModal: React.FC<DeleteConfirmModalProps> = ({
  language,
  confirmDelete,
  onClose,
  onConfirm,
}) => {
  return (
    <div
      className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[80]"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 text-red-600 mb-3">
          <AlertTriangle className="w-6 h-6 flex-shrink-0" />
          <h3 className="text-base font-bold text-[#00172D]">
            {language === 'zh' ? '确认删除' : 'Confirm Delete'}
          </h3>
        </div>
        <p className="text-sm text-black/60 mb-5">
          {confirmDelete.type === 'batch-subnet'
            ? language === 'zh'
              ? `确定要删除选中的 ${confirmDelete.label} 个子网吗？此操作无法撤销。`
              : `Are you sure you want to delete the selected ${confirmDelete.label} subnet(s)? This cannot be undone.`
            : confirmDelete.type === 'subnet'
            ? language === 'zh'
              ? `确定要删除子网 "${confirmDelete.label}" 吗？此操作无法撤销。`
              : `Are you sure you want to delete subnet "${confirmDelete.label}"? This cannot be undone.`
            : language === 'zh'
            ? `确定要删除 IP 地址 "${confirmDelete.label}" 的分配记录吗？`
            : `Are you sure you want to delete the allocation record for IP "${confirmDelete.label}"?`}
        </p>
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 border border-black/8 rounded-xl text-xs font-semibold text-black/50 hover:bg-black/5 transition-all"
          >
            {language === 'zh' ? '取消' : 'Cancel'}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="px-4 py-2 rounded-xl bg-red-500 hover:bg-red-600 text-white text-xs font-bold transition-all"
          >
            {language === 'zh' ? '确认删除' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default DeleteConfirmModal;
