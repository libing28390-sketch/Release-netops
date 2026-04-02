import React, { useEffect, useRef } from 'react';
import { motion } from 'motion/react';
import { X } from 'lucide-react';
import type { Device, User } from '../types';

interface CustomCommandModalProps {
  language: string;
  t: (key: string) => string;
  customCommand: string;
  customCommandMode: 'query' | 'config';
  customCommandVars: string[];
  scriptVars: Record<string, string>;
  batchMode: boolean;
  batchDeviceIds: string[];
  selectedDevice: Device | null;
  isBatchRunning: boolean;
  isTestingConnection: boolean;
  showFavorites: boolean;
  commandFavorites: string[];
  configReason: string;
  approverUsername: string;
  approvalCode: string;
  approvalStatus: 'idle' | 'sending' | 'sent' | 'verified' | 'error';
  approvalError: string;
  approvalCountdown: number;
  approverUsers: User[];
  onClose: () => void;
  onSubmit: () => void;
  onCustomCommandChange: (value: string) => void;
  onModeChange: (mode: 'query' | 'config') => void;
  onScriptVarChange: (key: string, value: string) => void;
  onToggleFavorite: (command: string) => void;
  isFavorited: (command: string) => boolean;
  onSaveQuickQuery: () => void;
  onToggleFavorites: () => void;
  onUseFavorite: (command: string) => void;
  onConfigReasonChange: (value: string) => void;
  onApproverUsernameChange: (value: string) => void;
  onApprovalCodeChange: (value: string) => void;
  onRequestApproval: () => void;
  onVerifyApproval: () => void;
}

const CustomCommandModal: React.FC<CustomCommandModalProps> = ({
  language,
  t,
  customCommand,
  customCommandMode,
  customCommandVars,
  scriptVars,
  batchMode,
  batchDeviceIds,
  selectedDevice,
  isBatchRunning,
  isTestingConnection,
  showFavorites,
  commandFavorites,
  onClose,
  onSubmit,
  onCustomCommandChange,
  onModeChange,
  onScriptVarChange,
  onToggleFavorite,
  isFavorited,
  onSaveQuickQuery,
  onToggleFavorites,
  onUseFavorite,
  configReason,
  onConfigReasonChange,
  approverUsername,
  approvalCode,
  approvalStatus,
  approvalError,
  approvalCountdown,
  approverUsers,
  onApproverUsernameChange,
  onApprovalCodeChange,
  onRequestApproval,
  onVerifyApproval,
}) => {
  const canSubmit = (batchMode ? batchDeviceIds.length > 0 : !!selectedDevice) && customCommand.trim() && !(batchMode ? isBatchRunning : isTestingConnection);
  const needsConfirm = customCommandMode === 'config';
  const canConfirmSubmit = canSubmit && (!needsConfirm || approvalStatus === 'verified');
  const canSendCode = needsConfirm && approverUsername.trim().length >= 1 && configReason.trim().length >= 2 && approvalStatus !== 'sending';

  // Auto-verify when 6 digits entered
  const prevCodeLen = useRef(0);
  useEffect(() => {
    if (approvalCode.length === 6 && prevCodeLen.current < 6 && approvalStatus === 'sent') {
      onVerifyApproval();
    }
    prevCodeLen.current = approvalCode.length;
  }, [approvalCode, approvalStatus, onVerifyApproval]);

  // Filter to users with Administrator/Operator role for approver dropdown
  const eligibleApprovers = approverUsers.filter(u => u.role === 'Administrator' || u.role === 'Operator');

  return (
    <div
      className="fixed inset-0 bg-black/55 backdrop-blur-sm flex items-center justify-center z-[85] p-4"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.96, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="w-full max-w-3xl max-h-[86vh] rounded-3xl bg-white shadow-2xl border border-black/8 overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-5 border-b border-black/6 bg-[linear-gradient(135deg,rgba(0,188,235,0.08),rgba(0,82,122,0.04))]">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-[11px] font-bold uppercase tracking-[0.24em] text-[#0087a9]">
                {language === 'zh' ? 'Direct Execution' : 'Direct Execution'}
              </p>
              <h3 className="mt-1 text-xl font-semibold text-black/85">
                {language === 'zh' ? '自定义命令' : 'Custom Command'}
              </h3>
            </div>
            <button
              onClick={onClose}
              title={language === 'zh' ? '关闭' : 'Close'}
              className="text-black/35 hover:text-black/70 transition-colors mt-1"
            >
              <X size={20} />
            </button>
          </div>
          <div className="mt-4 flex items-center gap-3">
            <span className="text-[11px] font-semibold text-black/40">
              {language === 'zh' ? '执行模式' : 'Mode'}
            </span>
            <div className="flex items-center bg-black/[0.06] rounded-xl p-[3px] gap-[3px]">
              <button
                onClick={() => onModeChange('query')}
                className={`flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-[12px] font-semibold transition-all ${
                  customCommandMode === 'query'
                    ? 'bg-white text-[#0087a9] shadow-sm shadow-black/10'
                    : 'text-black/40 hover:text-black/60'
                }`}
              >
                <svg width="13" height="13" viewBox="0 0 16 16" fill="none" className="opacity-80"><circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.8"/><path d="M11 11l3 3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>
                {language === 'zh' ? '查看' : 'Query'}
              </button>
              <button
                onClick={() => onModeChange('config')}
                className={`flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-[12px] font-semibold transition-all ${
                  customCommandMode === 'config'
                    ? 'bg-[#005b75] text-white shadow-sm shadow-[#005b75]/30'
                    : 'text-black/40 hover:text-black/60'
                }`}
              >
                <svg width="13" height="13" viewBox="0 0 16 16" fill="none" className="opacity-80"><path d="M2 4h12M2 8h8M2 12h5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>
                {language === 'zh' ? '配置' : 'Config'}
              </button>
            </div>
            <span className={`text-[11px] font-medium transition-colors ${customCommandMode === 'query' ? 'text-sky-600' : 'text-amber-600'}`}>
              {customCommandMode === 'query'
                ? (language === 'zh' ? 'Exec 模式 — 只读，不改变配置' : 'Exec mode — read-only, no changes')
                : (language === 'zh' ? 'Config 模式 — 自动进入配置视图' : 'Config mode — enters config view automatically')}
            </span>
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-auto p-6 space-y-5 bg-[#fbfdff]">
          <div className="grid grid-cols-1 lg:grid-cols-[1.25fr,0.75fr] gap-5">
            <div className="space-y-4">
              <div className="rounded-2xl border border-black/8 bg-white p-4 shadow-sm">
                <div className="flex items-center justify-between gap-3 mb-3">
                  <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-black/35">
                    {language === 'zh' ? '命令内容' : 'Command Content'}
                  </p>
                  <div className="flex items-center gap-1.5">
                    {customCommandMode === 'query' && (
                      <button
                        disabled={!customCommand.trim()}
                        onClick={onSaveQuickQuery}
                        className={`px-3 py-1.5 rounded-lg text-[11px] font-semibold border transition-all ${customCommand.trim()
                          ? 'border-[#00bceb]/30 text-[#0087a9] hover:bg-[#00bceb]/10' : 'border-black/8 text-black/25 cursor-not-allowed'}`}
                      >
                        {language === 'zh' ? '+ 快捷查询' : '+ Quick Query'}
                      </button>
                    )}
                    <button
                      onClick={() => onToggleFavorite(customCommand)}
                      disabled={!customCommand.trim()}
                      className={`px-3 py-1.5 rounded-lg text-[11px] font-semibold border transition-all ${customCommand.trim()
                        ? (isFavorited(customCommand)
                          ? 'border-amber-300 bg-amber-50 text-amber-700 hover:bg-amber-100'
                          : 'border-black/10 text-black/60 hover:bg-black/5')
                        : 'border-black/8 text-black/25 cursor-not-allowed'}`}
                    >
                      {isFavorited(customCommand)
                        ? (language === 'zh' ? '取消收藏' : 'Unfavorite')
                        : (language === 'zh' ? '收藏命令' : 'Save Favorite')}
                    </button>
                  </div>
                </div>
                <textarea
                  value={customCommand}
                  onChange={(e) => onCustomCommandChange(e.target.value)}
                  placeholder={customCommandMode === 'query'
                    ? (language === 'zh'
                      ? '例如:\nshow ip interface brief\nshow version\ndisplay version'
                      : 'Example:\nshow ip interface brief\nshow version\ndisplay version')
                    : (language === 'zh'
                      ? '例如:\ninterface Vlan100\n description Branch Office\n ip address 10.10.0.1 255.255.255.0'
                      : 'Example:\ninterface Vlan100\n description Branch Office\n ip address 10.10.0.1 255.255.255.0')}
                  className="w-full min-h-[260px] resize-y rounded-2xl border border-black/10 bg-[#0c1622] px-4 py-3 text-[13px] leading-6 text-[#d9f3ff] font-mono outline-none focus:border-[#00bceb]/50"
                />
              </div>

              {customCommandVars.length > 0 && (
                <div className="rounded-2xl border border-black/8 bg-white p-4 shadow-sm space-y-3">
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-black/35">
                      {language === 'zh' ? '变量替换' : 'Variable Substitution'}
                    </p>
                    <p className="mt-1 text-xs text-black/40">
                      {language === 'zh' ? '使用 `{{VAR}}` 占位符时，请在这里填写值。' : 'Fill values for any `{{VAR}}` placeholders here.'}
                    </p>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {customCommandVars.map((key) => (
                      <label key={key} className="space-y-1.5">
                        <span className="text-[11px] font-semibold text-black/65">{key}</span>
                        <input
                          type="text"
                          value={scriptVars[key] || ''}
                          onChange={(e) => onScriptVarChange(key, e.target.value)}
                          placeholder={language === 'zh' ? `输入 ${key}` : `Enter ${key}`}
                          className="w-full rounded-xl border border-black/10 bg-white px-3 py-2 text-sm outline-none focus:border-[#00bceb]/45"
                        />
                      </label>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="space-y-4">
              <div className="rounded-2xl border border-black/8 bg-white p-4 shadow-sm space-y-3">
                <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-black/35">
                  {language === 'zh' ? '执行目标' : 'Execution Target'}
                </p>
                <div className="rounded-xl border border-black/8 bg-black/[0.02] px-3 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-semibold text-black/75">
                      {batchMode
                        ? (language === 'zh' ? `批量模式 · ${batchDeviceIds.length} 台设备` : `Batch mode · ${batchDeviceIds.length} devices`)
                        : (selectedDevice
                          ? `${selectedDevice.hostname} (${selectedDevice.ip_address})`
                          : (language === 'zh' ? '未选择设备' : 'No device selected'))}
                    </p>
                    {!batchMode && selectedDevice && (
                      <span className="text-[10px] font-semibold px-2 py-0.5 rounded-md bg-[#00bceb]/10 text-[#0087a9] font-mono">
                        {selectedDevice.platform || 'unknown'}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-[11px] text-black/40">
                    {batchMode
                      ? (language === 'zh' ? '使用左侧设备列表维护批量目标。' : 'Manage batch targets from the device list on the left.')
                      : (language === 'zh' ? '当前将下发到左侧选中的单台设备。' : 'Command will run on the device selected in the left panel.')}
                  </p>
                </div>
                <div className={`rounded-xl px-3 py-3 text-xs leading-5 transition-all ${
                  customCommandMode === 'query'
                    ? 'border border-sky-200 bg-sky-50 text-sky-700'
                    : 'border border-amber-200 bg-amber-50 text-amber-700'
                }`}>
                  {customCommandMode === 'query'
                    ? (language === 'zh'
                      ? '查看模式：命令在 Exec 模式下执行，适用于 show、display、ping、tracert 等只读命令。若匹配到 ntc-templates，会自动生成表格；未匹配时默认保留原始终端输出。'
                      : 'Query mode: commands run in exec mode. Use for show, display, ping, tracert — read-only, no config changes. When an ntc template matches, the result is structured automatically; otherwise the raw terminal output is preserved.')
                    : (language === 'zh'
                      ? <>配置模式——各平台自动进入配置视图：<br/>· Cisco：<code className="font-mono">configure terminal</code><br/>· Huawei / H3C：<code className="font-mono">system-view</code><br/>· Arista EOS：<code className="font-mono">configure session</code>（事务，失败自动回滚）<br/>· Juniper：<code className="font-mono">configure</code></>
                      : <><b>Config mode</b> — config view entered automatically per platform:<br/>· Cisco: <code className="font-mono">configure terminal</code><br/>· Huawei / H3C: <code className="font-mono">system-view</code><br/>· Arista EOS: <code className="font-mono">configure session</code> (transactional, auto-rollback on error)<br/>· Juniper: <code className="font-mono">configure</code></>)}
                </div>
              </div>

              <div className="rounded-2xl border border-black/8 bg-white p-4 shadow-sm space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-black/35">
                    {language === 'zh' ? '常用命令' : 'Favorites'}
                  </p>
                  <button
                    onClick={onToggleFavorites}
                    className="text-[11px] font-semibold text-[#0087a9] hover:text-[#006c86]"
                  >
                    {showFavorites
                      ? (language === 'zh' ? '收起' : 'Hide')
                      : (language === 'zh' ? '展开' : 'Show')}
                  </button>
                </div>
                {showFavorites ? (
                  commandFavorites.length > 0 ? (
                    <div className="space-y-2 max-h-[260px] overflow-auto pr-1">
                      {commandFavorites.map((favorite, idx) => (
                        <div key={`${favorite}-${idx}`} className="rounded-xl border border-black/8 bg-black/[0.02] p-3">
                          <pre className="text-[11px] leading-5 text-black/70 font-mono whitespace-pre-wrap break-all">{favorite}</pre>
                          <div className="mt-2 flex items-center justify-between gap-2">
                            <button
                              onClick={() => onUseFavorite(favorite)}
                              className="px-2.5 py-1.5 rounded-lg bg-[#00bceb] text-white text-[11px] font-semibold hover:bg-[#009ac2] transition-all"
                            >
                              {language === 'zh' ? '填入编辑器' : 'Use Command'}
                            </button>
                            <button
                              onClick={() => onToggleFavorite(favorite)}
                              className="px-2.5 py-1.5 rounded-lg border border-black/10 text-[11px] font-semibold text-black/55 hover:bg-black/5 transition-all"
                            >
                              {language === 'zh' ? '移除' : 'Remove'}
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-xl border border-dashed border-black/10 px-3 py-4 text-xs text-black/35 text-center">
                      {language === 'zh' ? '还没有收藏的命令。' : 'No saved commands yet.'}
                    </div>
                  )
                ) : (
                  <p className="text-xs text-black/35">
                    {language === 'zh' ? '可将常用配置收藏到这里，便于快速复用。' : 'Save frequently used commands here for quick reuse.'}
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>

        <div className="px-6 py-4 border-t border-black/6 bg-white space-y-3">
          {needsConfirm && (
            <div className="rounded-2xl border border-black/8 overflow-hidden">
              {/* 顶栏 */}
              <div className={`px-4 py-2.5 flex items-center gap-2.5 ${
                approvalStatus === 'verified'
                  ? 'bg-gradient-to-r from-emerald-500 to-emerald-600'
                  : 'bg-gradient-to-r from-[#005b75] to-[#00465a]'
              }`}>
                {approvalStatus === 'verified' ? (
                  <svg width="15" height="15" viewBox="0 0 16 16" fill="none" className="text-white/90 flex-shrink-0"><path d="M3 8.5L6.5 12L13 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
                ) : (
                  <svg width="15" height="15" viewBox="0 0 16 16" fill="none" className="text-white/90 flex-shrink-0"><rect x="2" y="7" width="12" height="8" rx="2" stroke="currentColor" strokeWidth="1.5"/><path d="M5 7V5a3 3 0 016 0v2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/><circle cx="8" cy="11" r="1" fill="currentColor"/></svg>
                )}
                <span className="text-[12px] font-semibold text-white/95">
                  {approvalStatus === 'verified'
                    ? (language === 'zh' ? '审批已通过' : 'Approval Granted')
                    : (language === 'zh' ? '配置变更审批' : 'Config Change Approval')}
                </span>
                {approvalStatus === 'verified' && (
                  <span className="ml-auto text-[11px] text-white/70 font-medium">
                    {language === 'zh' ? '可以执行配置' : 'Ready to apply'}
                  </span>
                )}
              </div>

              {approvalStatus !== 'verified' && (
                <div className="px-4 py-3.5 bg-[#f7fbfc] space-y-3">
                  {/* 变更原因 + 审批人 — 双列 */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="text-[11px] font-semibold text-black/50 mb-1 block tracking-wide">
                        {language === 'zh' ? '变更原因' : 'Change Reason'}
                      </label>
                      <input
                        value={configReason}
                        onChange={e => onConfigReasonChange(e.target.value)}
                        placeholder={language === 'zh' ? '例如：添加 VLAN 100 接口配置' : 'e.g. Add VLAN 100 interface config'}
                        className="w-full rounded-xl border border-black/10 bg-white px-3 py-2 text-xs outline-none focus:border-[#00bceb] focus:ring-1 focus:ring-[#00bceb]/20 placeholder:text-black/25 transition-all"
                        maxLength={200}
                      />
                    </div>
                    <div>
                      <label className="text-[11px] font-semibold text-black/50 mb-1 block tracking-wide">
                        {language === 'zh' ? '审批人' : 'Approver'}
                      </label>
                      <div className="flex items-center gap-2">
                        <select
                          value={approverUsername}
                          onChange={e => onApproverUsernameChange(e.target.value)}
                          title={language === 'zh' ? '选择审批人' : 'Select approver'}
                          className="flex-1 rounded-xl border border-black/10 bg-white px-3 py-2 text-xs outline-none focus:border-[#00bceb] focus:ring-1 focus:ring-[#00bceb]/20 transition-all appearance-none bg-[url('data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%2212%22%20height%3D%2212%22%20viewBox%3D%220%200%2012%2012%22%3E%3Cpath%20d%3D%22M3%205l3%203%203-3%22%20stroke%3D%22%23999%22%20stroke-width%3D%221.5%22%20fill%3D%22none%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%2F%3E%3C%2Fsvg%3E')] bg-[length:12px] bg-[right_10px_center] bg-no-repeat pr-8"
                          disabled={approvalStatus === 'sent' || approvalStatus === 'sending'}
                        >
                          <option value="">{language === 'zh' ? '选择审批人...' : 'Select approver...'}</option>
                          {eligibleApprovers.map(u => (
                            <option key={u.id} value={u.username}>
                              {u.username} ({u.role})
                            </option>
                          ))}
                        </select>
                        <button
                          onClick={onRequestApproval}
                          disabled={!canSendCode || (approvalStatus === 'sent' && approvalCountdown > 0)}
                          className={`px-3.5 py-2 rounded-xl text-[11px] font-semibold transition-all whitespace-nowrap flex items-center gap-1.5 ${
                            canSendCode && !(approvalStatus === 'sent' && approvalCountdown > 0)
                              ? 'bg-[#005b75] text-white hover:bg-[#00465a] shadow-sm shadow-[#005b75]/20'
                              : 'bg-black/8 text-black/30 cursor-not-allowed'
                          }`}
                        >
                          {approvalStatus === 'sending' ? (
                            <><svg className="animate-spin" width="12" height="12" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="2" strokeDasharray="28" strokeDashoffset="8" strokeLinecap="round" opacity="0.7"/></svg>{language === 'zh' ? '发送中' : 'Sending'}</>
                          ) : approvalStatus === 'sent' && approvalCountdown > 0 ? (
                            <>{approvalCountdown}s</>
                          ) : (
                            <><svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M2 3h12v10H2z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/><path d="M2 3l6 5 6-5" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/></svg>{language === 'zh' ? '发送验证码' : 'Send Code'}</>
                          )}
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* 验证码输入区 — 仅发送后展示 */}
                  {(approvalStatus === 'sent' || approvalStatus === 'error') && (
                    <div className="rounded-xl border border-dashed border-[#00bceb]/30 bg-[#ecfeff]/50 px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div className="flex-1">
                          <label className="text-[11px] font-semibold text-[#0087a9] mb-1.5 block">
                            {language === 'zh' ? '输入审批人收到的 6 位验证码' : 'Enter the 6-digit code sent to approver'}
                          </label>
                          <div className="flex items-center gap-2">
                            <input
                              value={approvalCode}
                              onChange={e => {
                                const v = e.target.value.replace(/\D/g, '').slice(0, 6);
                                onApprovalCodeChange(v);
                              }}
                              placeholder="· · · · · ·"
                              className="flex-1 rounded-xl border border-[#00bceb]/25 bg-white px-4 py-2 text-sm outline-none focus:border-[#00bceb] focus:ring-1 focus:ring-[#00bceb]/20 placeholder:text-black/20 tracking-[0.5em] font-mono text-center font-semibold transition-all"
                              maxLength={6}
                              autoFocus
                            />
                            <button
                              onClick={onVerifyApproval}
                              disabled={approvalCode.length !== 6}
                              className={`px-4 py-2 rounded-xl text-[11px] font-semibold transition-all whitespace-nowrap flex items-center gap-1.5 ${
                                approvalCode.length === 6
                                  ? 'bg-emerald-600 text-white hover:bg-emerald-700 shadow-sm shadow-emerald-600/20'
                                  : 'bg-black/8 text-black/30 cursor-not-allowed'
                              }`}
                            >
                              <svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M3 8.5L6.5 12L13 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
                              {language === 'zh' ? '验证' : 'Verify'}
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* 错误信息 */}
                  {approvalError && (
                    <div className="flex items-center gap-2 rounded-xl bg-red-50 border border-red-200 px-3 py-2">
                      <svg width="13" height="13" viewBox="0 0 16 16" fill="none" className="text-red-500 flex-shrink-0"><circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.5"/><path d="M8 5v3.5M8 10.5v.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
                      <p className="text-[11px] text-red-700 font-medium">{approvalError}</p>
                    </div>
                  )}

                  {/* 底部信息 */}
                  <div className="flex items-center gap-1.5 pt-0.5">
                    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" className="text-black/25 flex-shrink-0"><circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.2"/><path d="M8 5v3.5M8 10.5v.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/></svg>
                    <p className="text-[11px] text-black/35">
                      {language === 'zh'
                        ? '验证码将通过飞书发送给审批人，有效期 5 分钟。'
                        : 'A verification code will be sent to the approver via Feishu, valid for 5 minutes.'}
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-black/35">
              {language === 'zh'
                ? (batchMode ? '将按左侧批量目标逐台执行。' : '执行结果会自动出现在历史记录中。')
                : (batchMode ? 'Commands will execute sequentially across the selected batch.' : 'Execution results will appear in the history view automatically.')}
            </p>
            <div className="flex items-center gap-2">
              <button
                onClick={onClose}
                className="px-4 py-2 rounded-xl text-sm font-medium text-black/60 hover:text-black hover:bg-black/5 transition-all"
              >
                {t('cancel')}
              </button>
              <button
                onClick={onSubmit}
                disabled={!canConfirmSubmit}
                className={`px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all ${
                  canConfirmSubmit
                    ? (needsConfirm ? 'bg-[#005b75] hover:bg-[#00465a] shadow-lg shadow-[#005b75]/20' : 'bg-[#005b75] hover:bg-[#00465a] shadow-lg shadow-[#005b75]/20')
                    : 'bg-black/15 text-black/30 cursor-not-allowed'
                }`}
              >
                {batchMode
                  ? (isBatchRunning
                    ? (language === 'zh' ? '批量执行中...' : 'Running Batch...')
                    : (language === 'zh' ? `批量下发 (${batchDeviceIds.length})` : `Run Batch (${batchDeviceIds.length})`))
                  : (isTestingConnection
                    ? (language === 'zh' ? '执行中...' : 'Running...')
                    : needsConfirm
                      ? (language === 'zh' ? '确认并执行配置' : 'Confirm & Apply Config')
                      : (language === 'zh' ? '执行命令' : 'Run Command'))}
              </button>
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  );
};

export default CustomCommandModal;