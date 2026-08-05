import React from 'react';
import { XCircle } from 'lucide-react';
import { motion } from 'motion/react';
import type { ComplianceFinding } from '../types';
import { complianceStatusBadgeClass, severityBadgeClass } from './shared';

type ComplianceFindingDetail = ComplianceFinding & {
  observed_value?: string;
  evidence?: string;
  first_seen_at?: string;
  last_seen_at?: string;
};

interface ComplianceFindingDetailModalProps {
  finding: ComplianceFindingDetail | null;
  language: string;
  t: (key: string) => string;
  onClose: () => void;
  onStatusChange: (value: ComplianceFinding['status']) => void;
  onOwnerChange: (value: string) => void;
  onNoteChange: (value: string) => void;
  onSave: () => void;
}

const ComplianceFindingDetailModal: React.FC<ComplianceFindingDetailModalProps> = ({
  finding,
  language,
  t,
  onClose,
  onStatusChange,
  onOwnerChange,
  onNoteChange,
  onSave,
}) => {
  if (!finding) return null;

  const firstSeen = finding.first_seen_at || finding.first_seen;
  const lastSeen = finding.last_seen_at || finding.last_seen;

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[60] flex items-center justify-center p-4">
      <motion.div
        initial={{ scale: 0.96, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="bg-white w-full max-w-4xl rounded-3xl shadow-2xl border border-black/5 overflow-hidden flex flex-col max-h-[84vh]"
      >
        <div className="p-6 border-b border-black/5 flex justify-between items-start bg-black/[0.01]">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-lg font-medium">{finding.title}</h3>
              <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold uppercase ${severityBadgeClass(finding.severity)}`}>{finding.severity}</span>
              <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold uppercase ${complianceStatusBadgeClass(finding.status)}`}>{finding.status.replace('_', ' ')}</span>
            </div>
            <p className="mt-2 text-xs text-black/40 font-mono">{finding.rule_id} · {finding.hostname || finding.device_id} · {finding.ip_address || 'N/A'}</p>
          </div>
          <button onClick={onClose} title={language === 'zh' ? '关闭问题详情' : 'Close finding details'} className="text-black/40 hover:text-black">
            <XCircle size={22} />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-6 space-y-5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="rounded-2xl border border-black/5 p-4 bg-black/[0.02]">
              <p className="text-[10px] font-bold uppercase tracking-widest text-black/35">{language === 'zh' ? '问题描述' : 'Description'}</p>
              <p className="mt-3 text-sm text-black/75 leading-6">{finding.description}</p>
              <p className="mt-4 text-[10px] font-bold uppercase tracking-widest text-black/35">{language === 'zh' ? '整改建议' : 'Remediation'}</p>
              <p className="mt-2 text-sm text-black/70 leading-6">{finding.remediation || (language === 'zh' ? '暂无建议' : 'No remediation provided.')}</p>
            </div>
            <div className="rounded-2xl border border-black/5 p-4 bg-black/[0.02] space-y-4">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-widest text-black/35">{language === 'zh' ? '观察值' : 'Observed Value'}</p>
                <p className="mt-2 text-xs text-black/70 font-mono whitespace-pre-wrap">{finding.observed_value || 'N/A'}</p>
              </div>
              <div>
                <p className="text-[10px] font-bold uppercase tracking-widest text-black/35">{language === 'zh' ? '证据' : 'Evidence'}</p>
                <p className="mt-2 text-xs text-black/70 font-mono whitespace-pre-wrap">{finding.evidence || 'N/A'}</p>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="text-[10px] font-bold uppercase tracking-widest text-black/35">{language === 'zh' ? '状态' : 'Status'}</label>
              <select
                value={finding.status}
                title={language === 'zh' ? '审计项状态' : 'Finding status'}
                onChange={(event) => onStatusChange(event.target.value as ComplianceFinding['status'])}
                className="mt-2 w-full px-3 py-2 rounded-xl border border-black/10 text-sm outline-none bg-white"
              >
                <option value="open">Open</option>
                <option value="in_progress">In Progress</option>
                <option value="accepted_risk">Accepted Risk</option>
                <option value="resolved">Resolved</option>
              </select>
            </div>
            <div>
              <label className="text-[10px] font-bold uppercase tracking-widest text-black/35">{language === 'zh' ? '负责人' : 'Owner'}</label>
              <input
                value={finding.owner || ''}
                title={language === 'zh' ? '负责人' : 'Owner'}
                onChange={(event) => onOwnerChange(event.target.value)}
                className="mt-2 w-full px-3 py-2 rounded-xl border border-black/10 text-sm outline-none"
                placeholder={language === 'zh' ? '例如：SecOps / NOC' : 'e.g. SecOps / NOC'}
              />
            </div>
            <div className="rounded-2xl border border-black/5 p-4 bg-black/[0.02]">
              <p className="text-[10px] font-bold uppercase tracking-widest text-black/35">{language === 'zh' ? '时间线' : 'Timeline'}</p>
              <p className="mt-2 text-xs text-black/60">{language === 'zh' ? '首次发现' : 'First seen'}: {firstSeen ? new Date(firstSeen).toLocaleString() : 'N/A'}</p>
              <p className="mt-1 text-xs text-black/60">{language === 'zh' ? '最近发现' : 'Last seen'}: {lastSeen ? new Date(lastSeen).toLocaleString() : 'N/A'}</p>
              <p className="mt-1 text-xs text-black/60">{language === 'zh' ? '已解决' : 'Resolved'}: {finding.resolved_at ? new Date(finding.resolved_at).toLocaleString() : 'N/A'}</p>
            </div>
          </div>

          <div>
            <label className="text-[10px] font-bold uppercase tracking-widest text-black/35">{language === 'zh' ? '备注' : 'Note'}</label>
            <textarea
              value={finding.note || ''}
              title={language === 'zh' ? '备注' : 'Note'}
              onChange={(event) => onNoteChange(event.target.value)}
              className="mt-2 w-full min-h-[120px] px-4 py-3 rounded-2xl border border-black/10 text-sm outline-none resize-y"
              placeholder={language === 'zh' ? '记录处理过程、风险接受依据或整改计划。' : 'Document triage notes, risk acceptance rationale, or remediation plan.'}
            />
          </div>
        </div>
        <div className="p-4 border-t border-black/5 flex justify-between gap-3">
          <button onClick={onClose} className="px-6 py-2 border border-black/10 rounded-xl text-sm font-medium hover:bg-black/5 transition-all">
            {t('cancel')}
          </button>
          <button onClick={onSave} className="px-6 py-2 bg-black text-white rounded-xl text-sm font-medium hover:bg-black/80 transition-all">
            {language === 'zh' ? '保存审计处置' : 'Save Finding'}
          </button>
        </div>
      </motion.div>
    </div>
  );
};

export default ComplianceFindingDetailModal;