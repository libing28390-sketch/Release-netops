import React from 'react';
import { ClipboardCheck, Paperclip, FileText, Download, User } from 'lucide-react';
import type { ChangeOrder } from '../types';
import { fmtDate, fmtFileSize } from '../helpers';
import { ActionLink } from '../../../components/ui/ActionIconButton';
import { ticketSurfaceClass } from '../../../components/tickets/TicketUI';

interface Props {
  language: string;
  selectedOrder: ChangeOrder;
}

export const ControlSheetPanel: React.FC<Props> = ({ language, selectedOrder }) => {
  const zh = language === 'zh';
  const cs = selectedOrder.control_sheet;
  if (!cs || Object.keys(cs).length === 0) return null;

  const attachments = selectedOrder.control_sheet_attachments || [];
  const sections = [
    { key: 'pre_check', label: zh ? '变更前检查' : 'Pre-change checks', value: cs.pre_check },
    { key: 'execution', label: zh ? '人工实施步骤' : 'Manual implementation steps', value: cs.execution },
    { key: 'post_verify', label: zh ? '技术验证' : 'Technical verification', value: cs.post_verify },
    { key: 'business_verify', label: zh ? '业务验证' : 'Business verification', value: cs.business_verify },
  ].filter((section) => typeof section.value === 'string' && section.value.trim());

  return (
    <div className="space-y-3">
      <section className={`${ticketSurfaceClass} p-4 sm:p-5`} aria-label={zh ? '变更控制表' : 'Change control sheet'}>
        <header className="mb-4 flex items-start gap-3 border-b border-[var(--ui-border)] pb-3">
          <span className="mt-0.5 rounded-lg bg-[var(--ui-surface-muted)] p-2 text-[var(--ui-fg-muted)]">
            <ClipboardCheck size={16} aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-[var(--ui-fg)]">{zh ? '变更控制表' : 'Change control sheet'}</h3>
            <p className="mt-1 text-[11px] leading-4 text-[var(--ui-fg-muted)]">
              {zh ? '实施前检查、人工步骤及技术和业务验证。' : 'Pre-change checks, manual steps, and technical and business verification.'}
            </p>
          </div>
        </header>

        <div className="grid gap-3 md:grid-cols-2">
          {sections.map((section) => (
            <div key={section.key} className="min-w-0 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] p-3">
              <h4 className="text-xs font-semibold text-[var(--ui-fg-muted)]">{section.label}</h4>
              <p className="mt-1.5 whitespace-pre-wrap break-words text-[13px] leading-5 text-[var(--ui-fg)]">{section.value}</p>
            </div>
          ))}
          {sections.length === 0 && (
            <p className="text-xs text-[var(--ui-fg-muted)]">{zh ? '暂无控制表内容。' : 'No control sheet details are available.'}</p>
          )}
        </div>
      </section>

      {attachments.length > 0 && (
        <section className={`${ticketSurfaceClass} p-4 sm:p-5`} aria-label={zh ? '控制表附件' : 'Control sheet attachments'}>
          <header className="mb-3 flex flex-wrap items-center gap-2 border-b border-[var(--ui-border)] pb-3">
            <Paperclip size={15} className="text-[var(--ui-fg-muted)]" aria-hidden="true" />
            <h3 className="text-sm font-semibold text-[var(--ui-fg)]">{zh ? '控制表附件' : 'Control sheet attachments'}</h3>
            <span className="ml-auto text-[11px] text-[var(--ui-fg-muted)]">
              {zh ? `${attachments.length} 个文件` : `${attachments.length} file${attachments.length !== 1 ? 's' : ''}`}
            </span>
          </header>
          <ul className="divide-y divide-[var(--ui-border)]">
            {attachments.map((att) => (
              <li key={att.id} className="flex min-w-0 items-center gap-3 py-3 first:pt-0 last:pb-0">
                <FileText size={16} className="shrink-0 text-[var(--ui-fg-subtle)]" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium text-[var(--ui-fg)]" title={att.filename}>{att.filename}</p>
                  <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[var(--ui-fg-muted)]">
                    <span>{fmtFileSize(att.size_bytes)}</span>
                    {att.uploaded_by_username && <span><User size={11} className="mr-1 inline" aria-hidden="true" />{att.uploaded_by_username}</span>}
                    {att.uploaded_at && <time className="tabular-nums">{fmtDate(att.uploaded_at)}</time>}
                  </p>
                </div>
                {att.download_url && (
                  <ActionLink
                    href={att.download_url}
                    download={att.filename}
                    title={zh ? '下载附件' : 'Download attachment'}
                    icon={Download}
                    variant="accent"
                    size="sm"
                    onClick={(event) => event.stopPropagation()}
                  />
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
};
