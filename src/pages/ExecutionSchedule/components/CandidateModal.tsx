import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { X, Target } from 'lucide-react';

interface CandidateItem {
  ip: string;
  hostname: string;
  tags: { id: string; label: string; label_zh: string; color: string }[];
  selected: boolean;
}

interface CandidateModalProps {
  zh: boolean;
  open: boolean;
  candidates: CandidateItem[];
  onClose: () => void;
  onToggle: (idx: number) => void;
  onToggleAll: () => void;
  onConfirm: () => void;
}

const CandidateModal: React.FC<CandidateModalProps> = ({
  zh, open, candidates, onClose, onToggle, onToggleAll, onConfirm,
}) => {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          className="fixed inset-0 z-[70] flex items-center justify-center p-4"
        >
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 15 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 15 }}
            className="relative w-full max-w-xl bg-white rounded-2xl shadow-2xl overflow-hidden border border-slate-100 flex flex-col z-10 max-h-[80vh]"
            onClick={e => e.stopPropagation()}
          >
            <div className="px-6 py-4 bg-gradient-to-r from-slate-900 to-[#0f172a] text-white flex items-center justify-between border-b border-white/10">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-xl bg-cyan-500/20 flex items-center justify-center border border-cyan-400/20 text-cyan-400">
                  <Target size={16} />
                </div>
                <div>
                  <h3 className="text-sm font-bold">{zh ? '选择匹配的目标设备' : 'Select Matched Target Devices'}</h3>
                  <p className="text-[10px] text-slate-400">{zh ? `共检索到 ${candidates.length} 台候选目标` : `Found ${candidates.length} candidate device(s)`}</p>
                </div>
              </div>
              <button type="button" onClick={onClose} className="text-slate-400 hover:text-white transition-colors p-1">
                <X size={16} />
              </button>
            </div>

            <div className="px-6 py-3 bg-slate-50 border-b border-slate-200/80 flex items-center justify-between text-xs text-slate-600">
              <label className="flex items-center gap-2 font-bold cursor-pointer hover:text-slate-900 select-none">
                <input
                  type="checkbox"
                  checked={candidates.length > 0 && candidates.every(c => c.selected)}
                  onChange={onToggleAll}
                  className="w-4 h-4 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500"
                />
                <span>{zh ? '全选 / 全不选' : 'Select All'}</span>
              </label>
              <span className="font-mono text-[11px] bg-white px-2 py-0.5 rounded border border-slate-200 font-bold text-slate-700 shadow-2xs">
                {zh ? `已勾选 ${candidates.filter(c => c.selected).length} / ${candidates.length} 台` : `${candidates.filter(c => c.selected).length} / ${candidates.length} selected`}
              </span>
            </div>

            <div className="flex-1 overflow-y-auto p-6 space-y-2 custom-scrollbar max-h-[50vh]">
              {candidates.map((cand, idx) => (
                <div
                  key={cand.ip}
                  onClick={() => onToggle(idx)}
                  className={`flex items-center gap-3 px-4 py-3 rounded-xl border transition-all cursor-pointer ${
                    cand.selected
                      ? 'border-cyan-400 bg-cyan-50/60 shadow-2xs text-slate-900 font-bold'
                      : 'border-slate-200/80 bg-white text-slate-500 hover:border-slate-300 opacity-70'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={cand.selected}
                    onChange={() => {}} // parent div onClick handles toggle
                    className="w-4 h-4 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500 pointer-events-none shrink-0"
                  />
                  <span className="font-mono text-xs text-[#0f172a] shrink-0 w-32">{cand.ip}</span>
                  {cand.hostname ? (
                    <span className="text-xs text-slate-600 truncate flex-1">{cand.hostname}</span>
                  ) : (
                    <span className="text-xs text-amber-600/80 italic flex-1 font-normal">{zh ? '手动输入目标 (非资产表)' : 'Manual Target'}</span>
                  )}
                  {cand.tags.length > 0 && (
                    <div className="flex items-center gap-1 shrink-0 max-w-[150px] overflow-hidden">
                      {cand.tags.slice(0, 2).map(t => (
                        <span key={t.id} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-medium bg-white border border-black/5">
                          <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: t.color || '#94a3b8' }} />
                          <span className="truncate">{zh ? (t.label_zh || t.label) : t.label}</span>
                        </span>
                      ))}
                      {cand.tags.length > 2 && <span className="text-[9px] text-slate-400">+{cand.tags.length - 2}</span>}
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="px-6 py-4 bg-slate-50/80 border-t border-slate-100 flex items-center justify-end gap-2.5">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 rounded-xl border border-slate-200 font-semibold text-xs text-slate-600 hover:bg-slate-100 transition-all"
              >
                {zh ? '取消' : 'Cancel'}
              </button>
              <button
                type="button"
                onClick={onConfirm}
                disabled={candidates.filter(c => c.selected).length === 0}
                className="px-5 py-2 rounded-xl bg-[#164e63] text-white font-bold text-xs hover:bg-[#0891b2] transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-md shadow-cyan-950/10"
              >
                {zh ? `确认添加 (${candidates.filter(c => c.selected).length}台)` : `Add Selected (${candidates.filter(c => c.selected).length})`}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};

export default CandidateModal;
