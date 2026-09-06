import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Globe2, Loader2, Shield, User, X } from 'lucide-react';

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
            className="w-full max-w-md overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
            initial={{ opacity: 0, scale: 0.97, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: 8 }}
            onClick={event => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/70 px-5 py-4">
              <div className="flex items-center gap-3">
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-cyan-50 text-cyan-600"><Globe2 size={18} /></span>
                <div>
                  <h3 className="text-sm font-bold text-slate-800">{zh ? 'Web 管理访问' : 'Web Management Access'}</h3>
                  <p className="mt-0.5 text-[10px] text-slate-400">{asset.hostname || asset.management_ip}</p>
                </div>
              </div>
              <button type="button" onClick={onClose} disabled={requesting} className="rounded-lg p-1.5 text-slate-300 hover:bg-white hover:text-slate-500"><X size={16} /></button>
            </div>

            <div className="space-y-4 p-5">
              <div>
                <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-wider text-slate-400">{zh ? 'Web 入口' : 'Web entry'}</label>
                <select value={profileId} onChange={event => onProfileChange(event.target.value)} className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-700 outline-none focus:border-cyan-400">
                  {profiles.map(profile => (
                    <option key={profile.id} value={profile.id}>
                      {profile.profile_name} · {profile.scheme.toUpperCase()} · {profile.port}{profile.path || '/'}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-wider text-slate-400">{zh ? '访问类型' : 'Access type'}</label>
                <div className="grid grid-cols-2 gap-2 rounded-xl bg-slate-50 p-1">
                  <button type="button" onClick={() => onAccessLevelChange('normal')} className={`flex items-center justify-center gap-2 rounded-lg py-2 text-xs font-semibold ${accessLevel === 'normal' ? 'bg-white text-cyan-700 shadow-sm' : 'text-slate-400'}`}><User size={13} />{zh ? '普通访问' : 'Normal'}</button>
                  <button type="button" onClick={() => onAccessLevelChange('admin')} className={`flex items-center justify-center gap-2 rounded-lg py-2 text-xs font-semibold ${accessLevel === 'admin' ? 'bg-white text-orange-600 shadow-sm' : 'text-slate-400'}`}><Shield size={13} />{zh ? '特权访问' : 'Privileged'}</button>
                </div>
                <p className="mt-1.5 text-[10px] leading-4 text-slate-400">{zh ? '当前仅用于申请分类和审计，不限制设备网页内的具体权限。' : 'Used for request classification and audit only; page permissions are not restricted.'}</p>
              </div>

              <div>
                <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-wider text-slate-400">{zh ? '访问说明（可选）' : 'Reason (optional)'}</label>
                <textarea rows={3} value={reason} onChange={event => onReasonChange(event.target.value)} className="w-full resize-none rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-700 outline-none focus:border-cyan-400" placeholder={zh ? '例如：检查防火墙策略或服务器带外健康状态' : 'For example: inspect firewall policy or server BMC health'} />
              </div>

              <div className="rounded-xl border border-cyan-100 bg-cyan-50/60 px-3 py-2 text-[11px] leading-5 text-cyan-800">
                {zh ? '提交后将调用本机 Nexora Agent 打开系统浏览器。设备账号密码由用户在设备页面自行输入。' : 'Nexora Agent will open the system browser. Enter device credentials directly on the device page.'}
              </div>
            </div>

            <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-4">
              <button type="button" onClick={onClose} disabled={requesting} className="rounded-xl px-4 py-2 text-xs font-semibold text-slate-400 hover:bg-slate-50">{zh ? '取消' : 'Cancel'}</button>
              <button type="button" onClick={onSubmit} disabled={requesting || !profileId} className="inline-flex min-w-28 items-center justify-center gap-2 rounded-xl bg-cyan-500 px-4 py-2 text-xs font-bold text-white shadow-sm hover:bg-cyan-600 disabled:opacity-50">
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
