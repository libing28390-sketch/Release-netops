import React from 'react';
import { FileText, Upload, XCircle } from 'lucide-react';
import { motion } from 'motion/react';

interface ImportInventoryModalProps {
  open: boolean;
  language: string;
  t: (key: string) => string;
  onClose: () => void;
  onImport: () => void;
}

const ImportInventoryModal: React.FC<ImportInventoryModalProps> = ({
  open,
  language,
  t,
  onClose,
  onImport,
}) => {
  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="bg-white w-full max-w-md rounded-3xl shadow-2xl overflow-hidden"
      >
        <div className="p-8 space-y-6">
          <div className="flex justify-between items-center">
            <h3 className="text-xl font-medium">{t('importInventory')}</h3>
            <button onClick={onClose} title={language === 'zh' ? '关闭导入窗口' : 'Close import dialog'} className="text-black/40 hover:text-black">
              <XCircle size={24} />
            </button>
          </div>

          <div className="space-y-4">
            <p className="text-sm text-black/40">{t('importDesc')}</p>

            <div className="border-2 border-dashed border-black/10 rounded-2xl p-10 flex flex-col items-center justify-center gap-4 hover:border-black/20 transition-all cursor-pointer bg-black/[0.01]">
              <div className="w-12 h-12 bg-black/5 rounded-full flex items-center justify-center text-black/40">
                <Upload size={24} />
              </div>
              <div className="text-center">
                <p className="text-sm font-medium">{t('clickToUpload')}</p>
                <p className="text-xs text-black/30 mt-1">JSON, CSV (max. 10MB)</p>
              </div>
            </div>

            <div className="flex items-center gap-3 p-4 bg-blue-50 rounded-xl border border-blue-100">
              <FileText className="text-blue-500" size={20} />
              <div className="flex-1">
                <p className="text-xs font-medium text-blue-900">{t('downloadTemplate')}</p>
                <p className="text-[10px] text-blue-700">{t('getStandardCsv')}</p>
              </div>
              <button className="text-[10px] font-bold uppercase text-blue-600 hover:underline">{t('export')}</button>
            </div>
          </div>

          <div className="flex gap-3 pt-4">
            <button onClick={onClose} className="flex-1 px-4 py-3 rounded-xl border border-black/10 text-sm font-medium hover:bg-black/5 transition-all">
              {t('cancel')}
            </button>
            <button onClick={onImport} className="flex-1 px-4 py-3 rounded-xl bg-black text-white text-sm font-medium hover:bg-black/80 transition-all">
              {t('startImport')}
            </button>
          </div>
        </div>
      </motion.div>
    </div>
  );
};

export default ImportInventoryModal;