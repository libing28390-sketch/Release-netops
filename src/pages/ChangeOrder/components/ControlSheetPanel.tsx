import React from 'react';
import { ClipboardCheck, User, UserCheck, Paperclip, FileText, Download } from 'lucide-react';
import type { ChangeOrder } from '../types';
import { fmtDate, fmtFileSize } from '../helpers';

interface Props {
  language: string;
  selectedOrder: ChangeOrder;
}

export const ControlSheetPanel: React.FC<Props> = ({ language, selectedOrder }) => {
  const zh = language === 'zh';
  const cs = selectedOrder.control_sheet;
  if (!cs || Object.keys(cs).length === 0) return null;

  const deviceIps: string[] = Array.isArray(cs.device_ips)
    ? cs.device_ips
    : (cs.device_ips
        ? String(cs.device_ips).split(/[\n,]+/).map((s: string) => s.trim()).filter(Boolean)
        : []);

  const attachments = selectedOrder.control_sheet_attachments || [];

  return (
    <div className="space-y-4">
      {/* ── Control Sheet Section ── */}
      <div className="rounded-2xl border border-teal-100 bg-gradient-to-br from-teal-50/60 to-white p-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="p-1.5 rounded-lg bg-teal-100 ring-1 ring-teal-200">
            <ClipboardCheck size={14} className="text-teal-600" />
          </div>
          <p className="text-sm font-bold text-teal-800">{zh ? '变更控制表' : 'Change Control Sheet'}</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {/* Change Time Window */}
          {(cs.change_time?.start || cs.change_time?.end) && (
            <div className="bg-white rounded-xl px-3 py-2.5 ring-1 ring-teal-100 md:col-span-2">
              <p className="text-[10px] font-semibold text-black/35 uppercase tracking-wider mb-1">
                {zh ? '变更时间窗口' : 'Change Time Window'}
              </p>
              <p className="text-sm font-medium text-black/70 tabular-nums">
                {cs.change_time?.start ? fmtDate(cs.change_time.start) : '—'}
                <span className="mx-2 text-black/30">→</span>
                {cs.change_time?.end ? fmtDate(cs.change_time.end) : '—'}
              </p>
            </div>
          )}

          {/* Implementer */}
          {cs.implementer?.username && (
            <div className="bg-white rounded-xl px-3 py-2.5 ring-1 ring-teal-100">
              <p className="text-[10px] font-semibold text-black/35 uppercase tracking-wider mb-1">
                {zh ? '实施人' : 'Implementer'}
              </p>
              <p className="text-sm font-medium text-black/70 flex items-center gap-1.5">
                <User size={12} className="text-teal-400" />
                {cs.implementer.username}
              </p>
            </div>
          )}

          {/* Co-Reviewer */}
          {cs.co_reviewer?.username && (
            <div className="bg-white rounded-xl px-3 py-2.5 ring-1 ring-teal-100">
              <p className="text-[10px] font-semibold text-black/35 uppercase tracking-wider mb-1">
                {zh ? '联合审核人' : 'Co-Reviewer'}
              </p>
              <p className="text-sm font-medium text-black/70 flex items-center gap-1.5">
                <UserCheck size={12} className="text-teal-400" />
                {cs.co_reviewer.username}
              </p>
            </div>
          )}

          {/* Device IPs */}
          {deviceIps.length > 0 && (
            <div className="bg-white rounded-xl px-3 py-2.5 ring-1 ring-teal-100 md:col-span-2">
              <p className="text-[10px] font-semibold text-black/35 uppercase tracking-wider mb-1.5">
                {zh ? '目标设备IP' : 'Target Device IPs'}
              </p>
              <div className="flex flex-wrap gap-1.5">
                {deviceIps.map((ip: string, i: number) => (
                  <span key={i} className="inline-flex items-center px-2 py-0.5 rounded-lg bg-teal-50 text-teal-700 text-xs font-mono ring-1 ring-teal-200">
                    {ip}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Multi-line text fields */}
        <div className="mt-3 space-y-3">
          {cs.pre_check && (
            <div className="bg-white rounded-xl px-3 py-2.5 ring-1 ring-teal-100">
              <p className="text-[10px] font-semibold text-black/35 uppercase tracking-wider mb-1">
                {zh ? '实施前检查' : 'Pre-Check'}
              </p>
              <p className="text-sm text-black/65 leading-relaxed whitespace-pre-wrap">{cs.pre_check}</p>
            </div>
          )}
          {cs.execution && (
            <div className="bg-white rounded-xl px-3 py-2.5 ring-1 ring-teal-100">
              <p className="text-[10px] font-semibold text-black/35 uppercase tracking-wider mb-1">
                {zh ? '执行步骤' : 'Execution Steps'}
              </p>
              <p className="text-sm text-black/65 leading-relaxed whitespace-pre-wrap">{cs.execution}</p>
            </div>
          )}
          {cs.post_verify && (
            <div className="bg-white rounded-xl px-3 py-2.5 ring-1 ring-teal-100">
              <p className="text-[10px] font-semibold text-black/35 uppercase tracking-wider mb-1">
                {zh ? '实施后验证' : 'Post-Verify'}
              </p>
              <p className="text-sm text-black/65 leading-relaxed whitespace-pre-wrap">{cs.post_verify}</p>
            </div>
          )}
          {cs.business_verify && (
            <div className="bg-white rounded-xl px-3 py-2.5 ring-1 ring-teal-100">
              <p className="text-[10px] font-semibold text-black/35 uppercase tracking-wider mb-1">
                {zh ? '业务验证' : 'Business Verify'}
              </p>
              <p className="text-sm text-black/65 leading-relaxed whitespace-pre-wrap">{cs.business_verify}</p>
            </div>
          )}
          {cs.rollback_plan && (
            <div className="bg-white rounded-xl px-3 py-2.5 ring-1 ring-teal-100">
              <p className="text-[10px] font-semibold text-black/35 uppercase tracking-wider mb-1">
                {zh ? '回滚方案' : 'Rollback Plan'}
              </p>
              <p className="text-sm text-black/65 leading-relaxed whitespace-pre-wrap">{cs.rollback_plan}</p>
            </div>
          )}
        </div>
      </div>

      {/* ── Control Sheet Attachments ── */}
      {attachments.length > 0 && (
        <div className="rounded-2xl border border-teal-100 bg-white p-5">
          <div className="flex items-center gap-2 mb-4">
            <div className="p-1.5 rounded-lg bg-teal-100 ring-1 ring-teal-200">
              <Paperclip size={14} className="text-teal-600" />
            </div>
            <p className="text-sm font-bold text-teal-800">
              {zh ? '变更控制表附件' : 'Control Sheet Attachments'}
            </p>
            <span className="ml-auto text-[10px] font-medium text-black/40 px-2 py-0.5 bg-black/[0.03] rounded-full">
              {zh ? `共 ${attachments.length} 个文件` : `${attachments.length} file${attachments.length !== 1 ? 's' : ''}`}
            </span>
          </div>
          <div className="space-y-2">
            {attachments.map((att) => (
              <div key={att.id} className="flex items-center gap-3 px-3 py-2.5 rounded-xl bg-teal-50/60 ring-1 ring-teal-100 hover:bg-teal-50 transition-colors">
                <FileText size={14} className="text-teal-500 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-black/75 truncate">{att.filename}</p>
                  <p className="text-[11px] text-black/40 mt-0.5 font-sans">
                    {fmtFileSize(att.size_bytes)}
                    {att.uploaded_by_username && (
                      <span className="ml-2">
                        <User size={9} className="inline -mt-0.5 mr-0.5 text-teal-400" />
                        {att.uploaded_by_username}
                      </span>
                    )}
                    {att.uploaded_at && (
                      <span className="ml-2 tabular-nums">{fmtDate(att.uploaded_at)}</span>
                    )}
                  </p>
                </div>
                {att.download_url && (
                  <a
                    href={att.download_url}
                    download={att.filename}
                    title={zh ? '下载附件' : 'Download attachment'}
                    className="flex-shrink-0 p-1.5 rounded-lg text-teal-500 hover:text-teal-700 hover:bg-teal-100 transition-all"
                    onClick={e => e.stopPropagation()}
                  >
                    <Download size={14} />
                  </a>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
