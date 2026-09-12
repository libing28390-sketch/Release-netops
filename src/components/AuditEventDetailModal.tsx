import React from 'react';
import { XCircle } from 'lucide-react';
import { motion } from 'motion/react';
import type { AuditEvent } from '../types';
import { auditStatusBadgeClass, parseJsonObject, severityBadgeClass } from './shared';

interface AuditEventDetailModalProps {
  event: AuditEvent | null;
  language: string;
  t: (key: string) => string;
  onClose: () => void;
}

const AuditEventDetailModal: React.FC<AuditEventDetailModalProps> = ({ event, language, t, onClose }) => {
  if (!event) return null;

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[60] flex items-center justify-center p-4">
      <motion.div
        initial={{ scale: 0.96, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="bg-white w-full max-w-3xl rounded-3xl shadow-2xl border border-black/5 overflow-hidden flex flex-col max-h-[82vh]"
      >
        <div className="p-6 border-b border-black/5 flex justify-between items-start bg-black/[0.01]">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-lg font-medium">{event.summary}</h3>
              <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold uppercase ${auditStatusBadgeClass(event.status)}`}>{event.status}</span>
              <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold uppercase ${severityBadgeClass(event.severity)}`}>{event.severity}</span>
            </div>
            <p className="mt-2 text-xs text-black/40 font-mono">{event.event_type} · {new Date(event.created_at).toLocaleString()}</p>
          </div>
          <button onClick={onClose} title={language === 'zh' ? '关闭审计详情' : 'Close audit details'} className="text-black/40 hover:text-black">
            <XCircle size={22} />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-6 space-y-5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="rounded-2xl border border-black/5 p-4 bg-black/[0.02]">
              <p className="text-[10px] font-bold uppercase tracking-widest text-black/35">{language === 'zh' ? '行为主体' : 'Actor'}</p>
              <p className="mt-2 text-sm font-medium">{event.actor_username || 'system'}</p>
              <p className="text-xs text-black/40 mt-1">{event.actor_role || 'Unknown role'}</p>
              <p className="text-xs text-black/35 mt-1 font-mono">{event.source_ip || 'N/A'}</p>
            </div>
            <div className="rounded-2xl border border-black/5 p-4 bg-black/[0.02]">
              <p className="text-[10px] font-bold uppercase tracking-widest text-black/35">{language === 'zh' ? '目标对象' : 'Target'}</p>
              <p className="mt-2 text-sm font-medium">{event.target_name || 'N/A'}</p>
              <p className="text-xs text-black/40 mt-1">{event.target_type || 'Unknown type'} · {event.target_id || 'N/A'}</p>
              <p className="text-xs text-black/35 mt-1 font-mono">device={event.device_id || 'N/A'} job={event.job_id || 'N/A'}</p>
            </div>
          </div>

          <div className="rounded-2xl border border-black/5 p-4">
            <p className="text-[10px] font-bold uppercase tracking-widest text-black/35">{language === 'zh' ? '事件详情' : 'Event Details'}</p>
            <pre className="mt-3 text-xs text-black/70 bg-black/[0.02] rounded-xl p-4 overflow-auto whitespace-pre-wrap font-mono">
              {JSON.stringify(event.details || parseJsonObject(event.details_json), null, 2)}
            </pre>
          </div>
        </div>
        <div className="p-4 border-t border-black/5 flex justify-end">
          <button onClick={onClose} className="px-6 py-2 bg-black text-white rounded-xl text-sm font-medium hover:bg-black/80 transition-all">
            {t('close')}
          </button>
        </div>
      </motion.div>
    </div>
  );
};

export default AuditEventDetailModal;