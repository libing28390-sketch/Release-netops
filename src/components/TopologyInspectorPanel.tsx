import React, { useState } from 'react';
import { AlertCircle, Eye, Monitor, ChevronDown, Unplug, Radio } from 'lucide-react';
import type { Device } from '../types';

interface TopologyOperationalTone {
  badge: string;
  panel: string;
}

interface TopologyDecoratedLinkLike {
  id?: string;
  link_key?: string;
  source_device_id?: string;
  target_device_id?: string;
  source_hostname?: string;
  source_hostname_resolved?: string;
  target_hostname?: string;
  target_hostname_resolved?: string;
  source_port?: string;
  target_port?: string;
  source_interface_snapshot?: unknown;
  target_interface_snapshot?: unknown;
  operational_state?: string;
  operational_summary?: string;
  last_seen?: string;
  evidence_sources: string[];
  evidence_count?: number;
  reverse_confirmed?: boolean;
  link_kind?: string;
  aggregation_protocol?: string;
  member_count?: number;
  active_member_count?: number;
  aggregation_bandwidth_mbps?: number | null;
  members?: Array<{
    source?: { name?: string; speed_mbps?: number; up?: boolean };
    target?: { name?: string; speed_mbps?: number; up?: boolean };
  }>;
}

interface TopologyInspectorPanelProps {
  language: string;
  selectedTopologyDevice: Device | null;
  selectedTopologyLink: TopologyDecoratedLinkLike | null;
  topologyNeighborDevices: Device[];
  topologyDeviceLinks: TopologyDecoratedLinkLike[];
  topologyPriorityDevices: Device[];
  topologyOrphanDevices: Device[];
  selectedTopologyLinkKey: string | null;
  secondaryActionBtnClass: string;
  onSelectDevice: (deviceId: string) => void;
  onSelectLink: (linkKey: string | null) => void;
  onOpenDeviceDetail: (device: Device) => void;
  onOpenMonitoring: () => void;
  formatTopologyPort: (value?: string) => string;
  formatTopologyInterfaceTelemetry: (snapshot: unknown) => string;
  formatTopologyLastSeen: (value?: string) => string;
  formatTopologyOperationalState: (value?: string) => string;
  formatTopologyEvidenceLabel: (value?: string) => string;
  getTopologyOperationalTone: (value?: string) => TopologyOperationalTone;
}

/* ── helpers ── */
const statusDot = (status?: string) => {
  if (status === 'online') return 'bg-emerald-400';
  if (status === 'pending') return 'bg-amber-400';
  return 'bg-rose-400';
};

const statusBadgeClass = (status?: string) => {
  if (status === 'online') return 'border-emerald-200/60 bg-emerald-50 text-emerald-600';
  if (status === 'pending') return 'border-amber-200/60 bg-amber-50 text-amber-600';
  return 'border-rose-200/60 bg-rose-50 text-rose-600';
};

/* ── collapsible section ── */
const Section: React.FC<{
  title: string;
  count?: number;
  icon?: React.ReactNode;
  accent?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}> = ({ title, count, icon, accent = 'text-cyan-600', defaultOpen = true, children }) => {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-t border-slate-100 first:border-t-0">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="group flex w-full items-center gap-2 px-4 py-3 text-left transition-colors hover:bg-slate-50/60"
      >
        {icon && <span className={accent}>{icon}</span>}
        <span className="flex-1 text-[13px] font-semibold tracking-tight text-slate-700">{title}</span>
        {count !== undefined && (
          <span className="min-w-[22px] rounded-full bg-slate-100 px-1.5 py-0.5 text-center text-[10px] font-bold tabular-nums text-slate-500">
            {count}
          </span>
        )}
        <ChevronDown
          size={14}
          className={`text-slate-400 transition-transform duration-200 ${open ? 'rotate-0' : '-rotate-90'}`}
        />
      </button>
      {open && <div className="px-4 pb-3">{children}</div>}
    </div>
  );
};

const TopologyInspectorPanel: React.FC<TopologyInspectorPanelProps> = ({
  language,
  selectedTopologyDevice,
  selectedTopologyLink,
  topologyNeighborDevices,
  topologyDeviceLinks,
  topologyPriorityDevices,
  topologyOrphanDevices,
  selectedTopologyLinkKey,
  secondaryActionBtnClass,
  onSelectDevice,
  onSelectLink,
  onOpenDeviceDetail,
  onOpenMonitoring,
  formatTopologyPort,
  formatTopologyInterfaceTelemetry,
  formatTopologyLastSeen,
  formatTopologyOperationalState,
  formatTopologyEvidenceLabel,
  getTopologyOperationalTone,
}) => {
  const zh = language === 'zh';

  /* ── empty state ── */
  if (!selectedTopologyDevice) {
    return (
      <div className="flex min-h-[620px] flex-col">
        <div className="flex flex-1 flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-gradient-to-b from-white to-slate-50/80 px-6 py-16 text-center">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-cyan-50 ring-1 ring-cyan-100">
            <Radio size={24} className="text-cyan-500" />
          </div>
          <p className="text-[15px] font-semibold text-slate-700">
            {zh ? '选择一个节点' : 'Select a Node'}
          </p>
          <p className="mt-1.5 max-w-[220px] text-[13px] leading-relaxed text-slate-400">
            {zh
              ? '在左侧拓扑图中点击任意设备，查看邻接关系与健康态势。'
              : 'Click any device in the topology graph to inspect adjacency and operational context.'}
          </p>
          {/* summary stats below empty state */}
          <div className="mt-8 grid w-full max-w-[260px] grid-cols-3 gap-2">
            {[
              { label: zh ? '告警设备' : 'At Risk', val: topologyPriorityDevices.length, color: 'text-amber-500' },
              { label: zh ? '孤立节点' : 'Orphans', val: topologyOrphanDevices.length, color: 'text-slate-500' },
              { label: zh ? '邻接链路' : 'Links', val: topologyDeviceLinks.length, color: 'text-cyan-500' },
            ].map((s) => (
              <div key={s.label} className="rounded-xl bg-white px-2 py-2.5 text-center ring-1 ring-black/[0.04]">
                <p className={`text-lg font-bold tabular-nums ${s.color}`}>{s.val}</p>
                <p className="mt-0.5 text-[10px] font-medium uppercase tracking-wider text-slate-400">{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  /* ── device selected ── */
  return (
    <div className="flex min-h-[620px] flex-col gap-3">
      {/* ─── device header card ─── */}
      <div className="overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-black/[0.04]">
        {/* gradient accent bar */}
        <div className="h-1 bg-gradient-to-r from-cyan-400 via-cyan-500 to-teal-400" />

        <div className="px-4 pb-4 pt-3.5">
          <div className="flex items-start gap-3">
            {/* status dot + hostname */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className={`mt-0.5 h-2.5 w-2.5 shrink-0 rounded-full ring-2 ring-white ${statusDot(selectedTopologyDevice.status)}`} />
                <h3 className="truncate text-[17px] font-bold tracking-tight text-slate-800">
                  {selectedTopologyDevice.hostname}
                </h3>
              </div>
              <p className="mt-1 truncate pl-[18px] text-[12px] text-slate-400">
                {selectedTopologyDevice.ip_address}
                {selectedTopologyDevice.site ? ` · ${selectedTopologyDevice.site}` : ''}
                {selectedTopologyDevice.role ? ` · ${selectedTopologyDevice.role}` : ''}
              </p>
            </div>
            <span className={`shrink-0 rounded-full border px-2.5 py-[3px] text-[10px] font-bold uppercase tracking-wide ${statusBadgeClass(selectedTopologyDevice.status)}`}>
              {selectedTopologyDevice.status}
            </span>
          </div>

          {/* stats row */}
          <div className="mt-3.5 grid grid-cols-2 gap-2">
            <div className="flex items-center gap-2.5 rounded-lg bg-slate-50 px-3 py-2 ring-1 ring-black/[0.03]">
              <span className="text-lg font-bold tabular-nums text-slate-700">{topologyNeighborDevices.length}</span>
              <span className="text-[11px] font-medium text-slate-400">{zh ? '邻接节点' : 'Neighbors'}</span>
            </div>
            <div className="flex items-center gap-2.5 rounded-lg bg-slate-50 px-3 py-2 ring-1 ring-black/[0.03]">
              <span className="text-lg font-bold tabular-nums text-slate-700">{topologyDeviceLinks.length}</span>
              <span className="text-[11px] font-medium text-slate-400">{zh ? '接口链路' : 'Links'}</span>
            </div>
          </div>

          {/* action buttons */}
          <div className="mt-3 flex gap-2">
            <button onClick={() => onOpenDeviceDetail(selectedTopologyDevice)} className={secondaryActionBtnClass}>
              <Eye size={15} />
              {zh ? '设备详情' : 'Detail'}
            </button>
            <button onClick={onOpenMonitoring} className={secondaryActionBtnClass}>
              <Monitor size={15} />
              {zh ? '监控中心' : 'Monitor'}
            </button>
          </div>
        </div>
      </div>

      {/* ─── accordion sections ─── */}
      <div className="overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-black/[0.04]">

        {/* === selected link detail (always visible when link selected) === */}
        {selectedTopologyLink && (
          <div className={`border-b border-slate-100 px-4 py-3 ${getTopologyOperationalTone(selectedTopologyLink.operational_state).panel}`}>
            <div className="flex items-center justify-between gap-2">
              <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">
                {zh ? '选中链路' : 'Selected Link'}
              </p>
              <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${getTopologyOperationalTone(selectedTopologyLink.operational_state).badge}`}>
                {formatTopologyOperationalState(selectedTopologyLink.operational_state)}
              </span>
            </div>
            <div className="mt-2 space-y-0.5 text-[12px] text-slate-600">
              <p>
                <span className="font-semibold text-slate-700">{selectedTopologyLink.source_hostname || selectedTopologyLink.source_hostname_resolved || selectedTopologyLink.source_device_id}</span>
                <span className="mx-1 text-slate-300">:</span>
                {formatTopologyPort(selectedTopologyLink.source_port)}
              </p>
              <p>
                <span className="font-semibold text-slate-700">{selectedTopologyLink.target_hostname || selectedTopologyLink.target_hostname_resolved || selectedTopologyLink.target_device_id}</span>
                <span className="mx-1 text-slate-300">:</span>
                {formatTopologyPort(selectedTopologyLink.target_port)}
              </p>
            </div>
            {selectedTopologyLink.operational_summary && (
              <p className="mt-1.5 text-[11px] leading-relaxed text-slate-500">{selectedTopologyLink.operational_summary}</p>
            )}
            {selectedTopologyLink.link_kind === 'aggregation' && (
              <div className="mt-2.5 rounded-lg bg-white/70 px-2.5 py-2 ring-1 ring-cyan-200/60">
                <div className="flex items-center justify-between text-[10px] font-bold text-cyan-700">
                  <span>{zh ? '聚合链路' : 'Aggregation'}</span>
                  <span>
                    {selectedTopologyLink.aggregation_protocol || 'LAG'} · {selectedTopologyLink.active_member_count || 0}/{selectedTopologyLink.member_count || 0}
                  </span>
                </div>
                {selectedTopologyLink.members && selectedTopologyLink.members.length > 0 && (
                  <div className="mt-1.5 space-y-1 text-[10px] text-slate-600">
                    {selectedTopologyLink.members.map((member, index) => (
                      <div key={`member-${index}`} className="flex items-center justify-between gap-2">
                        <span>{member.source?.name || '-'} ↔ {member.target?.name || '-'}</span>
                        <span className={member.source?.up && member.target?.up ? 'text-emerald-600' : 'text-amber-600'}>
                          {member.source?.up && member.target?.up ? 'UP' : 'DEGRADED'}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            <div className="mt-2.5 grid grid-cols-2 gap-2">
              <div className="rounded-md bg-white/60 px-2.5 py-1.5 ring-1 ring-black/[0.04]">
                <p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">{zh ? '源端遥测' : 'Source'}</p>
                <p className="mt-0.5 text-[11px] text-slate-600">{formatTopologyInterfaceTelemetry(selectedTopologyLink.source_interface_snapshot)}</p>
              </div>
              <div className="rounded-md bg-white/60 px-2.5 py-1.5 ring-1 ring-black/[0.04]">
                <p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">{zh ? '对端遥测' : 'Target'}</p>
                <p className="mt-0.5 text-[11px] text-slate-600">{formatTopologyInterfaceTelemetry(selectedTopologyLink.target_interface_snapshot)}</p>
              </div>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {(selectedTopologyLink.evidence_sources.length > 0 ? selectedTopologyLink.evidence_sources : ['lldp']).map((source) => (
                <span key={`sel-${source}`} className="rounded bg-white/70 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-slate-500 ring-1 ring-black/[0.06]">
                  {formatTopologyEvidenceLabel(source)}
                </span>
              ))}
              {selectedTopologyLink.reverse_confirmed && (
                <span className="rounded bg-cyan-50 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-cyan-600 ring-1 ring-cyan-200/60">
                  {zh ? '双向' : 'Bi-dir'}
                </span>
              )}
              <span className="text-[10px] text-slate-400">
                · {formatTopologyLastSeen(selectedTopologyLink.last_seen)}
              </span>
            </div>
          </div>
        )}

        {/* === interface links === */}
        <Section
          title={zh ? '接口链路' : 'Interface Adjacencies'}
          count={topologyDeviceLinks.length}
          icon={<Radio size={14} />}
          accent="text-cyan-500"
          defaultOpen
        >
          {topologyDeviceLinks.length > 0 ? (
            <div className="space-y-1.5">
              {topologyDeviceLinks.slice(0, 8).map((link) => {
                const isSource = link.source_device_id === selectedTopologyDevice.id;
                const peerName = isSource
                  ? (link.target_hostname || link.target_hostname_resolved || '')
                  : (link.source_hostname || link.source_hostname_resolved || '');
                const localPort = formatTopologyPort(isSource ? link.source_port : link.target_port);
                const remotePort = formatTopologyPort(isSource ? link.target_port : link.source_port);
                const localTelemetry = formatTopologyInterfaceTelemetry(isSource ? link.source_interface_snapshot : link.target_interface_snapshot);
                const remoteTelemetry = formatTopologyInterfaceTelemetry(isSource ? link.target_interface_snapshot : link.source_interface_snapshot);
                const peerId = isSource ? link.target_device_id : link.source_device_id;
                const linkKey = link.link_key || link.id || null;
                const tone = getTopologyOperationalTone(link.operational_state);
                const isActive = selectedTopologyLinkKey != null && linkKey === selectedTopologyLinkKey;

                return (
                  <div
                    key={linkKey || `${link.source_device_id}-${link.target_device_id}-${localPort}`}
                    className={`group relative rounded-lg border transition-all ${
                      isActive
                        ? 'border-cyan-300/50 bg-cyan-50/40 shadow-sm'
                        : 'border-transparent bg-slate-50/70 hover:border-slate-200 hover:bg-slate-50'
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => onSelectLink(linkKey)}
                      className="w-full px-3 py-2 text-left"
                    >
                      <div className="flex items-center gap-2">
                        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                          link.operational_state === 'up' ? 'bg-emerald-400'
                          : link.operational_state === 'down' ? 'bg-rose-400'
                          : 'bg-slate-300'
                        }`} />
                        <span className="flex-1 truncate text-[13px] font-semibold text-slate-700">
                          {peerName || (zh ? '对端' : 'Peer')}
                        </span>
                        <span className={`rounded border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide ${tone.badge}`}>
                          {formatTopologyOperationalState(link.operational_state)}
                        </span>
                      </div>
                      <div className="mt-1 flex items-baseline gap-1 pl-3.5 text-[11px] text-slate-400">
                        <span className="font-mono">{localPort}</span>
                        <span className="text-slate-300">⇄</span>
                        <span className="font-mono">{remotePort}</span>
                        <span className="mx-1 text-slate-200">|</span>
                        <span className="truncate">{localTelemetry}</span>
                      </div>
                    </button>
                    {/* evidence + actions row */}
                    <div className="flex items-center justify-between border-t border-dashed border-slate-100 px-3 py-1">
                      <div className="flex items-center gap-1">
                        {link.evidence_sources.slice(0, 2).map((src) => (
                          <span key={`${linkKey}-${src}`} className="rounded bg-slate-100 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-slate-500">
                            {formatTopologyEvidenceLabel(src)}
                          </span>
                        ))}
                        {link.reverse_confirmed && (
                          <span className="rounded bg-cyan-50 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-cyan-600">
                            {zh ? '双向' : 'Bi'}
                          </span>
                        )}
                      </div>
                      {peerId && (
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); onSelectDevice(peerId); onSelectLink(linkKey); }}
                          className="text-[10px] font-semibold text-cyan-600 opacity-0 transition-opacity group-hover:opacity-100 hover:text-cyan-700"
                        >
                          {zh ? '切到对端 →' : 'Peer →'}
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
              {topologyDeviceLinks.length > 8 && (
                <p className="pl-3 text-[11px] text-slate-400">
                  {zh ? `还有 ${topologyDeviceLinks.length - 8} 条链路…` : `${topologyDeviceLinks.length - 8} more links…`}
                </p>
              )}
            </div>
          ) : (
            <p className="py-2 text-center text-[12px] text-slate-400">
              {zh ? '暂无接口链路数据' : 'No interface links available'}
            </p>
          )}
        </Section>

        {/* === direct neighbors === */}
        <Section
          title={zh ? '直接邻居' : 'Direct Neighbors'}
          count={topologyNeighborDevices.length}
          defaultOpen={topologyNeighborDevices.length > 0 && topologyNeighborDevices.length <= 8}
        >
          {topologyNeighborDevices.length > 0 ? (
            <div className="space-y-1">
              {topologyNeighborDevices.slice(0, 6).map((device) => (
                <button
                  key={device.id}
                  onClick={() => onSelectDevice(device.id)}
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left transition-colors hover:bg-slate-50"
                >
                  <span className={`h-2 w-2 shrink-0 rounded-full ${statusDot(device.status)}`} />
                  <span className="flex-1 truncate text-[13px] font-medium text-slate-700">{device.hostname}</span>
                  <span className="text-[11px] text-slate-400">{device.role || device.ip_address}</span>
                </button>
              ))}
              {topologyNeighborDevices.length > 6 && (
                <p className="pl-6 text-[11px] text-slate-400">
                  {zh ? `还有 ${topologyNeighborDevices.length - 6} 个邻居…` : `${topologyNeighborDevices.length - 6} more…`}
                </p>
              )}
            </div>
          ) : (
            <p className="py-2 text-center text-[12px] text-slate-400">
              {zh ? '未发现邻接设备' : 'No adjacent devices found'}
            </p>
          )}
        </Section>
      </div>

      {/* ─── watchlist & orphans ─── */}
      <div className="overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-black/[0.04]">
        {/* === priority watchlist === */}
        <Section
          title={zh ? '优先关注' : 'Priority Watchlist'}
          count={topologyPriorityDevices.length}
          icon={<AlertCircle size={14} />}
          accent={topologyPriorityDevices.length > 0 ? 'text-amber-500' : 'text-slate-400'}
          defaultOpen={topologyPriorityDevices.length > 0}
        >
          {topologyPriorityDevices.length > 0 ? (
            <div className="space-y-1">
              {topologyPriorityDevices.map((device) => (
                <button
                  key={device.id}
                  onClick={() => onSelectDevice(device.id)}
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left transition-colors hover:bg-amber-50/60"
                >
                  <span className={`h-2 w-2 shrink-0 rounded-full ${statusDot(device.status)}`} />
                  <span className="flex-1 truncate text-[13px] font-medium text-slate-700">{device.hostname}</span>
                  <span className="rounded bg-rose-50 px-1.5 py-0.5 text-[10px] font-bold tabular-nums text-rose-600 ring-1 ring-rose-100">
                    {device.open_alert_count || 0}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <p className="py-2 text-center text-[12px] text-slate-400">
              {zh ? '没有需要优先处置的节点' : 'No high-priority devices'}
            </p>
          )}
        </Section>

        {/* === orphan devices === */}
        <Section
          title={zh ? '孤立节点' : 'Orphan Devices'}
          count={topologyOrphanDevices.length}
          icon={<Unplug size={14} />}
          accent="text-slate-400"
          defaultOpen={false}
        >
          {topologyOrphanDevices.length > 0 ? (
            <div className="space-y-1">
              {topologyOrphanDevices.slice(0, 6).map((device) => (
                <button
                  key={device.id}
                  onClick={() => onSelectDevice(device.id)}
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left transition-colors hover:bg-slate-50"
                >
                  <span className="h-2 w-2 shrink-0 rounded-full bg-slate-300" />
                  <span className="flex-1 truncate text-[13px] font-medium text-slate-600">{device.hostname}</span>
                  <span className="text-[11px] text-slate-400">{device.site || (zh ? '未分站' : '-')}</span>
                </button>
              ))}
              {topologyOrphanDevices.length > 6 && (
                <p className="pl-6 text-[11px] text-slate-400">
                  {zh ? `还有 ${topologyOrphanDevices.length - 6} 个…` : `${topologyOrphanDevices.length - 6} more…`}
                </p>
              )}
            </div>
          ) : (
            <p className="py-2 text-center text-[12px] text-slate-400">
              {zh ? '没有孤立节点' : 'No orphan devices'}
            </p>
          )}
        </Section>
      </div>
    </div>
  );
};

export default TopologyInspectorPanel;
