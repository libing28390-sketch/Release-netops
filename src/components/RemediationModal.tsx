import React from 'react';
import { Play, ShieldCheck, XCircle } from 'lucide-react';
import { motion } from 'motion/react';
import type { Device } from '../types';

interface RemediationModalProps {
  open: boolean;
  language: string;
  t: (key: string) => string;
  device: Device | null;
  onClose: () => void;
  onConfirm: () => void;
}

const RemediationModal: React.FC<RemediationModalProps> = ({
  open,
  language,
  t,
  device,
  onClose,
  onConfirm,
}) => {
  if (!open || !device) return null;

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="bg-white rounded-2xl w-full max-w-md shadow-2xl overflow-hidden"
      >
        <div className="p-6 border-b border-black/5 flex justify-between items-center bg-red-50">
          <div className="flex items-center gap-3">
            <ShieldCheck className="text-red-600" size={24} />
            <div>
              <h3 className="text-lg font-medium text-red-900">{t('autoRemediation')}</h3>
              <p className="text-xs text-red-700/70">{device.hostname}</p>
            </div>
          </div>
          <button onClick={onClose} title={language === 'zh' ? '关闭修复确认窗口' : 'Close remediation dialog'} className="text-red-900/40 hover:text-red-900">
            <XCircle size={24} />
          </button>
        </div>

        <div className="p-6 space-y-4">
          <p className="text-sm text-black/60">{t('remediationDesc')}</p>
          <div className="bg-black/[0.02] border border-black/5 rounded-xl p-4">
            <h4 className="text-[10px] font-bold uppercase tracking-widest text-black/40 mb-2">{t('proposedActions')}</h4>
            <ul className="text-xs font-mono text-black/60 space-y-2 list-disc list-inside">
              <li>Apply Golden Config template: <span className="text-black font-semibold">base_security_v2</span></li>
              <li>Update NTP server settings</li>
              <li>Disable insecure protocols (Telnet, HTTP)</li>
            </ul>
          </div>
        </div>

        <div className="p-6 bg-white border-t border-black/5 flex justify-end gap-4">
          <button onClick={onClose} className="px-6 py-2 text-sm font-medium text-black/60 hover:text-black">
            {t('cancel')}
          </button>
          <button onClick={onConfirm} className="px-8 py-2 bg-red-600 text-white rounded-xl text-sm font-medium hover:bg-red-700 transition-all shadow-lg shadow-red-600/20 flex items-center gap-2">
            <Play size={16} />
            {t('startRemediation')}
          </button>
        </div>
      </motion.div>
    </div>
  );
};

export default RemediationModal;