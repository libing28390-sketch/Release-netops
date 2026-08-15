import React from 'react';
import { Copy, X } from 'lucide-react';

type CommandPhase = 'pre_check' | 'execute' | 'post_check' | 'rollback';

interface CommandPreviewModalProps {
  open: boolean;
  language: string;
  scenarioName?: string;
  scenarioNameZh?: string;
  platform: string;
  preview: Partial<Record<CommandPhase, string[]>> | null;
  onClose: () => void;
  onCopyAll: () => void;
}

const phases: CommandPhase[] = ['pre_check', 'execute', 'post_check', 'rollback'];

const phaseColor: Record<CommandPhase, string> = {
  pre_check: 'text-sky-400',
  execute: 'text-[#00bceb]',
  post_check: 'text-emerald-400',
  rollback: 'text-amber-400',
};

const CommandPreviewModal: React.FC<CommandPreviewModalProps> = ({
  open,
  language,
  scenarioName,
  scenarioNameZh,
  platform,
  preview,
  onClose,
  onCopyAll,
}) => {
  if (!open || !preview) return null;

  return (
    <div
      className="fixed inset-0 bg-black/55 backdrop-blur-sm flex items-center justify-center z-[80] p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl max-h-[80vh] rounded-2xl border border-white/10 shadow-2xl overflow-hidden flex flex-col bg-[#0f1117]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="px-5 py-4 border-b border-white/10 flex items-center justify-between flex-shrink-0">
          <div className="flex items-center gap-3">
            <p className="text-sm font-bold text-white/90">
              {scenarioName ? (language === 'zh' ? (scenarioNameZh || scenarioName) : scenarioName) : 'Command Preview'}
            </p>
            <span className="text-[10px] font-mono text-white/35">{platform}</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onCopyAll}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/8 text-white/60 hover:bg-white/15 text-xs font-semibold transition-all"
            >
              <Copy size={12} /> {language === 'zh' ? '复制全部' : 'Copy All'}
            </button>
            <button onClick={onClose} title={language === 'zh' ? '关闭' : 'Close'} className="text-white/40 hover:text-white/80 transition-colors">
              <X size={18} />
            </button>
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-auto p-5 space-y-4 font-mono text-[12px]">
          {phases.map((phase) => {
            const commands = preview[phase] || [];
            if (!commands.length) return null;

            return (
              <div key={phase}>
                <p className={`text-[10px] uppercase tracking-widest font-bold mb-2 ${phaseColor[phase]}`}>
                  {phase.replace('_', ' ')}
                </p>
                <div className="rounded-xl bg-white/5 p-4 border border-white/8 space-y-1">
                  {commands.map((command, index) => (
                    <div key={`${phase}-${index}`} className="text-white/78 break-all whitespace-pre-wrap">
                      {command}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default CommandPreviewModal;