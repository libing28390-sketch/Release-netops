import React, { useMemo, useState } from 'react';
import { Activity, CheckCircle2, Database, Search, ShieldCheck, X } from 'lucide-react';
import PageHero from '../components/PageHero';
import { LiveWalkInspector } from '../components/SnmpMib/components/LiveWalkInspector';
import CmdbDevicePicker, { type CmdbDeviceCandidate } from '../components/SnmpMib/CmdbDevicePicker';
import MibNodeBrowser from '../components/SnmpMib/MibNodeBrowser';
import { useEscapeClose } from '../hooks/useEscapeClose';

interface SnmpWalkPageProps {
  language: 'zh' | 'en';
  currentUserRole?: string;
  showToast: (message: string, type?: string) => void;
}

const DEFAULT_DIAGNOSTIC_OID = '1.3.6.1.2.1.1';

const SnmpWalkPage: React.FC<SnmpWalkPageProps> = ({ language, currentUserRole, showToast }) => {
  const zh = language === 'zh';
  const canRunWalk = ['administrator', 'operator'].includes(String(currentUserRole || '').trim().toLowerCase());
  const initialIp = useMemo(() => {
    try {
      return new URLSearchParams(window.location.search).get('ip') || '';
    } catch {
      return '';
    }
  }, []);
  const [selectedTarget, setSelectedTarget] = useState<CmdbDeviceCandidate | null>(null);
  const [devicePickerOpen, setDevicePickerOpen] = useState(false);
  const [mibCatalogOpen, setMibCatalogOpen] = useState(false);
  const [walkOid, setWalkOid] = useState(DEFAULT_DIAGNOSTIC_OID);
  const targetIp = selectedTarget?.ip_address || initialIp;
  const inspectorKey = selectedTarget
    ? `device:${selectedTarget.device_id}:${selectedTarget.ip_address || ''}`
    : `ip:${initialIp}`;

  useEscapeClose(mibCatalogOpen, () => setMibCatalogOpen(false));

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

  const handleSelectOid = (oid: string, nodeName?: string) => {
    setWalkOid(oid);
    showToast(
      zh ? `已将 ${nodeName || 'OID'} 填入 Walk：${oid}` : `Loaded ${nodeName || 'OID'} into Walk: ${oid}`,
      'success',
    );
    document.getElementById('snmp-walk-diagnostic-tool')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <>
    <div className="flex h-full min-h-0 flex-col overflow-hidden" style={{ background: 'var(--main-bg)' }}>
      <PageHero
        icon={Activity}
        title={zh ? 'SNMP 诊断' : 'SNMP Diagnostics'}
        subtitle={zh
          ? '确认设备、凭据和 OID 是否正常返回，再判断 Grafana 无数据发生在哪一层。'
          : 'Verify the device, credentials, and OID responses to locate where Grafana data is missing.'}
      />
      <div className="min-h-0 flex-1 overflow-y-auto p-4 md:p-5">
        <div className="mx-auto w-full max-w-[1680px] space-y-3.5 2xl:max-w-[1760px]">
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-sky-200/90 bg-gradient-to-r from-sky-50 to-white px-4 py-3 text-sky-950 shadow-sm dark:border-sky-900/70 dark:from-sky-950/35 dark:to-slate-900/60 dark:text-sky-100">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sky-100 text-sky-700 dark:bg-sky-900/60 dark:text-sky-300">
              <ShieldCheck size={17} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-xs font-semibold">{zh ? '诊断思路' : 'Diagnostic flow'}</div>
              <p className="mt-0.5 text-[11px] leading-5 text-sky-900/75 dark:text-sky-100/75">
                {zh
                  ? '选择目标设备后，依次检查 SYS、IF-MIB 和 LLDP；这些公共 OID 有数据但 Grafana 无数据时，再检查采集链路和面板查询。'
                  : 'Choose a device, then check SYS, IF-MIB, and LLDP. If these standard OIDs return data but Grafana does not, inspect the scrape path and panel query.'}
              </p>
            </div>
            <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-sky-200/80 bg-white/80 px-2.5 py-1 text-[10px] font-medium text-sky-800/80 dark:border-sky-800 dark:bg-sky-950/60 dark:text-sky-200/80">
              <ShieldCheck size={11} />
              {zh ? '只读探测 · 凭据保留在服务端' : 'Read-only · credentials stay server-side'}
            </span>
          </div>

          {!canRunWalk ? (
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
                      {zh ? '指定探测目标；SNMP 凭据由服务端从 CMDB 读取。' : 'Sets the probe target; SNMP credentials are read from CMDB on the server.'}
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
                  initialWalkOid={walkOid}
                  selectedDevice={selectedTarget || undefined}
                  candidateDevices={[]}
                  showCandidateSelector={false}
                  showHardwareValidationTab={false}
                  diagnosticPresetOnly
                  hideMaxRowsSelector
                  publicSummaryOnly
                  metrics={[]}
                  initialTab="snmpwalk"
                  showToast={showToast}
                />
              </div>

              <section className="overflow-hidden rounded-xl border border-black/8 bg-[var(--card-bg)] shadow-sm dark:border-white/10">
                <button
                  type="button"
                  onClick={() => setMibCatalogOpen(true)}
                  aria-haspopup="dialog"
                  className="flex w-full items-center justify-between gap-4 px-4 py-3.5 text-left transition hover:bg-violet-500/[.025] dark:hover:bg-violet-400/[.04]"
                >
                  <span className="flex min-w-0 items-center gap-2.5">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-violet-500/10 text-violet-700 dark:text-violet-300"><Database size={17} /></span>
                    <span className="min-w-0">
                      <span className="flex items-center gap-2 text-sm font-semibold text-black/80 dark:text-white/85">
                        {zh ? '高级 OID 查找' : 'Advanced OID lookup'}
                        <span className="rounded-full bg-violet-500/10 px-2 py-0.5 text-[9px] font-medium text-violet-700 dark:text-violet-300">{zh ? '可选' : 'Optional'}</span>
                      </span>
                      <span className="mt-0.5 block truncate text-[11px] text-black/45 dark:text-white/45">{zh ? '查找快捷项以外的公共或厂商 OID；选择后填入第 2 步，不会立即执行。' : 'Find additional standard or vendor OIDs; selection fills step 2 without running it.'}</span>
                    </span>
                  </span>
                  <span className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-violet-500/20 bg-violet-500/[.06] px-3 py-2 text-xs font-semibold text-violet-700 transition hover:bg-violet-500/10 dark:text-violet-300">
                    <Search size={13} />
                    {zh ? '查找 OID' : 'Find OID'}
                  </span>
                </button>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
    {mibCatalogOpen && (
      <div
        className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/55 p-3 backdrop-blur-sm sm:p-5"
        role="dialog"
        aria-modal="true"
        aria-labelledby="snmp-mib-search-title"
        onClick={event => {
          if (event.target === event.currentTarget) setMibCatalogOpen(false);
        }}
      >
        <div className="flex max-h-[calc(100vh-1.5rem)] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-white/60 bg-white shadow-2xl shadow-slate-950/25 dark:border-slate-700 dark:bg-slate-900 sm:max-h-[calc(100vh-2.5rem)]">
          <div className="flex items-start justify-between gap-4 border-b border-black/7 px-5 py-4 dark:border-white/8 sm:px-6">
            <div className="flex min-w-0 items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-violet-500/10 text-violet-700 dark:text-violet-300"><Database size={18} /></span>
              <div className="min-w-0">
                <h2 id="snmp-mib-search-title" className="text-base font-semibold text-black/85 dark:text-white/90">{zh ? '高级 OID 查找' : 'Advanced OID lookup'}</h2>
                <p className="mt-1 text-xs leading-5 text-black/50 dark:text-white/50">{zh ? '搜索公共标准或厂商私有 MIB。选择 OID 后会填入第 2 步；探测需要手动执行。' : 'Search standard or vendor MIBs. Selecting an OID fills step 2; run the probe when ready.'}</p>
              </div>
            </div>
            <button type="button" onClick={() => setMibCatalogOpen(false)} aria-label={zh ? '关闭 OID 查找' : 'Close OID lookup'} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-black/45 transition hover:bg-black/[.05] hover:text-black/80 dark:text-white/45 dark:hover:bg-white/[.08] dark:hover:text-white/85">
              <X size={17} />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
            <MibNodeBrowser
              language={language}
              deviceId={selectedTarget?.device_id}
              assetVendor={selectedTarget?.vendor}
              showHeader={false}
              pageSize={10}
              onSelectOid={(oid, node) => {
                setMibCatalogOpen(false);
                handleSelectOid(oid, node.node_name);
              }}
            />
          </div>
        </div>
      </div>
    )}
    </>
  );
};

export default SnmpWalkPage;
