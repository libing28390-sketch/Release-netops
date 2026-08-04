import React from 'react';
import { Bell, CheckCircle, XCircle, X } from 'lucide-react';
import { motion } from 'motion/react';

export interface ToastState {
  message: string;
  type: 'success' | 'error' | 'info';
}

interface ToastNotificationProps {
  toast: ToastState | null;
  onClose: () => void;
}

const ToastNotification: React.FC<ToastNotificationProps> = ({ toast, onClose }) => {
  if (!toast) return null;

  return (
    <motion.div
      initial={{ y: 50, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      exit={{ y: 50, opacity: 0 }}
      className={`fixed bottom-14 left-1/2 z-[100] max-w-[calc(100vw-2rem)] -translate-x-1/2 px-6 py-3 rounded-2xl shadow-2xl flex items-center gap-3 border ${
        toast.type === 'success' ? 'bg-emerald-600 border-emerald-500 text-white' :
        toast.type === 'error' ? 'bg-red-600 border-red-500 text-white' :
        'bg-black border-black/10 text-white'
      }`}
    >
      {toast.type === 'success' && <CheckCircle size={18} />}
      {toast.type === 'error' && <XCircle size={18} />}
      {toast.type === 'info' && <Bell size={18} />}
      <span className="text-sm font-medium">{toast.message}</span>
      <button 
        onClick={onClose}
        className="ml-2 p-1 rounded-full hover:bg-white/20 transition-colors"
      >
        <X size={14} />
      </button>
    </motion.div>
  );
};

export default ToastNotification;
