import React from 'react';
import { Activity, BookOpenCheck, ShieldCheck } from 'lucide-react';

interface SnmpMetricTemplatesTabProps {
  language: string;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
}

const PINNED_LIBRENMS_COMMIT = '6c26b4fe4a40f7b392c19c36a44257212736e38c';

const SnmpMetricTemplatesTab: React.FC<SnmpMetricTemplatesTabProps> = ({ language }) => {
  const zh = language === 'zh';

  return (
    <div className="flex h-full min-h-0 flex-col p-4 md:p-6" style={{ background: 'var(--main-bg)' }}>
      <div className="mx-auto w-full max-w-5xl space-y-5">
        <header>
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">
            {zh ? 'LibreNMS 采集规则' : 'LibreNMS Collection Rules'}
          </h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {zh
              ? 'SNMP 指标不再由本地厂商模板维护；所有受支持设备都按固定版本的 LibreNMS 规则探测。'
              : 'SNMP metrics are no longer configured with local vendor templates. Supported devices are probed from a pinned LibreNMS rule bundle.'}
          </p>
        </header>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
          <div className="flex items-start gap-3">
            <div className="rounded-lg bg-cyan-500/10 p-2 text-cyan-700 dark:text-cyan-300">
              <BookOpenCheck size={20} />
            </div>
            <div className="min-w-0 flex-1">
              <h2 className="font-semibold text-slate-900 dark:text-white">
                {zh ? '固定上游规则包' : 'Pinned upstream rule bundle'}
              </h2>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                {zh ? 'LibreNMS commit' : 'LibreNMS commit'}
              </p>
              <code className="mt-2 block break-all rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                {PINNED_LIBRENMS_COMMIT}
              </code>
            </div>
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-2">
            <div className="flex gap-2 rounded-lg border border-emerald-200 bg-emerald-50/70 p-3 text-xs text-emerald-900 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200">
              <ShieldCheck size={15} className="mt-0.5 shrink-0" />
              <span>{zh ? '规则来源与文件哈希经过固定版本校验。没有对应 LibreNMS 规则的指标会保持未支持，不会回退到本地 OID。' : 'Rule sources and file hashes are checked against the pinned version. Metrics without a matching LibreNMS rule remain unsupported and are not replaced with local OIDs.'}</span>
            </div>
            <div className="flex gap-2 rounded-lg border border-sky-200 bg-sky-50/70 p-3 text-xs text-sky-900 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-200">
              <Activity size={15} className="mt-0.5 shrink-0" />
              <span>{zh ? 'SNMP-WALK 诊断同样只执行该规则包定义的探测，并显示命中的设备规则和来源文件。' : 'SNMP-WALK diagnostics use the same rule bundle and show the matched device rule and source file.'}</span>
            </div>
          </div>

          <a
            href="/monitor/snmp-walk"
            className="mt-5 inline-flex items-center gap-2 rounded-lg bg-cyan-700 px-3.5 py-2 text-sm font-semibold text-white hover:bg-cyan-800 dark:bg-cyan-600 dark:hover:bg-cyan-500"
          >
            {zh ? '打开 SNMP 规则诊断' : 'Open SNMP rule diagnostics'}
          </a>
        </section>
      </div>
    </div>
  );
};

export default SnmpMetricTemplatesTab;
