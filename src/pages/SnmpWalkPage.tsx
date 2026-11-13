import React, { useMemo, useState } from 'react';
import { Activity, CheckCircle2, Search, ShieldCheck } from 'lucide-react';
import PageHero from '../components/PageHero';
import { LiveWalkInspector } from '../components/SnmpMib/components/LiveWalkInspector';
import CmdbDevicePicker, { type CmdbDeviceCandidate } from '../components/SnmpMib/CmdbDevicePicker';

interface SnmpWalkPageProps {
  language: 'zh' | 'en';
  currentUserRole?: string;
  showToast: (message: string, type?: string) => void;
}

const SnmpWalkPage: React.FC<SnmpWalkPageProps> = ({ language, currentUserRole, showToast }) => {
  const zh = language === 'zh';
  const canRunProbe = ['administrator', 'operator'].includes(String(currentUserRole || '').trim().toLowerCase());
  const initialIp = useMemo(() => {
    try {
      return new URLSearchParams(window.location.search).get('ip') || '';
    } catch {
      return '';
    }
  }, []);
  const [selectedTarget, setSelectedTarget] = useState<CmdbDeviceCandidate | null>(null);
  const [devicePickerOpen, setDevicePickerOpen] = useState(false);
  const targetIp = selectedTarget?.ip_address || initialIp;
  const inspectorKey = selectedTarget
    ? `device:${selectedTarget.device_id}:${selectedTarget.ip_address || ''}`
    : `ip:${initialIp}`;

  const handleSelectTarget = (device: CmdbDeviceCandidate) => {
    setSelectedTarget(device);
    setDevicePickerOpen(false);
    showToast(
      zh
        ? `已选择 ${device.hostname}${device.ip_address ? `（${device.ip_address}）` : ''}`
        : `Selected ${device.hostname}${device.ip_address ? ` (${device.ip_address})` : ''}`,
      'info',
    );
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden" style={{ background: 'var(--main-bg)' }}>
      <PageHero
        icon={Activity}
        title={zh ? 'SNMP 诊断' : 'SNMP Diagnostics'}
        subtitle={zh
          ? '查看设备系统信息、LLDP 邻居和硬件规则诊断。'
          : 'View device system information, LLDP neighbors, and hardware rule diagnostics.'}
      />
      <div className="min-h-0 flex-1 overflow-y-auto p-4 md:p-5">
        <div className="mx-auto w-full max-w-[1680px] space-y-3.5 2xl:max-w-[1760px]">
          <section className="rounded-xl border border-sky-200/90 bg-gradient-to-r from-sky-50 to-white px-4 py-3.5 text-sky-950 shadow-sm dark:border-sky-900/70 dark:from-sky-950/35 dark:to-slate-900/60 dark:text-sky-100">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex min-w-0 items-start gap-2.5">
                <ShieldCheck size={17} className="mt-0.5 shrink-0 text-sky-700 dark:text-sky-300" />
                <div className="min-w-0">
                  <h2 className="text-xs font-semibold">{zh ? '三步完成设备诊断' : 'Device diagnostics in three steps'}</h2>
                  <p className="mt-0.5 text-[11px] leading-5 text-sky-900/70 dark:text-sky-100/70">
                    {zh ? '只读查询标准系统信息和 LLDP 邻居；不会修改设备配置。凭据由服务端从设备档案读取。' : 'Read standard system information and LLDP neighbors without changing device configuration. Credentials are resolved server-side.'}
                  </p>
                </div>
              </div>
              <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-sky-200/80 bg-white/80 px-2.5 py-1 text-[10px] font-medium text-sky-800/80 dark:border-sky-800 dark:bg-sky-950/60 dark:text-sky-200/80">
                <ShieldCheck size={11} />
                {zh ? '安全只读' : 'Read-only'}
              </span>
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-3">
              <div className="flex items-center gap-2 rounded-lg border border-sky-200/60 bg-white/65 px-2.5 py-2 text-[10px] dark:border-sky-900/60 dark:bg-black/10">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-sky-100 font-semibold text-sky-800 dark:bg-sky-900/70 dark:text-sky-200">1</span>
                <span>{zh ? '选择已纳管设备' : 'Choose a managed device'}</span>
              </div>
              <div className="flex items-center gap-2 rounded-lg border border-sky-200/60 bg-white/65 px-2.5 py-2 text-[10px] dark:border-sky-900/60 dark:bg-black/10">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-sky-100 font-semibold text-sky-800 dark:bg-sky-900/70 dark:text-sky-200">2</span>
                <span>{zh ? '查询系统信息与 LLDP' : 'Query system information and LLDP'}</span>
              </div>
              <div className="flex items-center gap-2 rounded-lg border border-sky-200/60 bg-white/65 px-2.5 py-2 text-[10px] dark:border-sky-900/60 dark:bg-black/10">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-sky-100 font-semibold text-sky-800 dark:bg-sky-900/70 dark:text-sky-200">3</span>
                <span>{zh ? '按需展开技术详情' : 'Expand technical details when needed'}</span>
              </div>
            </div>
          </section>

          {!canRunProbe ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/25 dark:text-amber-200">
              {zh ? 'SNMP 诊断需要 Operator 或 Administrator 权限。' : 'SNMP diagnostics require Operator or Administrator access.'}
            </div>
          ) : (
            <>
              <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#00bceb]/20 bg-[var(--card-bg)] px-4 py-3.5 shadow-sm dark:border-[#00bceb]/20">
                <div className="flex min-w-0 items-center gap-3">
                  <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold ${selectedTarget ? 'bg-emerald-500/12 text-emerald-700 dark:text-emerald-300' : 'bg-[#00bceb]/12 text-[#007391] dark:text-[#00c2e8]'}`}>1</span>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-sm font-semibold text-black/85 dark:text-white/90">{zh ? '选择诊断设备' : 'Choose a device'}</h2>
                      {selectedTarget ? (
                        <span className="inline-flex min-w-0 items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-1 text-[10px] font-medium text-emerald-700 dark:text-emerald-300">
                          <CheckCircle2 size={12} className="shrink-0" />
                          <span className="truncate">{selectedTarget.hostname} · {selectedTarget.ip_address || '—'}</span>
                        </span>
                      ) : initialIp ? (
                        <span className="rounded-full bg-slate-500/10 px-2.5 py-1 font-mono text-[10px] text-slate-600 dark:text-slate-300">{initialIp}</span>
                      ) : (
                        <span className="text-[10px] text-amber-700 dark:text-amber-300">{zh ? '尚未选择' : 'Not selected'}</span>
                      )}
                    </div>
                    <p className="mt-1 text-[11px] leading-4 text-black/50 dark:text-white/50">
                      {zh ? '系统信息与邻居数据通过只读诊断查询。' : 'System and neighbor data are queried through read-only diagnostics.'}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setDevicePickerOpen(true)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-black/10 bg-white/70 px-3.5 py-2 text-xs font-semibold text-black/65 transition hover:border-[#00bceb]/40 hover:bg-[#00bceb]/[.05] dark:border-white/10 dark:bg-white/[.04] dark:text-white/75 dark:hover:border-[#00bceb]/40 dark:hover:bg-[#00bceb]/[.08]"
                >
                  <Search size={13} />
                  {selectedTarget || initialIp ? (zh ? '更换设备' : 'Change device') : (zh ? '选择设备' : 'Choose device')}
                </button>
              </section>
              <CmdbDevicePicker
                open={devicePickerOpen}
                onClose={() => setDevicePickerOpen(false)}
                language={language}
                initialQuery={selectedTarget ? '' : initialIp}
                selectedDeviceId={selectedTarget?.device_id}
                onSelect={handleSelectTarget}
              />

              <div id="snmp-walk-diagnostic-tool" className="scroll-mt-3">
                <LiveWalkInspector
                  key={inspectorKey}
                  zh={zh}
                  initialIp={targetIp}
                  selectedDevice={selectedTarget || undefined}
                  candidateDevices={[]}
                  showCandidateSelector={false}
                  showHardwareValidationTab
                  showSystemInfoTab
                  initialTab="system"
                  showToast={showToast}
                />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default SnmpWalkPage;
