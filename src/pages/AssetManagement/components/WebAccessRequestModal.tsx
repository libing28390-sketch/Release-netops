import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Globe2, Loader2, Shield, User, X } from 'lucide-react';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import { useFocusTrap } from '../../../hooks/useFocusTrap';

import type { WebAccessLevel } from '../../../api/pamWeb';
import type { WebAccessProfile } from '../types';

export interface WebAccessTarget {
  hostname?: string;
  management_ip?: string;
}

interface WebAccessRequestModalProps {
  isOpen: boolean;
  asset: WebAccessTarget | null;
  profiles: WebAccessProfile[];
  accessLevel: WebAccessLevel;
  profileId: string;
  reason: string;
  requesting: boolean;
  language: string;
  onAccessLevelChange: (value: WebAccessLevel) => void;
  onProfileChange: (value: string) => void;
  onReasonChange: (value: string) => void;
  onClose: () => void;
  onSubmit: () => void;
}

export const WebAccessRequestModal: React.FC<WebAccessRequestModalProps> = ({
  isOpen,
  asset,
  profiles,
  accessLevel,
  profileId,
  reason,
  requesting,
  language,
  onAccessLevelChange,
  onProfileChange,
  onReasonChange,
  onClose,
  onSubmit,
}) => {
  const dialogRef = React.useRef<HTMLDivElement>(null);
  const dialogTitleId = React.useId();
  const profileInputId = React.useId();
  const reasonInputId = React.useId();
  const dialogOpen = isOpen && Boolean(asset);
  useEscapeClose(dialogOpen && !requesting, onClose);
  useFocusTrap(dialogRef, dialogOpen, 'select');
  const zh = language === 'zh';
  return (
    <AnimatePresence>
      {isOpen && asset && (
        <motion.div
          className="fixed inset-0 z-[220] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={() => !requesting && onClose()}
        >
          <motion.div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={dialogTitleId}
            aria-busy={requesting}
            className="nx-form-dialog-surface w-full max-w-md overflow-hidden rounded-xl border shadow-2xl"
            initial={{ opacity: 0, scale: 0.97, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: 8 }}
            onClick={event => event.stopPropagation()}
          >
            <div className="nx-dialog-header flex items-center justify-between border-b px-5 py-4">
              <div className="flex items-center gap-3">
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-cyan-50 text-cyan-600"><Globe2 size={18} /></span>
                <div>
                  <h3 id={dialogTitleId} className="text-sm font-bold">{zh ? 'Web 管理访问' : 'Web Management Access'}</h3>
                  <p className="mt-0.5 text-xs text-[var(--ui-fg-muted)]">{asset.hostname || asset.management_ip}</p>
                </div>
              </div>
              <button type="button" onClick={onClose} disabled={requesting} aria-label={zh ? '关闭' : 'Close'} className="rounded-lg p-1.5 text-[var(--ui-fg-muted)] hover:bg-[var(--ui-surface-muted)] hover:text-[var(--ui-fg)]"><X size={16} /></button>
            </div>

            <div className="space-y-4 p-5">
              <div>
                <label htmlFor={profileInputId} className="mb-1.5 block text-[10px] font-bold uppercase tracking-wider text-[var(--ui-fg-muted)]">{zh ? 'Web 入口' : 'Web entry'}</label>
                <select id={profileInputId} value={profileId} onChange={event => onProfileChange(event.target.value)} className="w-full rounded-xl border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2.5 text-sm text-[var(--ui-fg)] outline-none focus:border-[var(--ui-accent)]">
                  {profiles.map(profile => (
                    <option key={profile.id} value={profile.id}>
                      {profile.profile_name} · {profile.scheme.toUpperCase()} · {profile.port}{profile.path || '/'}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <span className="mb-1.5 block text-[10px] font-bold uppercase tracking-wider text-[var(--ui-fg-muted)]">{zh ? '访问类型' : 'Access type'}</span>
                <div role="group" aria-label={zh ? '访问类型' : 'Access type'} className="grid grid-cols-2 gap-2 rounded-xl bg-[var(--ui-surface-muted)] p-1">
                  <button type="button" aria-pressed={accessLevel === 'normal'} onClick={() => onAccessLevelChange('normal')} className={`min-h-10 flex items-center justify-center gap-2 rounded-lg py-2 text-xs font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)] ${accessLevel === 'normal' ? 'bg-[var(--ui-surface)] text-[var(--ui-accent)] shadow-sm' : 'text-[var(--ui-fg-muted)]'}`}><User size={13} />{zh ? '普通访问' : 'Normal'}</button>
                  <button type="button" aria-pressed={accessLevel === 'admin'} onClick={() => onAccessLevelChange('admin')} className={`min-h-10 flex items-center justify-center gap-2 rounded-lg py-2 text-xs font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-warning)] ${accessLevel === 'admin' ? 'bg-[var(--ui-warning-subtle)] text-[var(--ui-warning)] shadow-sm' : 'text-[var(--ui-fg-muted)]'}`}><Shield size={13} />{zh ? '特权访问' : 'Privileged'}</button>
                </div>
                <p className="mt-1.5 text-[10px] leading-4 text-[var(--ui-fg-muted)]">{zh ? '当前仅用于申请分类和审计，不限制设备网页内的具体权限。' : 'Used for request classification and audit only; page permissions are not restricted.'}</p>
              </div>

              <div>
                <label htmlFor={reasonInputId} className="mb-1.5 block text-[10px] font-bold uppercase tracking-wider text-[var(--ui-fg-muted)]">{zh ? '访问说明（可选）' : 'Reason (optional)'}</label>
                <textarea id={reasonInputId} rows={3} value={reason} onChange={event => onReasonChange(event.target.value)} className="w-full resize-none rounded-xl border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2 text-sm text-[var(--ui-fg)] outline-none focus:border-[var(--ui-accent)]" placeholder={zh ? '例如：检查防火墙策略或服务器带外健康状态' : 'For example: inspect firewall policy or server BMC health'} />
              </div>

              <div className="rounded-xl border border-[var(--ui-border)] bg-[var(--ui-accent-subtle)] px-3 py-2 text-[11px] leading-5 text-[var(--ui-fg)]">
                {zh ? '提交后将调用本机 Nexora Agent 打开系统浏览器。设备账号密码由用户在设备页面自行输入。' : 'Nexora Agent will open the system browser. Enter device credentials directly on the device page.'}
              </div>
            </div>

            <div className="nx-form-dialog-footer flex justify-end gap-2 px-5 py-4">
              <button type="button" onClick={onClose} disabled={requesting} className="nx-dialog-action-secondary rounded-xl border px-4 py-2 text-xs font-semibold">{zh ? '取消' : 'Cancel'}</button>
              <button type="button" onClick={onSubmit} disabled={requesting || !profileId} className="nx-dialog-action-primary inline-flex min-w-28 items-center justify-center gap-2 rounded-xl border px-4 py-2 text-xs font-bold disabled:opacity-50">
                {requesting ? <Loader2 size={14} className="animate-spin" /> : <Globe2 size={14} />}
                {zh ? '申请并打开' : 'Request & Open'}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};
