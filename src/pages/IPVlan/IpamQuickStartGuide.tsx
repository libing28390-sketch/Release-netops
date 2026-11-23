import React, { useState } from 'react';
import { BookOpen, ChevronDown, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

const STORAGE_KEY = 'nexora.ipam.quickstart.collapsed';

interface IpamQuickStartGuideProps {
  zh: boolean;
  /** Registered prefixes visible in the current scope. */
  prefixCount: number;
  /** Registered IPAM ledger rows in the current scope. */
  addressCount: number;
  /** Discovered endpoints not yet in the ledger (when known). */
  discoveredCount?: number;
  loading?: boolean;
}

interface GuideStep {
  key: string;
  zhTitle: string;
  enTitle: string;
  zhBody: string;
  enBody: string;
  path: string;
  zhAction: string;
  enAction: string;
  done?: boolean;
}

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

function writeCollapsed(value: boolean) {
  try {
    window.localStorage.setItem(STORAGE_KEY, value ? '1' : '0');
  } catch {
    /* storage unavailable: keep in-memory state only */
  }
}

/**
 * First-run guide for the IPAM workspace: explains the workflow
 * (prefix -> address ledger -> discovered endpoints -> reconciliation)
 * and the difference between formal ledger rows and collected observations.
 */
export default function IpamQuickStartGuide({
  zh, prefixCount, addressCount, discoveredCount, loading = false,
}: IpamQuickStartGuideProps) {
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState<boolean>(readCollapsed);

  const toggle = (value: boolean) => {
    setCollapsed(value);
    writeCollapsed(value);
  };

  const steps: GuideStep[] = [
    {
      key: 'prefixes',
      zhTitle: '1. 建网段',
      enTitle: '1. Create prefixes',
      zhBody: '在“网段”页点击“从接口 IP 生成”，把设备上已配置的接口网段一键导入；也可手动“新增网段”。',
      enBody: 'On Prefixes, use “Generate from interface IPs” to import configured interface networks, or add one manually.',
      path: '/ipam/prefixes',
      zhAction: '去网段',
      enAction: 'Open Prefixes',
      done: prefixCount > 0,
    },
    {
      key: 'addresses',
      zhTitle: '2. 管理 IP 台账',
      enTitle: '2. Manage the IP ledger',
      zhBody: '就在本页：先选站点和网段，再“分配 IP 地址”；行尾可编辑用途、状态、备注。切到“矩阵”可看整段占用。',
      enBody: 'This page: choose a site and prefix, then “Allocate IP”. Edit purpose/status per row; use “Matrix” to see a whole prefix.',
      path: '/ipam/ips',
      zhAction: '就在本页',
      enAction: 'You are here',
      done: addressCount > 0,
    },
    {
      key: 'endpoints',
      zhTitle: '3. 登记发现终端',
      enTitle: '3. Register discovered endpoints',
      zhBody: '系统通过 ARP / MAC / LLDP 采集到的服务器、终端会出现在“发现终端”，确认后点“登记”即进入正式台账。',
      enBody: 'Servers and hosts found via ARP/MAC/LLDP appear in Discovered Endpoints; register them to add them to the ledger.',
      path: '/ipam/endpoints',
      zhAction: '去登记',
      enAction: 'Open Endpoints',
      done: discoveredCount === 0 ? true : undefined,
    },
    {
      key: 'reconciliation',
      zhTitle: '4. 对账与利用率',
      enTitle: '4. Reconcile & watch usage',
      zhBody: '“IP 对账”列出台账与现网不一致的地址（漏登记、已下线、冲突）；“利用率”查看各网段剩余容量。',
      enBody: 'Reconciliation lists ledger vs. network mismatches; Utilization shows remaining capacity per prefix.',
      path: '/ipam/reconciliation',
      zhAction: '去对账',
      enAction: 'Open Reconciliation',
    },
    {
      key: 'locate',
      zhTitle: '5. 排障定位',
      enTitle: '5. Troubleshoot',
      zhBody: '在“IP 定位”输入 IP 或 MAC，查出它接在哪台交换机的哪个端口；在表格中点击 IP 可打开详情，再一键定位。',
      enBody: 'IP Locator finds the switch port behind an IP or MAC; click an IP in the table to open its detail and locate it.',
      path: '/ipam/locate',
      zhAction: '去定位',
      enAction: 'Open Locator',
    },
  ];

  if (collapsed) {
    return (
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => toggle(false)}
          className="inline-flex items-center gap-1.5 rounded-xl border border-cyan-200/80 bg-cyan-50/70 px-3 py-1.5 text-[11px] font-semibold text-cyan-700 transition-colors hover:bg-cyan-100/80 dark:border-cyan-900/60 dark:bg-cyan-950/40 dark:text-cyan-300 cursor-pointer"
          aria-expanded={false}
        >
          <BookOpen size={13} />
          {zh ? 'IPAM 使用指引' : 'IPAM quick start'}
          <ChevronDown size={13} />
        </button>
      </div>
    );
  }

  return (
    <section
      aria-label={zh ? 'IPAM 使用指引' : 'IPAM quick start'}
      className="rounded-2xl border border-cyan-200/70 bg-gradient-to-br from-cyan-50/80 to-white px-4 py-3 shadow-2xs dark:border-cyan-900/50 dark:from-cyan-950/30 dark:to-zinc-900"
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-1.5 text-xs font-bold text-cyan-800 dark:text-cyan-300">
            <BookOpen size={14} />
            {zh ? 'IPAM 怎么用：5 步建立并维护地址台账' : 'How IPAM works: 5 steps'}
          </h2>
          <p className="mt-1 text-[11px] leading-4 text-slate-600 dark:text-zinc-400">
            {zh
              ? '“正式台账”是人工确认过的地址记录（可编辑、参与分配与冲突检查）；“采集观察”只是设备上看到的事实，需登记后才进入台账。标记“推断”的用途/类型由系统根据接口名、掩码、设备管理 IP 自动判断，编辑保存后即固定。'
              : 'The formal ledger holds confirmed records; collected observations become ledger rows only after registration. Values marked “inferred” are derived from interface name, mask or device management IP until you edit them.'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => toggle(true)}
          className="shrink-0 rounded-lg p-1 text-slate-400 transition-colors hover:bg-white hover:text-slate-600 dark:hover:bg-zinc-800 cursor-pointer"
          aria-label={zh ? '收起使用指引' : 'Collapse quick start'}
          title={zh ? '收起（可随时从右上角重新展开）' : 'Collapse'}
        >
          <span className="sr-only">{zh ? '收起' : 'Collapse'}</span>
          <X size={14} />
        </button>
      </div>
      <ol className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-5">
        {steps.map((step) => (
          <li
            key={step.key}
            className={`flex min-w-0 flex-col justify-between gap-2 rounded-xl border px-3 py-2 ${
              step.done
                ? 'border-emerald-200 bg-emerald-50/60 dark:border-emerald-900/50 dark:bg-emerald-950/20'
                : 'border-slate-200/80 bg-white/80 dark:border-zinc-800 dark:bg-zinc-900/70'
            }`}
          >
            <div className="min-w-0">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-bold text-slate-800 dark:text-zinc-100">{zh ? step.zhTitle : step.enTitle}</span>
                {step.done && !loading && (
                  <span className="shrink-0 rounded-full bg-emerald-100 px-1.5 py-0.5 text-[9px] font-bold text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300">
                    {zh ? '已完成' : 'Done'}
                  </span>
                )}
              </div>
              <p className="mt-1 text-[10px] leading-4 text-slate-600 dark:text-zinc-400">{zh ? step.zhBody : step.enBody}</p>
            </div>
            {step.path !== '/ipam/ips' ? (
              <button
                type="button"
                onClick={() => navigate(step.path)}
                className="self-start rounded-lg border border-cyan-200/80 bg-cyan-50 px-2 py-1 text-[10px] font-semibold text-cyan-700 transition-colors hover:bg-cyan-100 dark:border-cyan-900/60 dark:bg-cyan-950/40 dark:text-cyan-300 cursor-pointer"
              >
                {zh ? step.zhAction : step.enAction} →
              </button>
            ) : (
              <span className="self-start text-[10px] font-semibold text-[var(--ui-fg-muted)]">{zh ? step.zhAction : step.enAction}</span>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
