import React from 'react';
import { motion } from 'motion/react';
import { X, type LucideIcon } from 'lucide-react';

interface ResultStatusModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  closeTitle: string;
  icon: LucideIcon;
  iconClassName?: string;
  headerClassName?: string;
  panelClassName?: string;
  bodyClassName?: string;
  closeDisabled?: boolean;
  onBackdropClick?: () => void;
  children: React.ReactNode;
}

const ResultStatusModal: React.FC<ResultStatusModalProps> = ({
  open,
  onClose,
  title,
  closeTitle,
  icon: Icon,
  iconClassName = 'bg-slate-900 text-white',
  headerClassName = 'border-b border-black/5 bg-black/[0.01]',
  panelClassName = 'w-full max-w-md rounded-2xl shadow-2xl border border-black/5 overflow-hidden bg-white',
  bodyClassName = 'p-5 space-y-4',
  closeDisabled = false,
  onBackdropClick,
  children,
}) => {
  if (!open) return null;

  const handleBackdropClick = () => {
    if (closeDisabled) return;
    (onBackdropClick || onClose)();
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[60] flex items-center justify-center p-4" onClick={handleBackdropClick}>
      <motion.div
        initial={{ scale: 0.94, opacity: 0, y: 14 }}
        animate={{ scale: 1, opacity: 1, y: 0 }}
        className={panelClassName}
        onClick={(event) => event.stopPropagation()}
      >
        <div className={`p-5 flex items-center justify-between ${headerClassName}`}>
          <div className="flex items-center gap-3 min-w-0">
            <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${iconClassName}`}>
              <Icon size={18} />
            </div>
            <h3 className="text-sm font-semibold truncate">{title}</h3>
          </div>
          {!closeDisabled && (
            <button onClick={onClose} title={closeTitle} className="text-black/30 hover:text-black">
              <X size={18} />
            </button>
          )}
        </div>
        <div className={bodyClassName}>{children}</div>
      </motion.div>
    </div>
  );
};

export default ResultStatusModal;