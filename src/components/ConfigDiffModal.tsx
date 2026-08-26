import React from 'react';
import { XCircle } from 'lucide-react';
import { motion } from 'motion/react';
import type { Device } from '../types';

interface ConfigDiffModalProps {
  open: boolean;
  language: string;
  t: (key: string) => string;
  selectedDevice: Device | null;
  currentDiff: {
    before: string;
    after: string;
  };
  onClose: () => void;
  onCommit: () => void;
}

const ConfigDiffModal: React.FC<ConfigDiffModalProps> = ({
  open,
  language,
  t,
  selectedDevice,
  currentDiff,
  onClose,
  onCommit,
}) => {
  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="bg-white rounded-2xl w-full max-w-4xl shadow-2xl overflow-hidden"
      >
        <div className="p-6 border-b border-black/5 flex justify-between items-center bg-black/5">
          <div>
            <h3 className="text-lg font-medium">{t('configChangeReview')}</h3>
            <p className="text-xs text-black/40">{t('reviewDiff')} {selectedDevice?.hostname}</p>
          </div>
          <button onClick={onClose} title={language === 'zh' ? '关闭差异窗口' : 'Close diff dialog'} className="text-black/40 hover:text-black">
            <XCircle size={24} />
          </button>
        </div>

        <div className="grid grid-cols-2 gap-px bg-black/10 h-[400px]">
          <div className="bg-white p-6 overflow-auto border-r border-black/5">
            <h4 className="text-[10px] font-bold uppercase tracking-widest text-black/30 mb-4">{t('currentConfig')}</h4>
            <pre className="text-xs font-mono text-red-600 bg-red-50 p-4 rounded-lg whitespace-pre-wrap">
              {currentDiff.before}
            </pre>
          </div>
          <div className="bg-white p-6 overflow-auto">
            <h4 className="text-[10px] font-bold uppercase tracking-widest text-black/30 mb-4">{t('proposedChange')}</h4>
            <pre className="text-xs font-mono text-emerald-600 bg-emerald-50 p-4 rounded-lg whitespace-pre-wrap">
              {currentDiff.after}
            </pre>
          </div>
        </div>

        <div className="p-6 bg-white border-t border-black/5 flex justify-end gap-4">
          <button onClick={onClose} className="px-6 py-2 text-sm font-medium text-black/60 hover:text-black">
            {t('cancel')}
          </button>
          <button onClick={onCommit} className="px-8 py-2 bg-black text-white rounded-xl text-sm font-medium hover:bg-black/80 transition-all shadow-lg shadow-black/20">
            {t('commitDeploy')}
          </button>
        </div>
      </motion.div>
    </div>
  );
};

export default ConfigDiffModal;