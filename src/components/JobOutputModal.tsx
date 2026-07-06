import React from 'react';
import { Copy } from 'lucide-react';
import { motion } from 'motion/react';
import type { Job } from '../types';

interface JobOutputModalProps {
  job: Job | null;
  t: (key: string) => string;
  onClose: () => void;
  onCopy: () => void;
}

const JobOutputModal: React.FC<JobOutputModalProps> = ({ job, t, onClose, onCopy }) => {
  if (!job) return null;

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[60] flex items-center justify-center p-4">
      <motion.div
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="bg-white w-full max-w-4xl rounded-3xl shadow-2xl border border-black/5 overflow-hidden flex flex-col max-h-[80vh]"
      >
        <div className="p-6 border-b border-black/5 flex justify-between items-center bg-black/[0.01]">
          <div>
            <h3 className="text-lg font-medium">{job.task_name}</h3>
            <p className="text-xs text-black/40 uppercase tracking-wider">{new Date(job.created_at).toLocaleString()}</p>
          </div>
          <div className={`px-3 py-1 rounded-full text-[10px] font-bold uppercase ${
            job.status === 'success' ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'
          }`}>
            {job.status}
          </div>
        </div>
        <div className="flex-1 overflow-auto p-6 bg-[#1E1E1E] font-mono text-xs text-[#D4D4D4] relative group">
          <button
            onClick={onCopy}
            className="absolute top-4 right-4 p-2 bg-white/10 hover:bg-white/20 text-white rounded-lg opacity-0 group-hover:opacity-100 transition-all"
            title="Copy Output"
          >
            <Copy size={16} />
          </button>
          <pre className="whitespace-pre-wrap">{job.output || 'No output recorded.'}</pre>
        </div>
        <div className="p-4 border-t border-black/5 flex justify-end gap-3">
          <button onClick={onClose} className="px-6 py-2 bg-black text-white rounded-xl text-sm font-medium hover:bg-black/80 transition-all">
            {t('close')}
          </button>
        </div>
      </motion.div>
    </div>
  );
};

export default JobOutputModal;