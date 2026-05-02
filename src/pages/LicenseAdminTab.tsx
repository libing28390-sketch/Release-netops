import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Shield, Upload, AlertTriangle, CheckCircle2, Clock, Server,
  Cpu, Key, RefreshCw, X, Lock, Unlock, ChevronDown, ChevronUp,
  Zap, Eye, EyeOff, FileText, AlertCircle, Info, Calendar,
  Hash, Building2, Crown, Loader2, ShieldCheck, ShieldAlert, Copy,
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';

interface Props {
  language: string;
  t: (key: string) => string;
}

interface LicenseStatus {
  valid: boolean;
  license_id?: string;
  company?: string;
  license_type?: string;
  issued_at?: string;
  expire_at?: string;
  days_remaining?: number;
  device_limit?: number;
  device_current?: number;
  server_limit?: number;
  server_current?: number;
  features: string[];
  warnings: string[];
  error?: string;
}

interface DeviceUsage {
  valid: boolean;
  device_limit: number;
  device_current: number;
  utilization_percent: number;
  remaining: number;
  exceeded: boolean;
  server_limit: number;
  server_current: number;
  server_utilization_percent: number;
  server_remaining: number;
  server_exceeded: boolean;
}

interface AuditEntry {
  timestamp: string;
  action: string;
  detail: string;
  ip?: string;
}

const FEATURE_LABELS: Record<string, { zh: string; en: string; icon: any }> = {
  automation:         { zh: '自动化执行',   en: 'Automation',          icon: Zap },
  config_management:  { zh: '配置管理',     en: 'Config Management',   icon: FileText },
  monitoring:         { zh: '监控中心',     en: 'Monitoring',          icon: Eye },
  alerting:           { zh: '告警系统',     en: 'Alerting',            icon: AlertTriangle },
  rbac:               { zh: '角色权限',     en: 'RBAC',                icon: Lock },
  change_orders:      { zh: '变更工单',     en: 'Change Orders',       icon: FileText },
  inspections:        { zh: '巡检管理',     en: 'Inspections',         icon: ShieldCheck },
  topology:           { zh: '拓扑发现',     en: 'Topology',            icon: Cpu },
  ipam:               { zh: 'IP 管理',      en: 'IPAM',                icon: Hash },
  capacity:           { zh: '容量规划',     en: 'Capacity',            icon: Server },
  compliance:         { zh: '合规检查',     en: 'Compliance',          icon: ShieldCheck },
  reports:            { zh: '报表导出',     en: 'Reports',             icon: FileText },
  api_access:         { zh: 'API 接口',     en: 'API Access',          icon: Key },
  scheduled_jobs:     { zh: '定时任务',     en: 'Scheduled Jobs',      icon: Clock },
  password_rotation:  { zh: '密码轮换',     en: 'Password Rotation',   icon: RefreshCw },
};

const TYPE_COLORS: Record<string, string> = {
  trial:        'from-slate-500 to-slate-600',
  standard:     'from-blue-500 to-blue-600',
  professional: 'from-violet-500 to-violet-600',
  enterprise:   'from-amber-500 to-amber-600',
};

const TYPE_LABELS: Record<string, { zh: string; en: string }> = {
  trial:        { zh: '试用版', en: 'Trial' },
  standard:     { zh: '标准版', en: 'Standard' },
  professional: { zh: '专业版', en: 'Professional' },
  enterprise:   { zh: '企业版', en: 'Enterprise' },
};

const LicenseAdminTab: React.FC<Props> = ({ language }) => {
  const zh = language === 'zh';

  const [status, setStatus] = useState<LicenseStatus | null>(null);
  const [deviceUsage, setDeviceUsage] = useState<DeviceUsage | null>(null);
  const [auditLog, setAuditLog] = useState<AuditEntry[]>([]);
  const [machineId, setMachineId] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [feedbackMsg, setFeedbackMsg] = useState<{ type: 'success' | 'error' | 'warning' | 'info'; text: string } | null>(null);
  const [showFeatures, setShowFeatures] = useState(true);
  const [showAudit, setShowAudit] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [copiedText, setCopiedText] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [sRes, dRes, aRes, mRes] = await Promise.all([
        fetch('/api/license/status'),
        fetch('/api/license/device-usage'),
        fetch('/api/license/audit-log'),
        fetch('/api/license/machine-id'),
      ]);
      if (sRes.ok) setStatus(await sRes.json());
      if (dRes.ok) setDeviceUsage(await dRes.json());
      if (aRes.ok) {
        const data = await aRes.json();
        setAuditLog(data.entries || []);
      }
      if (mRes.ok) {
        const mData = await mRes.json();
        setMachineId(mData.machine_id);
      }
    } catch { /* noop */ }
    setLoading(false);
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // Auto-dismiss feedback
  useEffect(() => {
    if (feedbackMsg) {
      const t = setTimeout(() => setFeedbackMsg(null), 6000);
      return () => clearTimeout(t);
    }
  }, [feedbackMsg]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const token = localStorage.getItem('netops_token');
      const res = await fetch('/api/license/upload', { 
        method: 'POST', 
        body: formData,
        headers: token ? { 'Authorization': `Bearer ${token}` } : {}
      });
      if (res.ok) {
        setFeedbackMsg({ type: 'success', text: zh ? 'License 上传成功并已激活' : 'License uploaded and activated' });
        await fetchAll();
      } else {
        const err = await res.json();
        setFeedbackMsg({ type: 'error', text: err.detail || (zh ? '上传失败' : 'Upload failed') });
      }
    } catch {
      setFeedbackMsg({ type: 'error', text: zh ? '网络错误' : 'Network error' });
    }
    setUploading(false);
    e.target.value = '';
  };

  const copyToClipboard = (text: string) => {
    const onSuccess = () => {
      setCopiedText(text);
      setTimeout(() => setCopiedText(null), 2000);
    };

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => {
        onSuccess();
      }).catch(() => {
        fallbackCopyTextToClipboard(text, onSuccess);
      });
    } else {
      fallbackCopyTextToClipboard(text, onSuccess);
    }
  };

  const fallbackCopyTextToClipboard = (text: string, onSuccess: () => void) => {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.style.top = "0";
    textArea.style.left = "0";
    textArea.style.position = "fixed";
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    try {
      const successful = document.execCommand('copy');
      if (successful) onSuccess();
    } catch (err) {
      // noop
    }
    document.body.removeChild(textArea);
  };

  const translateError = (err?: string) => {
    if (!err) return '';
    if (!zh) return err;
    const lower = err.toLowerCase();
    if (lower.includes('public key not found')) return '未找到公钥文件。';
    if (lower.includes('license file not found')) return '未找到授权文件。';
    if (lower.includes('corrupted')) return '授权文件损坏（非法的 JSON 格式）。';
    if (lower.includes('invalid license signature')) return '授权签名无效，文件可能已被篡改。';
    if (lower.includes('license expired')) {
      const match = err.match(/\d+/);
      const days = match ? match[0] : '';
      return `授权已过期${days ? ` ${days} 天` : ''}。`;
    }
    if (lower.includes('machine id')) {
      if (lower.includes('lacks machine_id')) return '非试用版授权必须绑定机器码。';
      return '授权文件绑定的机器码与当前服务器不一致。';
    }
    return err;
  };

  const fmtDate = (iso?: string) => {
    if (!iso) return '—';
    try {
      const d = new Date(iso);
      return d.toLocaleDateString(zh ? 'zh-CN' : 'en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch { return iso; }
  };

  const licType = status?.license_type || 'standard';
  const typeGradient = TYPE_COLORS[licType] || TYPE_COLORS.standard;
  const typeLabel = TYPE_LABELS[licType]?.[zh ? 'zh' : 'en'] || licType;

  // Device usage ring
  const usagePct = deviceUsage?.utilization_percent ?? 0;
  const ringColor = usagePct > 90 ? '#ef4444' : usagePct > 70 ? '#f59e0b' : '#10b981';
  const circumference = 2 * Math.PI * 40;
  const strokeDash = (usagePct / 100) * circumference;

  // Server usage ring
  const svrUsagePct = deviceUsage?.server_utilization_percent ?? 0;
  const svrRingColor = svrUsagePct > 90 ? '#ef4444' : svrUsagePct > 70 ? '#f59e0b' : '#10b981';
  const svrStrokeDash = (svrUsagePct / 100) * circumference;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[400px]">
        <Loader2 size={28} className="animate-spin text-[#00bceb]" />
      </div>
    );
  }

  return (
    <div className="space-y-4 pb-6">
      {/* Hidden file input */}
      <input ref={fileInputRef} type="file" accept=".json" className="hidden" onChange={handleUpload} />

      {/* Feedback Toast */}
      <AnimatePresence>
        {feedbackMsg && (
          <motion.div
            initial={{ opacity: 0, y: -12 }} animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }} transition={{ duration: 0.25 }}
            className={`flex items-center gap-3 px-4 py-3 rounded-xl border shadow-lg backdrop-blur-sm ${
              feedbackMsg.type === 'success' ? 'bg-emerald-50/90 border-emerald-200 text-emerald-800' :
              feedbackMsg.type === 'warning' ? 'bg-amber-50/90 border-amber-200 text-amber-800' :
              feedbackMsg.type === 'info' ? 'bg-cyan-50/90 border-cyan-200 text-cyan-800' :
              'bg-red-50/90 border-red-200 text-red-800'
            }`}
          >
            {feedbackMsg.type === 'success' ? <CheckCircle2 size={18} className="text-emerald-500 shrink-0" /> :
             feedbackMsg.type === 'warning' ? <AlertTriangle size={18} className="text-amber-500 shrink-0" /> :
             <AlertCircle size={18} className="text-red-500 shrink-0" />}
            <span className="text-sm font-medium flex-1">{feedbackMsg.text}</span>
            <button onClick={() => setFeedbackMsg(null)} className="p-0.5 rounded-md hover:bg-black/5"><X size={14} /></button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold tracking-tight flex items-center gap-2">
            <Shield size={20} className="text-[#00bceb]" />
            {zh ? 'License 授权管理' : 'License Management'}
          </h2>
          <p className="text-xs text-black/40 mt-0.5">{zh ? '管理平台授权、设备配额与功能开关' : 'Manage platform licensing, device quotas, and feature flags'}</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={fetchAll} className="p-2 rounded-lg text-black/25 hover:text-[#00bceb] hover:bg-[#00bceb]/5 transition-colors" title={zh ? '刷新' : 'Refresh'}>
            <RefreshCw size={15} />
          </button>
          <button
            onClick={() => {
              if (status?.valid) {
                setShowConfirm(true);
              } else {
                fileInputRef.current?.click();
              }
            }}
            disabled={uploading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#00bceb] text-white text-xs font-semibold hover:bg-[#00a5d0] shadow-sm shadow-[#00bceb]/20 disabled:opacity-50"
          >
            {uploading ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
            {zh ? '上传 License' : 'Upload License'}
          </button>
        </div>
      </div>

      {/* ── Status Banner ── */}
      {status && !status.valid && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-red-50 border border-red-200">
          <ShieldAlert size={20} className="text-red-500 shrink-0" />
          <div>
            <p className="text-sm font-semibold text-red-800">{zh ? 'License 无效' : 'License Invalid'}</p>
            <p className="text-xs text-red-600 mt-0.5">{translateError(status.error)}</p>
          </div>
        </div>
      )}

      {status && status.valid && status.warnings.length > 0 && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-amber-50 border border-amber-200">
          <AlertTriangle size={20} className="text-amber-500 shrink-0" />
          <div>
            <p className="text-sm font-semibold text-amber-800">{zh ? '授权即将到期' : 'License Expiring Soon'}</p>
            <p className="text-xs text-amber-600 mt-0.5">
              {zh 
                ? `License 将在 ${status?.days_remaining} 天内过期，请尽快续期。` 
                : `License expires in ${status?.days_remaining} day(s) — please renew soon.`}
            </p>
          </div>
        </div>
      )}

      {/* ── Top Cards ── */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        {/* License Type Card */}
        <div className={`rounded-xl bg-gradient-to-br ${typeGradient} p-4 text-white shadow-sm`}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[9px] font-bold uppercase tracking-widest text-white/50">LICENSE</span>
            <Crown size={16} className="text-white/40" />
          </div>
          <p className="text-lg font-black">{typeLabel}</p>
          <p className="text-[10px] text-white/50 mt-1">{status?.company || '—'}</p>
        </div>

        {/* Validity Card */}
        <div className="rounded-xl bg-white border border-black/5 p-4 shadow-sm">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[9px] font-bold uppercase tracking-widest text-black/30">{zh ? '有效状态' : 'STATUS'}</span>
            {status?.valid ? <CheckCircle2 size={16} className="text-emerald-500" /> : <AlertCircle size={16} className="text-red-500" />}
          </div>
          <p className={`text-lg font-black ${status?.valid ? 'text-emerald-600' : 'text-red-600'}`}>
            {status?.valid ? (zh ? '有效' : 'Valid') : (zh ? '无效' : 'Invalid')}
          </p>
          <p className="text-[10px] text-black/35 mt-1">
            {status?.days_remaining !== undefined && status?.days_remaining >= 0
              ? (zh ? `剩余 ${status.days_remaining} 天` : `${status.days_remaining} days remaining`)
              : (status?.error || '—')}
          </p>
        </div>

        {/* Expiry Card */}
        <div className="rounded-xl bg-white border border-black/5 p-4 shadow-sm">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[9px] font-bold uppercase tracking-widest text-black/30">{zh ? '到期时间' : 'EXPIRES'}</span>
            <Calendar size={16} className="text-black/20" />
          </div>
          <p className="text-sm font-bold text-black/70">{fmtDate(status?.expire_at)}</p>
          <p className="text-[10px] text-black/35 mt-1">{zh ? '签发: ' : 'Issued: '}{fmtDate(status?.issued_at)}</p>
        </div>

        {/* Device Usage Card */}
        <div className="rounded-xl bg-white border border-black/5 p-4 shadow-sm">
          <div className="flex items-center gap-3">
            <svg width="56" height="56" viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="40" fill="none" stroke="#e5e7eb" strokeWidth="8" />
              <circle cx="50" cy="50" r="40" fill="none" stroke={ringColor} strokeWidth="8" strokeLinecap="round"
                strokeDasharray={`${strokeDash} ${circumference}`} transform="rotate(-90 50 50)"
                className="transition-all duration-700"
              />
              <text x="50" y="54" textAnchor="middle" className="text-sm font-bold fill-current" style={{ fontSize: '18px', fill: ringColor }}>
                {Math.round(usagePct)}%
              </text>
            </svg>
            <div>
              <span className="text-[9px] font-bold uppercase tracking-widest text-black/30">{zh ? '网络设备' : 'NETWORK DEVICES'}</span>
              <p className="text-sm font-bold text-black/70 mt-0.5">{deviceUsage?.device_current ?? 0} / {deviceUsage?.device_limit ?? 0}</p>
              <p className="text-[10px] text-black/35">{zh ? `剩余 ${deviceUsage?.remaining ?? 0} 台` : `${deviceUsage?.remaining ?? 0} remaining`}</p>
            </div>
          </div>
        </div>

        {/* Server Usage Card */}
        <div className="rounded-xl bg-white border border-black/5 p-4 shadow-sm">
          <div className="flex items-center gap-3">
            <svg width="56" height="56" viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="40" fill="none" stroke="#e5e7eb" strokeWidth="8" />
              <circle cx="50" cy="50" r="40" fill="none" stroke={svrRingColor} strokeWidth="8" strokeLinecap="round"
                strokeDasharray={`${svrStrokeDash} ${circumference}`} transform="rotate(-90 50 50)"
                className="transition-all duration-700"
              />
              <text x="50" y="54" textAnchor="middle" className="text-sm font-bold fill-current" style={{ fontSize: '18px', fill: svrRingColor }}>
                {Math.round(svrUsagePct)}%
              </text>
            </svg>
            <div>
              <span className="text-[9px] font-bold uppercase tracking-widest text-black/30">{zh ? '服务器' : 'SERVERS'}</span>
              <p className="text-sm font-bold text-black/70 mt-0.5">{deviceUsage?.server_current ?? 0} / {deviceUsage?.server_limit ?? 0}</p>
              <p className="text-[10px] text-black/35">{zh ? `剩余 ${deviceUsage?.server_remaining ?? 0} 台` : `${deviceUsage?.server_remaining ?? 0} remaining`}</p>
            </div>
          </div>
        </div>
      </div>

      {/* ── License Details ── */}
      {/* ── License Details ── */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* License Info */}
        <div className="xl:col-span-1 bg-white rounded-2xl border border-black/5 shadow-sm p-5 flex flex-col">
          <h3 className="text-xs font-bold uppercase tracking-wider text-black/30 mb-4 flex items-center gap-1.5">
            <Key size={14} className="text-cyan-500" /> {zh ? '授权详情' : 'License Details'}
          </h3>
          <div className="space-y-3 flex-1">
            {([
              { label: zh ? '服务器机器码' : 'Machine ID', value: machineId, mono: true, copyable: true },
              { label: zh ? 'License ID' : 'License ID', value: status?.license_id, mono: true },
              { label: zh ? '授权公司' : 'Company', value: status?.company },
              { label: zh ? '版本类型' : 'Type', value: typeLabel },
              { label: zh ? '签发时间' : 'Issued At', value: fmtDate(status?.issued_at) },
              { label: zh ? '到期时间' : 'Expires At', value: fmtDate(status?.expire_at) },
              { label: zh ? '设备上限' : 'Device Limit', value: status?.device_limit?.toString() },
              { label: zh ? '服务器上限' : 'Server Limit', value: status?.server_limit?.toString() },
              { label: zh ? '功能权限' : 'Features', value: `${status?.features?.length || 0} ${zh ? '项已授权' : 'authorized'}` },
            ]).map(row => (
              <div key={row.label} className="flex items-center justify-between py-2 border-b border-black/[0.03] last:border-0 group">
                <span className="text-[11px] text-black/40 font-medium">{row.label}</span>
                <div className="flex items-center gap-2 max-w-[60%]">
                  <span className={`text-[11px] font-semibold text-black/70 truncate ${row.mono ? 'font-mono text-[10px] bg-slate-50 px-1 rounded' : ''}`}>
                    {row.value || '—'}
                  </span>
                  {row.copyable && row.value && (
                    <button
                      onClick={() => copyToClipboard(row.value as string)}
                      className={`p-1 rounded hover:bg-black/5 transition-colors ${copiedText === row.value ? 'text-emerald-500' : 'text-black/20 hover:text-cyan-600'}`}
                      title={zh ? '复制' : 'Copy'}
                    >
                      {copiedText === row.value ? <CheckCircle2 size={12} /> : <Copy size={12} />}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 pt-4 border-t border-black/5">
            <div className="flex items-center justify-between text-[10px] text-black/30">
              <span>{zh ? '授权状态验证' : 'License verification'}</span>
              <span className="flex items-center gap-1 text-emerald-500 font-bold">
                <ShieldCheck size={10} /> {zh ? '已通过' : 'Passed'}
              </span>
            </div>
          </div>
        </div>

        {/* Feature Flags */}
        <div className="xl:col-span-2 bg-white rounded-2xl border border-black/5 shadow-sm flex flex-col overflow-hidden">
          <div className="px-5 py-4 border-b border-black/5 flex items-center justify-between bg-slate-50/50">
            <h3 className="text-xs font-bold uppercase tracking-wider text-black/30 flex items-center gap-1.5">
              <Crown size={14} className="text-amber-500" /> {zh ? '功能授权清单' : 'Licensed Features'}
            </h3>
            <span className="px-2 py-0.5 rounded-full bg-cyan-100 text-cyan-700 text-[10px] font-bold">
              {status?.features?.length ?? 0} / {Object.keys(FEATURE_LABELS).length}
            </span>
          </div>
          <div className="p-5 grid grid-cols-2 md:grid-cols-3 gap-3 flex-1 overflow-y-auto">
            {Object.entries(FEATURE_LABELS).map(([key, meta]) => {
              const enabled = status?.features?.includes(key) ?? false;
              const Icon = meta.icon;
              return (
                <div key={key} className={`group relative flex flex-col gap-2 p-3 rounded-xl border transition-all duration-300 ${
                  enabled 
                    ? 'border-emerald-100 bg-white shadow-sm hover:shadow-md hover:border-emerald-200' 
                    : 'border-slate-100 bg-slate-50/50 opacity-50 grayscale hover:grayscale-0 transition-all'
                }`}>
                  <div className="flex items-center justify-between">
                    <div className={`p-2 rounded-lg ${enabled ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-200 text-slate-400'}`}>
                      <Icon size={16} />
                    </div>
                    {enabled ? (
                      <div className="flex items-center gap-1 text-[10px] font-bold text-emerald-500">
                        <CheckCircle2 size={12} />
                        {zh ? '已开启' : 'ON'}
                      </div>
                    ) : (
                      <X size={12} className="text-slate-300" />
                    )}
                  </div>
                  <div>
                    <p className={`text-[13px] font-bold ${enabled ? 'text-slate-800' : 'text-slate-400'}`}>
                      {meta[zh ? 'zh' : 'en']}
                    </p>
                    <p className="text-[10px] text-slate-400 mt-0.5 line-clamp-1">
                      {enabled ? (zh ? '已获得永久授权' : 'Permanent access') : (zh ? '当前版本未包含' : 'Not included')}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>



      {/* ── Overwrite Confirmation Modal ── */}
      <AnimatePresence>
        {showConfirm && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              className="bg-white rounded-2xl shadow-xl max-w-md w-full overflow-hidden"
            >
              <div className="p-5 border-b border-black/5 bg-amber-50/50">
                <div className="flex items-center gap-3 text-amber-600">
                  <AlertTriangle size={24} className="shrink-0" />
                  <h3 className="text-lg font-bold">{zh ? '确认覆盖授权' : 'Confirm Overwrite License'}</h3>
                </div>
              </div>
              <div className="p-5 text-sm text-black/60 space-y-3">
                <p>
                  {zh
                    ? '您当前已有生效的 License。重新上传将覆盖并替换当前系统的授权状态。'
                    : 'You already have a valid License. Uploading a new one will overwrite and replace the current authorization.'}
                </p>
                <p className="font-medium text-black/80">
                  {zh ? '您确定要继续吗？' : 'Do you wish to continue?'}
                </p>
              </div>
              <div className="p-4 bg-black/[0.02] border-t border-black/5 flex justify-end gap-2">
                <button
                  onClick={() => setShowConfirm(false)}
                  className="px-4 py-2 rounded-lg text-xs font-semibold text-black/60 hover:bg-black/5 transition-colors"
                >
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button
                  onClick={() => {
                    setShowConfirm(false);
                    fileInputRef.current?.click();
                  }}
                  className="px-4 py-2 rounded-lg text-xs font-semibold bg-amber-500 text-white hover:bg-amber-600 shadow-sm shadow-amber-500/20 transition-all"
                >
                  {zh ? '确认覆盖并上传' : 'Confirm & Upload'}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default LicenseAdminTab;
