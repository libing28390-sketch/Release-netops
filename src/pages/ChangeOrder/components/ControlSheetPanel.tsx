import React, { useEffect, useRef, useState } from 'react';
import { ClipboardCheck, Paperclip, FileText, Download, User, UploadCloud } from 'lucide-react';
import type { SessionUser } from '../../../types';
import type { ChangeOrder } from '../types';
import { canUploadControlSheetAttachment, fmtDate, fmtFileSize, formatChangeOrderApiMessage } from '../helpers';
import { ActionLink, ActionButton } from '../../../components/ui/ActionIconButton';
import { ticketSurfaceClass } from '../../../components/tickets/TicketUI';

export type ControlSheetUploadResult =
  | { success: true; requiresReview?: boolean }
  | { success: false; message: string };

interface Props {
  language: string;
  selectedOrder: ChangeOrder;
  currentUser: SessionUser;
  onUpload: (orderId: string, file: File) => Promise<ControlSheetUploadResult>;
  onDownload: (orderId: string, attachmentId: string, filename: string) => void;
}

const MAX_CONTROL_SHEET_BYTES = 20 * 1024 * 1024;
const ACCEPTED_CONTROL_SHEET_FILE = /\.(pdf|doc|docx|xls|xlsx)$/i;

export const ControlSheetPanel: React.FC<Props> = ({ language, selectedOrder, currentUser, onUpload, onDownload }) => {
  const zh = language === 'zh';
  const cs = selectedOrder.control_sheet || {};
  const attachments = selectedOrder.control_sheet_attachments || [];
  const canUpload = canUploadControlSheetAttachment(selectedOrder, currentUser);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [uploadMessage, setUploadMessage] = useState('');
  const sections = [
    { key: 'pre_check', label: zh ? '变更前检查' : 'Pre-change checks', value: cs.pre_check },
    { key: 'execution', label: zh ? '人工实施步骤' : 'Manual implementation steps', value: cs.execution },
    { key: 'post_verify', label: zh ? '技术验证' : 'Technical verification', value: cs.post_verify },
    { key: 'business_verify', label: zh ? '业务验证' : 'Business verification', value: cs.business_verify },
  ].filter((section) => typeof section.value === 'string' && section.value.trim());

  useEffect(() => {
    setUploadError('');
    setUploadMessage('');
  }, [selectedOrder.id]);

  const submitFile = async (file: File) => {
    setUploadError('');
    setUploadMessage('');
    if (!ACCEPTED_CONTROL_SHEET_FILE.test(file.name)) {
      setUploadError(zh ? '仅支持 PDF、Word 或 Excel 文件。' : 'Only PDF, Word, and Excel files are supported.');
      return;
    }
    if (file.size <= 0) {
      setUploadError(zh ? '文件不能为空。' : 'The file cannot be empty.');
      return;
    }
    if (file.size > MAX_CONTROL_SHEET_BYTES) {
      setUploadError(zh ? '文件不能超过 20 MiB。' : 'The file must be 20 MiB or smaller.');
      return;
    }

    setUploading(true);
    try {
      const result = await onUpload(selectedOrder.id, file);
      if (result.success === false) {
        setUploadError(formatChangeOrderApiMessage(result.message, language, zh ? '附件上传失败' : 'Attachment upload failed'));
        return;
      }
      setUploadMessage(result.requiresReview
        ? (zh ? '附件已上传，工单已退回初审，需重新完成审批。' : 'Attachment uploaded. The order returned to initial review and needs approval again.')
        : (zh ? '控制表附件已上传。' : 'Control sheet attachment uploaded.'));
    } catch (error) {
      setUploadError(formatChangeOrderApiMessage(error, language, zh ? '附件上传请求失败' : 'Attachment upload request failed'));
    } finally {
      setUploading(false);
    }
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const input = event.currentTarget;
    const file = input.files?.[0];
    input.value = '';
    if (file) void submitFile(file);
  };

  const showAttachments = attachments.length > 0 || canUpload || (selectedOrder.status === 'approved' && attachments.length === 0);

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

      {showAttachments && (
        <section className={`${ticketSurfaceClass} p-4 sm:p-5`} aria-label={zh ? '控制表附件' : 'Control sheet attachments'}>
          <header className="mb-3 flex flex-wrap items-center gap-2 border-b border-[var(--ui-border)] pb-3">
            <Paperclip size={15} className="text-[var(--ui-fg-muted)]" aria-hidden="true" />
            <h3 className="text-sm font-semibold text-[var(--ui-fg)]">{zh ? '控制表附件' : 'Control sheet attachments'}</h3>
            <span className="ml-auto text-[11px] text-[var(--ui-fg-muted)]">
              {zh ? `${attachments.length} 个文件` : `${attachments.length} file${attachments.length !== 1 ? 's' : ''}`}
            </span>
            {canUpload && (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  className="sr-only"
                  accept=".pdf,.doc,.docx,.xls,.xlsx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                  aria-label={zh ? '上传控制表附件' : 'Upload control sheet attachment'}
                  disabled={uploading}
                  onChange={handleFileChange}
                />
                <ActionButton
                  type="button"
                  icon={UploadCloud}
                  variant="accent"
                  size="sm"
                  disabled={uploading}
                  onClick={() => fileInputRef.current?.click()}
                >
                  {uploading ? (zh ? '上传中…' : 'Uploading…') : (zh ? '上传附件' : 'Upload attachment')}
                </ActionButton>
              </>
            )}
          </header>

          {attachments.length === 0 ? (
            <p className="text-xs text-[var(--ui-fg-muted)]" role="note">
              {zh ? '实施前至少需要一份 PDF、Word 或 Excel 控制表附件。' : 'Upload at least one PDF, Word, or Excel control sheet attachment before implementation.'}
            </p>
          ) : (
            <ul className="divide-y divide-[var(--ui-border)]">
              {attachments.map((att) => (
                <li key={att.id} className="flex min-w-0 items-center gap-3 py-3 first:pt-0 last:pb-0">
                  <FileText size={16} className="shrink-0 text-[var(--ui-fg-subtle)]" aria-hidden="true" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-medium text-[var(--ui-fg)]" title={att.filename || att.file_name}>
                      {att.filename || att.file_name || (zh ? '控制表附件' : 'Control sheet attachment')}
                    </p>
                    <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[var(--ui-fg-muted)]">
                      <span>{fmtFileSize(att.size_bytes ?? att.file_size ?? 0)}</span>
                      {att.uploaded_by_username && <span><User size={11} className="mr-1 inline" aria-hidden="true" />{att.uploaded_by_username}</span>}
                      {(att.uploaded_at || att.created_at) && <time className="tabular-nums">{fmtDate(att.uploaded_at || att.created_at || '')}</time>}
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
                  {!att.download_url && (
                    <ActionButton
                      type="button"
                      icon={Download}
                      variant="accent"
                      size="sm"
                      onClick={() => onDownload(selectedOrder.id, att.id, att.filename || att.file_name || (zh ? '控制表附件' : 'Control sheet attachment'))}
                    >
                      {zh ? '下载附件' : 'Download attachment'}
                    </ActionButton>
                  )}
                </li>
              ))}
            </ul>
          )}
          {['final_review', 'approved', 'implementing'].includes(selectedOrder.status) && canUpload && (
            <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800" role="note">
              {zh ? '审核中、审批后或实施阶段上传附件会使工单退回初审，并需重新完成审批。' : 'Uploading during review, after approval, or during implementation returns the order to initial review and requires approval again.'}
            </p>
          )}
          {uploadError && <p className="mt-3 text-xs text-[var(--ui-danger)]" role="alert">{uploadError}</p>}
          {uploadMessage && <p className="mt-3 text-xs text-[var(--ui-success)]" role="status">{uploadMessage}</p>}
        </section>
      )}
    </div>
  );
};
