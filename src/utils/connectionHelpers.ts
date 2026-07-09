import type { DeviceConnectionCheckSummary } from '../types';

export const LEGACY_SSH_ERROR_CODE = 'legacy_ssh_algorithms';
export const SSH_AUTH_ERROR_CODE = 'ssh_authentication_failed';
export const SSH_TIMEOUT_ERROR_CODE = 'ssh_transport_timeout';
export const SSH_TRANSPORT_ERROR_CODE = 'ssh_transport_unreachable';

export const buildConnectionTestMessage = (detail: any, errorCode?: string): string => {
  const normalizedDetail = typeof detail === 'string'
    ? detail
    : (detail && typeof detail === 'object' && 'message' in detail ? String(detail.message) : 'Connection failed');

  if (errorCode === LEGACY_SSH_ERROR_CODE) {
    return '设备 SSH 算法较旧，兼容重试后仍未完成协商。';
  }

  if (errorCode === SSH_AUTH_ERROR_CODE) {
    return '设备可达，但 SSH 认证被拒绝。请检查账号密码或 AAA/VTY 配置。';
  }

  if (errorCode === SSH_TIMEOUT_ERROR_CODE) {
    return 'SSH 会话建立或读取超时，请检查设备负载、VTY 状态或中间策略。';
  }

  if (errorCode === SSH_TRANSPORT_ERROR_CODE) {
    return 'SSH 传输层未建立，请检查 22 端口、SSH 服务和 ACL/防火墙策略。';
  }

  return normalizedDetail || 'Connection failed';
};

export const buildConnectionTestHint = (errorCode?: string, language: string = 'zh'): string | null => {
  const isZh = language === 'zh';
  if (errorCode === LEGACY_SSH_ERROR_CODE) {
    return isZh ? '建议先核对设备 SSH 算法与镜像版本。' : 'Check device SSH algorithm support and software version.';
  }
  if (errorCode === SSH_AUTH_ERROR_CODE) {
    return isZh ? '建议先用同一账号手工 SSH 登录，再检查 AAA、VTY、login local。' : 'Try a manual SSH login with the same account, then review AAA, VTY, and login local.';
  }
  if (errorCode === SSH_TIMEOUT_ERROR_CODE) {
    return isZh ? '建议先检查设备 CPU、会话配额和中间安全设备。' : 'Check device CPU, session limits, and any inline security controls.';
  }
  if (errorCode === SSH_TRANSPORT_ERROR_CODE) {
    return isZh ? '建议先确认 22 端口、SSH 服务和路径 ACL。' : 'Verify TCP/22, the SSH service, and path ACLs.';
  }
  return null;
};

export const buildConnectionCheckStatus = (
  success: boolean,
  mode: 'quick' | 'deep',
  errorCode?: string,
  stages?: Array<{ stage: string; ok: boolean }>,
): DeviceConnectionCheckSummary['status'] => {
  if (success) return 'ok';
  if (errorCode === LEGACY_SSH_ERROR_CODE) return 'ssh_legacy';
  if (errorCode === SSH_AUTH_ERROR_CODE) return 'ssh_auth_fail';
  if (errorCode === SSH_TIMEOUT_ERROR_CODE) return 'ssh_timeout';
  if (errorCode === SSH_TRANSPORT_ERROR_CODE) return 'ssh_transport';
  if (mode === 'quick' || stages?.some((stage) => stage.stage === 'tcp' && !stage.ok)) return 'tcp_fail';
  return 'fail';
};

export const connectionCheckBadgeMeta: Record<DeviceConnectionCheckSummary['status'], { zh: string; en: string; className: string }> = {
  ok: { zh: 'OK', en: 'OK', className: 'border-emerald-200 bg-emerald-100 text-emerald-700' },
  tcp_fail: { zh: 'TCP 失败', en: 'TCP Fail', className: 'border-red-200 bg-red-100 text-red-700' },
  ssh_auth_fail: { zh: 'SSH 认证失败', en: 'SSH Auth Fail', className: 'border-rose-200 bg-rose-100 text-rose-700' },
  ssh_timeout: { zh: 'SSH 超时', en: 'SSH Timeout', className: 'border-orange-200 bg-orange-100 text-orange-700' },
  ssh_transport: { zh: 'SSH 传输失败', en: 'SSH Transport', className: 'border-slate-200 bg-slate-100 text-slate-700' },
  ssh_legacy: { zh: 'SSH 算法旧', en: 'Legacy SSH', className: 'border-amber-200 bg-amber-100 text-amber-700' },
  fail: { zh: '失败', en: 'Fail', className: 'border-red-200 bg-red-100 text-red-700' },
};

export const formatConnectionCheckTime = (value: string, language: string) => {
  try {
    return new Date(value).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  } catch {
    return value;
  }
};
