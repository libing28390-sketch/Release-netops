import React, { useEffect, useState } from 'react';
import { History, LoaderCircle, MapPin, Network, Pencil, Radar, RefreshCw, Server, X, type LucideIcon } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { useNavigate } from 'react-router-dom';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import {
  formatLivenessAge,
  formatLivenessWindow,
  interfaceLivenessSourceLabel,
  type InterfaceLiveness,
} from './interfaceLiveness';
import { formatMacAddress } from '../../utils/resourceFormatters';
import { formatIPAddressLocalTime } from './ipAddressTablePresentation';

/** Minimal row shape the table already has; used until the detail request returns. */
export interface IPAddressDetailSeed {
  id: string;
  address: string;
  status?: string;
  purpose?: string;
  device_type?: string;
  classification_inferred?: boolean;
  subnet_id?: string;
  subnet_prefix?: string;
  site_name?: string;
  hostname?: string;
  interface_name?: string;
  description?: string;
}

interface DetailAddress extends IPAddressDetailSeed {
  revision?: number;
  device_id?: string;
  subnet_name?: string;
  network_type?: string;
  prefix_gateway?: string;
  prefix_status?: string;
  vrf_name?: string;
  mac_address?: string;
  source_type?: string;
  created_at?: string;
  updated_at?: string;
  last_seen?: string;
  expires_at?: string;
  requested_by?: string;
  bound_device_hostname?: string;
  bound_device_ip?: string;
  device_platform?: string;
  device_model?: string;
  device_role?: string;
  device_status?: string;
  asset_tag?: string;
  asset_serial_number?: string;
  asset_vendor?: string;
  asset_model?: string;
  interface_mac?: string;
  interface_mac_source?: 'snmp_ifmib' | 'neighbor_arp' | string;
  interface_mac_conflict?: string[];
  interface_liveness?: InterfaceLiveness;
}

interface DetailInterface {
  interface_name?: string;
  description?: string;
  admin_status?: string;
  oper_status?: string;
  mac_address?: string;
  interface_type?: string;
  speed?: number;
  mtu?: number;
  access_vlan?: number | null;
  source?: 'cli_snapshot' | string;
  observed_at?: string;
}

interface DetailDiscovery {
  mac?: string;
  hostname?: string;
  vendor?: string;
  switch_name?: string;
  switch_port?: string;
  vlan?: string;
  source_type?: string;
  first_seen?: string;
  last_seen?: string;
  is_active?: number | boolean;
  freshness?: 'recent' | 'historical' | 'unknown';
  age_minutes?: number | null;
  window_minutes?: number;
  evidence_source?: 'current_observation' | 'legacy_cache' | string;
}

interface DetailSameIp {
  id: string;
  status?: string;
  hostname?: string;
  subnet_prefix?: string;
  site_name?: string;
  same_routing_domain?: boolean;
}

interface DetailHistoryItem {
  id: string;
  event_type?: string;
  summary?: string;
  actor_username?: string;
  created_at?: string;
  changes?: { field: string; before: unknown; after: unknown }[];
}

interface AddressDetailResponse {
  address: DetailAddress;
  interface: DetailInterface | null;
  discovery: DetailDiscovery[];
  same_ip_elsewhere: DetailSameIp[];
  history: DetailHistoryItem[];
}

interface IPAddressDetailDrawerProps {
  zh: boolean;
  seed: IPAddressDetailSeed | null;
  authHeaders: () => HeadersInit;
  onClose: () => void;
  onEdit?: (seed: IPAddressDetailSeed) => void;
  /** Called after an on-demand SNMP refresh so the list can reload observed values. */
  onDataChanged?: () => void;
  statusLabel: (status: string, zh: boolean) => string;
  purposeLabel: (purpose: string, zh: boolean) => string;
  roleLabel: (role: string, zh: boolean) => string;
}

const FIELD_LABELS: Record<string, [string, string]> = {
  status: ['状态', 'Status'],
  purpose: ['用途', 'Purpose'],
  device_type: ['类型', 'Type'],
  hostname: ['主机名', 'Hostname'],
  description: ['备注', 'Description'],
  device_id: ['关联设备', 'Device'],
  interface_name: ['接口', 'Interface'],
  interface_id: ['接口 ID', 'Interface ID'],
  mac_address: ['MAC', 'MAC'],
  expires_at: ['到期时间', 'Expires'],
  pool_id: ['地址池', 'Pool'],
  address: ['地址', 'Address'],
};

const text = (value: unknown): string => {
  if (value === null || value === undefined || value === '') return '—';
  return String(value);
};

function formatAge(minutes: number | null | undefined, zh: boolean): string {
  if (minutes === null || minutes === undefined || Number.isNaN(minutes)) return zh ? '未知时间' : 'unknown';
  if (minutes < 60) return zh ? `${minutes} 分钟` : `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return zh ? `${hours} 小时` : `${hours} h`;
  return zh ? `${Math.floor(hours / 24)} 天` : `${Math.floor(hours / 24)} d`;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] gap-2 py-1 text-xs">
      <dt className="text-[var(--ui-fg-muted)]">{label}</dt>
      <dd className="min-w-0 break-words font-medium text-[var(--ui-fg)]">{children}</dd>
    </div>
  );
}

function Section({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200/80 bg-white/80 px-4 py-3 dark:border-zinc-800 dark:bg-zinc-900/70">
      <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-bold text-slate-800 dark:text-zinc-100">
        <Icon size={13} className="text-cyan-600" />
        {title}
      </h3>
      {children}
    </section>
  );
}

export default function IPAddressDetailDrawer({
  zh, seed, authHeaders, onClose, onEdit, onDataChanged, statusLabel, purposeLabel, roleLabel,
}: IPAddressDetailDrawerProps) {
  const navigate = useNavigate();
  const [detail, setDetail] = useState<AddressDetailResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [reloadVersion, setReloadVersion] = useState(0);
  const [snmpRefreshing, setSnmpRefreshing] = useState(false);
  const [snmpMessage, setSnmpMessage] = useState<{ tone: 'success' | 'error'; text: string } | null>(null);
  useEscapeClose(Boolean(seed), onClose);

  useEffect(() => {
    setSnmpMessage(null);
  }, [seed?.id]);

  const refreshInterfacesViaSnmp = async (deviceId: string) => {
    if (snmpRefreshing) return;
    setSnmpRefreshing(true);
    setSnmpMessage(null);
    try {
      const response = await fetch(`/api/cmdb/devices/${encodeURIComponent(deviceId)}/interfaces/snmp-refresh`, {
        method: 'POST',
        headers: authHeaders(),
      });
      const payload = await response.json().catch(() => ({})) as { detail?: unknown; data?: { interface_count?: number; mac_count?: number } };
      if (!response.ok) {
        const detailText = typeof payload.detail === 'string' ? payload.detail : '';
        setSnmpMessage({
          tone: 'error',
          text: response.status === 403
            ? (zh ? '当前账号没有刷新接口表的权限（需要 Operator）。' : 'Operator role required.')
            : detailText || (zh ? `SNMP 读取失败（HTTP ${response.status}）。` : `SNMP refresh failed (HTTP ${response.status}).`),
        });
        return;
      }
      const count = payload.data?.interface_count ?? 0;
      const macs = payload.data?.mac_count ?? 0;
      setSnmpMessage({
        tone: 'success',
        text: zh ? `已通过 SNMP 读取 ${count} 个接口，其中 ${macs} 个有 MAC。` : `Read ${count} interfaces via SNMP (${macs} with MAC).`,
      });
      setReloadVersion((version) => version + 1);
      onDataChanged?.();
    } catch {
      setSnmpMessage({ tone: 'error', text: zh ? '网络请求失败，请重试。' : 'Request failed; retry.' });
    } finally {
      setSnmpRefreshing(false);
    }
  };

  useEffect(() => {
    if (reloadVersion === 0) setDetail(null);
    setError('');
    if (!seed?.id) return undefined;
    const controller = new AbortController();
    setLoading(true);
    void (async () => {
      try {
        const response = await fetch(`/api/ipam/addresses/${encodeURIComponent(seed.id)}/detail`, {
          headers: authHeaders(),
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        if (!response.ok) {
          setError(response.status === 401
            ? (zh ? '登录已失效，请刷新页面重新登录。' : 'Session expired; sign in again.')
            : response.status === 403 || response.status === 404
              ? (zh ? '该地址不存在或当前账号无权查看。' : 'Address not found or not visible to you.')
              : (zh ? `加载详情失败（HTTP ${response.status}），下方先显示列表中的信息。` : `Failed to load detail (HTTP ${response.status}).`));
          return;
        }
        setDetail(await response.json());
      } catch {
        if (!controller.signal.aborted) {
          setError(zh ? '网络请求失败，下方先显示列表中的信息。' : 'Request failed; showing list data.');
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [seed?.id, authHeaders, zh, reloadVersion]);

  const address: DetailAddress | null = detail?.address || seed;
  const iface = detail?.interface || null;
  const discovery = detail?.discovery || [];
  const sameIp = detail?.same_ip_elsewhere || [];
  const history = detail?.history || [];
  const conflicting = sameIp.filter((item) => item.same_routing_domain);

  return (
    <AnimatePresence>
      {seed && address && (
        <>
          <motion.div
            key="ip-detail-backdrop"
            className="fixed inset-0 z-40 bg-black/20"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.aside
            key="ip-detail-panel"
            role="dialog"
            aria-modal="true"
            aria-label={zh ? `IP 详情 ${address.address}` : `IP detail ${address.address}`}
            className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[460px] flex-col border-l border-slate-200 bg-[var(--ui-surface)] shadow-2xl dark:border-zinc-800"
            initial={{ x: 480 }}
            animate={{ x: 0 }}
            exit={{ x: 480 }}
            transition={{ type: 'tween', duration: 0.2 }}
          >
            <header className="flex items-start justify-between gap-3 border-b border-slate-200 px-5 py-4 dark:border-zinc-800">
              <div className="min-w-0">
                <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--ui-fg-muted)]">{zh ? 'IP 地址详情' : 'IP address detail'}</p>
                <h2 className="mt-0.5 break-all font-mono text-lg font-bold text-[var(--ui-fg)]">{address.address}</h2>
                <div className="mt-1.5 flex flex-wrap gap-1.5 text-[10px] font-bold">
                  {address.status && <span className="rounded-full border border-emerald-500/20 bg-emerald-50 px-2 py-0.5 text-emerald-700">{statusLabel(address.status, zh)}</span>}
                  {address.purpose && <span className="rounded-full border border-cyan-500/20 bg-cyan-50 px-2 py-0.5 text-cyan-700">{purposeLabel(address.purpose, zh)}</span>}
                  {address.device_type && <span className="rounded-full border border-slate-300 bg-slate-50 px-2 py-0.5 text-slate-600">{roleLabel(address.device_type, zh)}</span>}
                  {address.classification_inferred && <span className="rounded-full border border-dashed border-amber-300 bg-amber-50 px-2 py-0.5 text-amber-700" title={zh ? '用途/类型由系统根据接口名、掩码或设备管理 IP 推断；编辑保存后即固定' : 'Inferred; edit to confirm'}>{zh ? '推断' : 'Inferred'}</span>}
                </div>
              </div>
              <button type="button" onClick={onClose} aria-label={zh ? '关闭' : 'Close'} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-zinc-800 cursor-pointer">
                <X size={16} />
              </button>
            </header>

            <div className="flex flex-wrap gap-2 border-b border-slate-200 px-5 py-3 dark:border-zinc-800">
              {onEdit && (
                <button type="button" onClick={() => onEdit(seed)} className="inline-flex items-center gap-1 rounded-lg bg-cyan-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-cyan-700 cursor-pointer">
                  <Pencil size={12} />{zh ? '编辑' : 'Edit'}
                </button>
              )}
              <button type="button" onClick={() => navigate(`/ipam/locate?ip=${encodeURIComponent(address.address)}`)} className="inline-flex items-center gap-1 rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-1.5 text-xs font-semibold text-cyan-700 hover:bg-cyan-100 cursor-pointer dark:border-cyan-900/60 dark:bg-cyan-950/40 dark:text-cyan-300">
                <Radar size={12} />{zh ? '定位交换机端口' : 'Locate switch port'}
              </button>
              {address.subnet_id && (
                <button type="button" onClick={() => { onClose(); navigate(`/ipam/ips?prefix_id=${encodeURIComponent(address.subnet_id || '')}`); }} className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 cursor-pointer dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200">
                  <Network size={12} />{zh ? '查看同网段地址' : 'Same prefix'}
                </button>
              )}
            </div>

            <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
              {loading && (
                <div role="status" className="flex items-center gap-2 text-xs text-[var(--ui-fg-muted)]">
                  <LoaderCircle size={13} className="animate-spin" />{zh ? '正在加载详情…' : 'Loading detail…'}
                </div>
              )}
              {error && <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">{error}</div>}

              {conflicting.length > 0 && (
                <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
                  <p className="font-bold">{zh ? `同一路由域内还有 ${conflicting.length} 条相同 IP 的登记，可能是地址冲突` : `${conflicting.length} other records use this IP in the same routing domain`}</p>
                  <ul className="mt-1 space-y-0.5">
                    {conflicting.map((item) => (
                      <li key={item.id} className="font-mono">{item.subnet_prefix || '—'} · {item.site_name || '—'} · {item.hostname || '—'}</li>
                    ))}
                  </ul>
                </div>
              )}

              <Section icon={MapPin} title={zh ? '归属' : 'Ownership'}>
                <dl>
                  <Row label={zh ? '网段' : 'Prefix'}><span className="font-mono">{text(address.subnet_prefix)}</span>{detail?.address.subnet_name ? <span className="ml-1 text-[var(--ui-fg-muted)]">（{detail.address.subnet_name}）</span> : null}</Row>
                  <Row label={zh ? '站点' : 'Site'}>{text(address.site_name)}</Row>
                  <Row label="VRF">{detail ? (detail.address.vrf_name || (zh ? '全局（无 VRF）' : 'Global')) : '—'}</Row>
                  <Row label={zh ? '网段网关' : 'Gateway'}><span className="font-mono">{text(detail?.address.prefix_gateway)}</span></Row>
                  <Row label={zh ? '来源' : 'Source'}>{detail?.address.source_type === 'interface_collection' ? (zh ? '接口采集生成' : 'Interface collection') : detail?.address.source_type === 'manual' ? (zh ? '人工登记' : 'Manual') : text(detail?.address.source_type)}</Row>
                  <Row label={zh ? '主机名' : 'Hostname'}>{text(address.hostname)}</Row>
                  <Row label={zh ? '备注' : 'Description'}>{text(address.description)}</Row>
                  <Row label={zh ? '登记时间' : 'Created'}>{text(formatIPAddressLocalTime(detail?.address.created_at))}</Row>
                  <Row label={zh ? '最近更新' : 'Updated'}>{text(formatIPAddressLocalTime(detail?.address.updated_at))}</Row>
                  {detail?.address.expires_at ? <Row label={zh ? '到期时间' : 'Expires'}>{formatIPAddressLocalTime(detail.address.expires_at)}</Row> : null}
                </dl>
              </Section>

              <Section icon={Server} title={zh ? '设备与接口' : 'Device & interface'}>
                {detail?.address.bound_device_hostname || address.interface_name ? (
                  <dl>
                    <Row label={zh ? '设备' : 'Device'}>{text(detail?.address.bound_device_hostname)}{detail?.address.device_status ? <span className="ml-1 text-[var(--ui-fg-muted)]">· {detail.address.device_status}</span> : null}</Row>
                    <Row label={zh ? '设备管理 IP' : 'Mgmt IP'}><span className="font-mono">{text(detail?.address.bound_device_ip)}</span></Row>
                    <Row label={zh ? '型号 / 平台' : 'Model'}>{[detail?.address.device_model, detail?.address.device_platform].filter(Boolean).join(' · ') || '—'}</Row>
                    <Row label={zh ? '资产' : 'Asset'}>{[detail?.address.asset_tag, detail?.address.asset_serial_number].filter(Boolean).join(' · ') || '—'}</Row>
                    <Row label={zh ? '接口' : 'Interface'}><span className="font-mono">{text(iface?.interface_name || address.interface_name)}</span></Row>
                    {iface ? (
                      <>
                        <Row label={zh ? '接口状态' : 'State'}>{zh ? `管理 ${text(iface.admin_status)} / 运行 ${text(iface.oper_status)}` : `admin ${text(iface.admin_status)} / oper ${text(iface.oper_status)}`}</Row>
                        <Row label={zh ? '接口 MAC' : 'MAC'}>{(() => {
                          const direct = formatMacAddress(iface.mac_address || detail?.address.mac_address || '');
                          if (direct) return <span className="font-mono">{direct}</span>;
                          const observed = detail?.address.interface_mac;
                          if (observed) {
                            const sourceLabel = detail?.address.interface_mac_source === 'snmp_ifmib'
                              ? (zh ? 'SNMP 接口表（IF-MIB）' : 'SNMP IF-MIB')
                              : (zh ? '邻居设备 ARP 表' : 'neighbor ARP');
                            return <span><span className="font-mono">{formatMacAddress(observed)}</span><span className="ml-1 text-[10px] text-[var(--ui-fg-muted)]">{zh ? `来自${sourceLabel}，未写入台账` : `from ${sourceLabel}; not stored`}</span></span>;
                          }
                          const conflict = detail?.address.interface_mac_conflict || [];
                          if (conflict.length > 1) {
                            return <span className="text-amber-700">{zh ? '邻居 ARP 中有多个 MAC：' : 'Multiple MACs: '}<span className="font-mono">{conflict.map((mac) => formatMacAddress(mac)).join('、')}</span></span>;
                          }
                          const canRefresh = Boolean(detail?.address.device_id) && address.device_type !== 'loopback';
                          if (canRefresh) {
                            return (
                              <span className="flex flex-col items-start gap-1">
                                <span className="text-[var(--ui-fg-muted)]">{zh ? '—（CLI 采集不含 MAC，邻居 ARP 中也没有这个地址）' : '— (not in CLI output or neighbor ARP)'}</span>
                                <button
                                  type="button"
                                  disabled={snmpRefreshing}
                                  onClick={() => detail?.address.device_id && void refreshInterfacesViaSnmp(detail.address.device_id)}
                                  className="inline-flex items-center gap-1 rounded-lg border border-cyan-200 bg-cyan-50 px-2 py-1 text-[10px] font-semibold text-cyan-700 hover:bg-cyan-100 disabled:opacity-60 cursor-pointer dark:border-cyan-900/60 dark:bg-cyan-950/40 dark:text-cyan-300"
                                  title={zh ? '只读：通过 SNMP 读取该设备的接口表（IF-MIB），更新接口状态和 MAC，不改动 IPAM 台账' : 'Read-only SNMP IF-MIB walk'}
                                >
                                  <RefreshCw size={11} className={snmpRefreshing ? 'animate-spin' : ''} />
                                  {snmpRefreshing ? (zh ? '正在通过 SNMP 读取…' : 'Reading via SNMP…') : (zh ? '通过 SNMP 读取接口 MAC' : 'Read MAC via SNMP')}
                                </button>
                              </span>
                            );
                          }
                          return <span className="text-[var(--ui-fg-muted)]">{address.device_type === 'loopback'
                            ? (zh ? '—（Loopback 是逻辑接口，本身没有 MAC）' : '— (loopbacks have no MAC)')
                            : (zh ? '—（CLI 采集的“display interface brief”不含 MAC；邻居设备 ARP 和 SNMP 接口表中也暂无这个地址的记录）' : '— (no MAC in CLI brief output, neighbor ARP or SNMP IF-MIB)')}</span>;
                        })()}</Row>
                        <Row label={zh ? '接口描述' : 'Description'}>{text(iface.description)}</Row>
                        {snmpMessage && (
                          <p role="status" className={`mt-1 rounded-md px-2 py-1 text-[10px] ${snmpMessage.tone === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>{snmpMessage.text}</p>
                        )}
                        {iface.source === 'cli_snapshot' && (
                          <p className="mt-1 text-[10px] text-[var(--ui-fg-muted)]">{zh ? `接口状态来自 CLI 接口采集快照（采集于 ${text(formatIPAddressLocalTime(iface.observed_at))}），不是实时状态。` : `From the CLI interface snapshot (${text(formatIPAddressLocalTime(iface.observed_at))}); not live.`}</p>
                        )}
                      </>
                    ) : detail ? (
                      <p className="mt-1 text-[11px] text-[var(--ui-fg-muted)]">{zh ? 'CMDB 接口表中没有找到该接口，状态和 MAC 暂不可用。' : 'Interface not found in CMDB.'}</p>
                    ) : null}
                  </dl>
                ) : (
                  <p className="text-[11px] text-[var(--ui-fg-muted)]">{zh ? '未关联设备。可点击“编辑”补充关联设备和接口。' : 'No linked device. Use Edit to link one.'}</p>
                )}
              </Section>

              {detail?.address.interface_liveness && (() => {
                const live = detail.address.interface_liveness!;
                const age = formatLivenessAge(live.age_minutes, zh) || (zh ? '未知时间' : 'unknown time');
                const window = formatLivenessWindow(live.window_minutes, zh);
                const sourceLabel = interfaceLivenessSourceLabel(live.source, zh);
                const stateLabel = live.state === 'up' ? (zh ? '接口 up' : 'Interface up')
                  : live.state === 'admin_down' ? (zh ? '接口已手工关闭' : 'Administratively down')
                    : live.state === 'down' ? (zh ? '接口 down' : 'Interface down')
                      : (zh ? '没有接口状态记录' : 'No interface state');
                const tone = live.alive
                  ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                  : live.state === 'up' ? 'border-amber-200 bg-amber-50 text-amber-800'
                    : live.state === 'unknown' ? 'border-slate-200 bg-slate-50 text-slate-600'
                      : 'border-rose-200 bg-rose-50 text-rose-800';
                return (
                  <section data-testid="ip-detail-liveness" className={`rounded-xl border px-4 py-3 text-[11px] ${tone}`}>
                    <p className="font-bold">
                      {zh ? '存活判断：设备接口地址，以接口状态为准' : 'Liveness: device interface address, judged by interface state'}
                    </p>
                    <p className="mt-1">
                      {stateLabel}
                      {live.state !== 'unknown' && (zh ? ` · ${age}采集 · 来源 ${sourceLabel}` : ` · collected ${age} · ${sourceLabel}`)}
                      {live.state !== 'unknown' && (live.freshness === 'recent' ? (zh ? ' · 当前' : ' · current') : (zh ? ` · 已超过 ${window}，可能不是当前状态` : ` · older than ${window}`))}
                    </p>
                    <p className="mt-1 opacity-80">
                      {zh
                        ? 'Loopback、互联口这类地址通常不会（或只会偶尔）出现在 ARP 表里，下方的 ARP 记录仅供参考。要刷新接口状态，可到 CMDB“接口骨架”点“立即采集接口”。'
                        : 'Loopback and point-to-point addresses rarely appear in ARP tables; ARP records below are informational.'}
                    </p>
                  </section>
                );
              })()}

              <Section icon={Radar} title={zh ? '网络发现记录（ARP/MAC）' : 'Discovery (ARP/MAC)'}>
                {discovery.length > 0 ? (
                  <ul className="space-y-2">
                    {discovery.map((item, index) => (
                      <li key={`${item.mac}-${index}`} className="rounded-lg bg-[var(--ui-surface-muted)] px-3 py-2 text-[11px]">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-mono font-semibold">{formatMacAddress(item.mac || '') || '—'}</span>
                          {(() => {
                            const ageText = formatAge(item.age_minutes, zh);
                            const windowText = item.window_minutes ? formatAge(item.window_minutes, zh) : '';
                            if (!item.is_active) {
                              return <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[9px] font-bold text-slate-500" title={zh ? '采集任务已将这条记录标记为下线' : 'Retired by collection'}>{zh ? '已下线' : 'Retired'}</span>;
                            }
                            if (item.freshness === 'recent') {
                              return <span className="rounded-full bg-emerald-50 px-1.5 py-0.5 text-[9px] font-bold text-emerald-700" title={zh ? `${ageText}前采集到，在当前采集周期内（${windowText}）` : `Seen ${ageText} ago, within ${windowText}`}>{zh ? '当前' : 'Current'}</span>;
                            }
                            if (item.freshness === 'historical') {
                              return <span className="rounded-full bg-amber-50 px-1.5 py-0.5 text-[9px] font-bold text-amber-700" title={zh ? `最近一次采集在 ${ageText}前，超过采集周期（${windowText}），不代表当前仍在线` : `Last seen ${ageText} ago; older than ${windowText}`}>{zh ? `已过期 · ${ageText}前` : `Expired · ${ageText} ago`}</span>;
                            }
                            return <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[9px] font-bold text-slate-500">{zh ? '时间未知' : 'Unknown time'}</span>;
                          })()}
                        </div>
                        <p className="mt-0.5 text-[var(--ui-fg-muted)]">{[item.switch_name, item.switch_port, item.vlan ? `VLAN ${item.vlan}` : ''].filter(Boolean).join(' · ') || (zh ? '接入端口未知' : 'Port unknown')}</p>
                        <p className="text-[var(--ui-fg-muted)]">{zh ? '最近发现' : 'Last seen'} {text(formatIPAddressLocalTime(item.last_seen))} · {(item.source_type || '').toUpperCase()}{item.evidence_source === 'current_observation' ? (zh ? ' · 该设备最近一次 ARP 快照' : ' · latest ARP snapshot of that device') : item.evidence_source === 'legacy_cache' ? (zh ? ' · 旧终端缓存' : ' · legacy cache') : ''}</p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-[11px] text-[var(--ui-fg-muted)]">{detail ? (zh ? '还没有采集到这个 IP 的 ARP/MAC 记录。设备自身接口地址通常不会出现在 ARP 表中；终端地址可用“定位交换机端口”实时查询。' : 'No ARP/MAC records yet.') : '—'}</p>
                )}
              </Section>

              {sameIp.length > conflicting.length && (
                <Section icon={Network} title={zh ? '其他路由域中的同 IP 登记' : 'Same IP in other routing domains'}>
                  <ul className="space-y-1 text-[11px]">
                    {sameIp.filter((item) => !item.same_routing_domain).map((item) => (
                      <li key={item.id} className="font-mono">{item.subnet_prefix || '—'} · {item.site_name || '—'}</li>
                    ))}
                  </ul>
                  <p className="mt-1 text-[10px] text-[var(--ui-fg-muted)]">{zh ? '不同 VRF 中复用同一 IP 是正常的，不算冲突。' : 'Reuse across VRFs is expected.'}</p>
                </Section>
              )}

              <Section icon={History} title={zh ? '变更历史' : 'Change history'}>
                {history.length > 0 ? (
                  <ol className="space-y-2">
                    {history.map((event) => (
                      <li key={event.id} className="border-l-2 border-cyan-200 pl-3 text-[11px]">
                        <p className="font-semibold text-[var(--ui-fg)]">{event.summary || event.event_type}</p>
                        <p className="text-[var(--ui-fg-muted)]">{formatIPAddressLocalTime(event.created_at)} · {event.actor_username || 'system'}</p>
                        {event.changes && event.changes.length > 0 && (
                          <ul className="mt-0.5 space-y-0.5 text-[10px] text-[var(--ui-fg-muted)]">
                            {event.changes.map((change) => (
                              <li key={change.field}>
                                {(FIELD_LABELS[change.field] ? FIELD_LABELS[change.field][zh ? 0 : 1] : change.field)}：<span className="line-through">{text(change.before)}</span> → <span className="font-semibold text-[var(--ui-fg)]">{text(change.after)}</span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="text-[11px] text-[var(--ui-fg-muted)]">{detail ? (zh ? '暂无变更记录（接口采集自动生成的地址在被人工编辑前没有变更历史）。' : 'No changes recorded yet.') : '—'}</p>
                )}
              </Section>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
