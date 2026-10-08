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
          ? '设备识别、硬件发现和即时诊断统一执行固定版本的 LibreNMS 规则。'
          : 'Device identification, hardware discovery, and on-demand diagnostics all use the pinned LibreNMS rules.'}
      />
      <div className="min-h-0 flex-1 overflow-y-auto p-4 md:p-5">
        <div className="mx-auto w-full max-w-[1680px] space-y-3.5 2xl:max-w-[1760px]">
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-sky-200/90 bg-gradient-to-r from-sky-50 to-white px-4 py-3 text-sky-950 shadow-sm dark:border-sky-900/70 dark:from-sky-950/35 dark:to-slate-900/60 dark:text-sky-100">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sky-100 text-sky-700 dark:bg-sky-900/60 dark:text-sky-300">
              <ShieldCheck size={17} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-xs font-semibold">{zh ? '统一规则来源' : 'Single rule source'}</div>
              <p className="mt-0.5 text-[11px] leading-5 text-sky-900/75 dark:text-sky-100/75">
                {zh
                  ? '诊断不再接受任意 OID、厂商快捷项或自定义预设；服务端按设备身份匹配 LibreNMS 规则，并展示命中规则及源文件。'
                  : 'Diagnostics no longer accept arbitrary OIDs, vendor shortcuts, or custom presets. The server matches LibreNMS rules to device identity and shows the matched source file.'}
              </p>
            </div>
            <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-sky-200/80 bg-white/80 px-2.5 py-1 text-[10px] font-medium text-sky-800/80 dark:border-sky-800 dark:bg-sky-950/60 dark:text-sky-200/80">
              <ShieldCheck size={11} />
              {zh ? '只读探测 · 凭据保留在服务端' : 'Read-only · credentials stay server-side'}
            </span>
          </div>

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
                      {zh ? '指定 CMDB 设备；凭据和探测 OID 均由服务端及 LibreNMS 规则确定。' : 'Select a CMDB device; credentials and probe OIDs are resolved server-side from LibreNMS rules.'}
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
                  initialTab="snmpwalk"
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
