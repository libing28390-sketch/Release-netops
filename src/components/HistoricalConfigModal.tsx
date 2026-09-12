import React from 'react';
import { RotateCcw, XCircle } from 'lucide-react';
import { motion } from 'motion/react';
import type { ConfigVersion, Device } from '../types';

interface HistoricalConfigModalProps {
  open: boolean;
  language: string;
  t: (key: string) => string;
  selectedDevice: Device | null;
  viewingConfig: ConfigVersion | null;
  onClose: () => void;
  onRollback: () => void;
}

const HistoricalConfigModal: React.FC<HistoricalConfigModalProps> = ({
  open,
  language,
  t,
  selectedDevice,
  viewingConfig,
  onClose,
  onRollback,
}) => {
  if (!open || !viewingConfig || !selectedDevice) return null;

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="bg-white rounded-2xl w-full max-w-2xl shadow-2xl overflow-hidden"
      >
        <div className="p-6 border-b border-black/5 flex justify-between items-center bg-black/5">
          <div>
            <h3 className="text-lg font-medium">{t('viewConfig')}: {viewingConfig.id}</h3>
            <p className="text-xs text-black/40">{viewingConfig.timestamp} • {viewingConfig.author}</p>
          </div>
          <button onClick={onClose} title={language === 'zh' ? '关闭配置窗口' : 'Close configuration dialog'} className="text-black/40 hover:text-black">
            <XCircle size={24} />
          </button>
        </div>

        <div className="p-6 space-y-4">
          <div className="grid grid-cols-2 gap-4 text-[10px] font-bold uppercase text-black/40">
            <div>
              <p>{t('description')}</p>
              <p className="text-black mt-1 normal-case font-medium">{viewingConfig.description}</p>
            </div>
            <div>
              <p>{t('author')}</p>
              <p className="text-black mt-1 normal-case font-medium">{viewingConfig.author}</p>
            </div>
          </div>

          <div className="space-y-2">
            <p className="text-[10px] font-bold uppercase text-black/40">{t('configContent')}</p>
            <div className="bg-black/[0.02] border border-black/5 rounded-xl p-4 max-h-[400px] overflow-auto">
              <pre className="text-xs font-mono text-black/60 whitespace-pre-wrap">
                {viewingConfig.content}
              </pre>
            </div>
          </div>
        </div>

        <div className="p-6 bg-white border-t border-black/5 flex justify-end gap-4">
          <button onClick={onClose} className="px-6 py-2 text-sm font-medium text-black/60 hover:text-black">
            {t('cancel')}
          </button>
          <button onClick={onRollback} className="px-8 py-2 bg-orange-600 text-white rounded-xl text-sm font-medium hover:bg-orange-700 transition-all shadow-lg shadow-orange-600/20 flex items-center gap-2">
            <RotateCcw size={16} />
            {t('rollbackTo')}
          </button>
        </div>
      </motion.div>
    </div>
  );
};

export default HistoricalConfigModal;