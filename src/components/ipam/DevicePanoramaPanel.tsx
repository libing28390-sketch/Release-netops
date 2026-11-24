import React, { useEffect, useState } from 'react';
import { Server, Globe, Cable, Network, Activity, Loader2, Search, AlertTriangle } from 'lucide-react';

interface AssetIdentity {
  device_id: string;
  entity_uid: string;
  hostname: string;
  canonical_mgmt_ip: string;
  status: string;
  role: string;
  vendor: string;
  platform: string;
  model: string;
  os_version: string;
  serial_number: string;
  vsys_id: string;
  ha_cluster_id: string;
  ha_role: string;
  base_mac: string;
  uptime: string;
  site_id: string;
  physical_location: string;
}

interface L3InterfaceItem {
  interface_name: string;
  ip_address: string;
  prefix_length: number | null;
  vrf: string;
  interface_type: string;
  admin_status: string;
  oper_status: string;
  encap_vlan_id: number | null;
  duplex: string;
  description: string;
  source: string;
}

interface TargetPortDiagnostics {
  interface_name: string;
  interface_type: string;
  admin_status: string;
  oper_status: string;
  speed_bps: number | null;
  duplex: string;
  switchport_mode: string;
  access_vlan: number | null;
  encap_vlan_id: number | null;
  channel_group: number | null;
  description: string;
}

interface PanoramaData {
  asset_identity: AssetIdentity;
  l3_interfaces: L3InterfaceItem[];
  target_port_diagnostics: TargetPortDiagnostics | null;
  arp_mac_preview: {
    arp: Array<{ ip: string; mac: string; interface: string; vlan: string; observed_at: string }>;
    mac: Array<{ mac: string; interface: string; vlan: string; type: string; last_updated: string }>;
    limit: number;
  };
  topology_neighbors: Array<{
    local_port: string;
    peer_device_id: string;
    peer_hostname: string;
    peer_port: string;
    protocol: string;
    last_seen: string;
  }>;
}

type PanoramaTab = 'overview' | 'l3' | 'port' | 'arp_mac' | 'neighbors';

interface DevicePanoramaPanelProps {
  deviceId: string;
  highlightPort?: string;
  zh?: boolean;
}

export const DevicePanoramaPanel: React.FC<DevicePanoramaPanelProps> = ({
  deviceId,
  highlightPort = '',
  zh = true,
}) => {
  const [activeTab, setActiveTab] = useState<PanoramaTab>('overview');
  const [data, setData] = useState<PanoramaData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [filterText, setFilterText] = useState('');

  useEffect(() => {
    if (!deviceId) return;
    let cancelled = false;
    setLoading(true);
    setError('');
    const token = localStorage.getItem('netops_token') || localStorage.getItem('token') || '';
    const params = new URLSearchParams();
    if (highlightPort) params.set('highlight_port', highlightPort);
    if (filterText.trim()) params.set('q', filterText.trim());
    fetch(`/api/ip-locator/device-panorama/${encodeURIComponent(deviceId)}?${params.toString()}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return (await res.json()) as PanoramaData;
      })
      .then((payload) => {
        if (!cancelled) setData(payload);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err?.message || 'Failed to load panorama'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [deviceId, highlightPort, filterText]);

  if (!deviceId) return null;

  const tabs: Array<{ id: PanoramaTab; label: string; icon: React.ComponentType<{ size?: number }> }> = [
    { id: 'overview', label: zh ? '1. 设备概览' : '1. Overview', icon: Server },
    { id: 'l3', label: zh ? `2. 三层 IP 与 VRF (${data?.l3_interfaces.length ?? 0})` : `2. L3 & VRF (${data?.l3_interfaces.length ?? 0})`, icon: Globe },
    { id: 'port', label: zh ? '3. 命中端口诊断' : '3. Port Diagnostics', icon: Activity },
    { id: 'arp_mac', label: zh ? '4. 关联 ARP & MAC' : '4. ARP & MAC', icon: Cable },
    { id: 'neighbors', label: zh ? `5. 拓扑邻居 (${data?.topology_neighbors.length ?? 0})` : `5. Neighbors (${data?.topology_neighbors.length ?? 0})`, icon: Network },
  ];

  return (
    <div className="rounded-2xl border border-black/8 dark:border-white/10 bg-white dark:bg-white/[0.03] overflow-hidden shadow-sm">
      <div className="px-4 py-3 border-b border-black/5 dark:border-white/10 flex items-center justify-between gap-3 flex-wrap bg-slate-50/70 dark:bg-white/[0.02]">
        <div className="flex items-center gap-2">
          <Server size={15} className="text-[#0891b2]" />
          <span className="text-sm font-semibold text-[#164e63] dark:text-[var(--app-text)]">
            {zh ? '归属/接入设备 5 维全息详情' : '5D Device Holographic Panorama'}
          </span>
          {data?.asset_identity && (
            <span className="text-xs font-mono text-black/55 dark:text-white/55">
              {data.asset_identity.hostname} ({data.asset_identity.canonical_mgmt_ip})
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 flex-wrap">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  active
                    ? 'bg-[#0891b2] text-white'
                    : 'text-black/60 dark:text-white/60 hover:bg-black/5 dark:hover:bg-white/10'
                }`}
              >
                <Icon size={12} />
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="p-4">
        {loading && !data ? (
          <div className="flex items-center gap-2 text-xs text-black/50 dark:text-white/50 py-6 justify-center">
            <Loader2 size={14} className="animate-spin" />
            <span>{zh ? '正在加载设备全息视图...' : 'Loading device panorama...'}</span>
          </div>
        ) : error ? (
          <div className="flex items-center gap-2 text-xs text-amber-600 dark:text-amber-400 py-4">
            <AlertTriangle size={14} />
            <span>{error}</span>
          </div>
        ) : !data ? null : activeTab === 'overview' ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            {[
              [zh ? '设备名称' : 'Hostname', data.asset_identity.hostname],
              [zh ? '主管理 IP' : 'Canonical Mgmt IP', data.asset_identity.canonical_mgmt_ip],
              [zh ? '厂商 / 平台' : 'Vendor / Platform', `${data.asset_identity.vendor || '-'} / ${data.asset_identity.platform || '-'}`],
              [zh ? '硬件型号' : 'Model', data.asset_identity.model || '-'],
              [zh ? '序列号 (SN)' : 'Serial Number', data.asset_identity.serial_number || '-'],
              [zh ? '复合实体 ID' : 'Entity UID', data.asset_identity.entity_uid],
              [zh ? '虚拟系统 (VSYS)' : 'VSYS', data.asset_identity.vsys_id],
              [zh ? 'HA 角色' : 'HA Role', data.asset_identity.ha_role],
              [zh ? '软件版本' : 'OS Version', data.asset_identity.os_version || '-'],
              [zh ? '运行时长' : 'Uptime', data.asset_identity.uptime || '-'],
              [zh ? '站点 / 位置' : 'Site / Location', data.asset_identity.site_id || data.asset_identity.physical_location || '-'],
              [zh ? '背板 MAC' : 'Base MAC', data.asset_identity.base_mac || '-'],
            ].map(([label, val]) => (
              <div key={label} className="rounded-lg border border-black/5 dark:border-white/10 p-2.5 bg-slate-50/50 dark:bg-white/[0.02]">
                <div className="text-[10px] text-black/45 dark:text-white/45">{label}</div>
                <div className="mt-1 font-mono text-xs font-medium text-black/80 dark:text-white/85 break-all">{val}</div>
              </div>
            ))}
          </div>
        ) : activeTab === 'l3' ? (
          <div className="overflow-x-auto max-h-72">
            <table className="w-full text-left text-xs">
              <thead className="text-[11px] text-black/50 dark:text-white/50 border-b border-black/5 dark:border-white/10">
                <tr>
                  <th className="py-2 pr-3">{zh ? '接口' : 'Interface'}</th>
                  <th className="py-2 pr-3">IP / Mask</th>
                  <th className="py-2 pr-3">VRF</th>
                  <th className="py-2 pr-3">{zh ? '封装 VLAN' : 'Encap VLAN'}</th>
                  <th className="py-2 pr-3">{zh ? '状态 (Admin/Oper)' : 'Status'}</th>
                  <th className="py-2">{zh ? '描述' : 'Description'}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-black/5 dark:divide-white/5 font-mono">
                {data.l3_interfaces.map((item, idx) => (
                  <tr
                    key={`${item.interface_name}-${item.ip_address}-${idx}`}
                    className={
                      highlightPort && item.interface_name.toLowerCase() === highlightPort.toLowerCase()
                        ? 'bg-cyan-50/70 dark:bg-cyan-500/10'
                        : ''
                    }
                  >
                    <td className="py-2 pr-3 font-medium">{item.interface_name}</td>
                    <td className="py-2 pr-3">{item.ip_address}{item.prefix_length != null ? `/${item.prefix_length}` : ''}</td>
                    <td className="py-2 pr-3">{item.vrf}</td>
                    <td className="py-2 pr-3">{item.encap_vlan_id ?? '-'}</td>
                    <td className="py-2 pr-3">
                      <span className={item.oper_status === 'down' || item.admin_status === 'down' ? 'text-rose-600' : 'text-emerald-600'}>
                        {item.admin_status}/{item.oper_status}
                      </span>
                    </td>
                    <td className="py-2 font-sans text-black/60 dark:text-white/60">{item.description || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : activeTab === 'port' ? (
          data.target_port_diagnostics ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
              {[
                [zh ? '命中端口' : 'Port', data.target_port_diagnostics.interface_name],
                [zh ? '管理/协议状态' : 'Admin / Oper', `${data.target_port_diagnostics.admin_status} / ${data.target_port_diagnostics.oper_status}`],
                [zh ? '协商速率' : 'Speed', data.target_port_diagnostics.speed_bps ? `${Math.round(data.target_port_diagnostics.speed_bps / 1_000_000)} Mbps` : '-'],
                [zh ? '双工模式' : 'Duplex', data.target_port_diagnostics.duplex || '-'],
                [zh ? '端口模式' : 'Switchport Mode', data.target_port_diagnostics.switchport_mode || '-'],
                [zh ? 'Access VLAN' : 'Access VLAN', data.target_port_diagnostics.access_vlan ?? '-'],
                [zh ? '子接口封装 VLAN' : 'Encap VLAN', data.target_port_diagnostics.encap_vlan_id ?? '-'],
                [zh ? '所属聚合组' : 'LAG Group', data.target_port_diagnostics.channel_group ?? '-'],
              ].map(([label, val]) => (
                <div key={String(label)} className="rounded-lg border border-black/5 dark:border-white/10 p-2.5 bg-slate-50/50 dark:bg-white/[0.02]">
                  <div className="text-[10px] text-black/45 dark:text-white/45">{label}</div>
                  <div className="mt-1 font-mono text-xs font-medium">{String(val)}</div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-black/45 dark:text-white/45 py-4">
              {zh ? '当前未指定具体物理端口或该端口暂无扩展诊断记录。' : 'No specific physical port diagnostics available.'}
            </p>
          )
        ) : activeTab === 'arp_mac' ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2 max-w-xs">
              <Search size={13} className="text-black/40" />
              <input
                type="text"
                value={filterText}
                onChange={(e) => setFilterText(e.target.value)}
                placeholder={zh ? '按 IP / MAC / 端口实时过滤...' : 'Filter by IP / MAC / port...'}
                className="w-full rounded-lg border border-black/10 dark:border-white/15 bg-transparent px-2.5 py-1 text-xs"
              />
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 text-xs">
              <div>
                <p className="font-semibold mb-1.5 text-black/70 dark:text-white/70">
                  ARP ({data.arp_mac_preview.arp.length})
                </p>
                <div className="max-h-56 overflow-y-auto border border-black/5 dark:border-white/10 rounded-lg divide-y divide-black/5 dark:divide-white/5 font-mono">
                  {data.arp_mac_preview.arp.length === 0 ? (
                    <div className="p-3 text-black/40 font-sans">{zh ? '暂无局部 ARP 缓存' : 'No local ARP entries'}</div>
                  ) : (
                    data.arp_mac_preview.arp.map((a, idx) => (
                      <div key={idx} className="px-3 py-1.5 flex items-center justify-between gap-2">
                        <span>{a.ip}</span>
                        <span className="text-amber-600 dark:text-amber-400">{a.mac}</span>
                        <span className="text-black/50 dark:text-white/50">{a.interface}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>
              <div>
                <p className="font-semibold mb-1.5 text-black/70 dark:text-white/70">
                  MAC ({data.arp_mac_preview.mac.length})
                </p>
                <div className="max-h-56 overflow-y-auto border border-black/5 dark:border-white/10 rounded-lg divide-y divide-black/5 dark:divide-white/5 font-mono">
                  {data.arp_mac_preview.mac.length === 0 ? (
                    <div className="p-3 text-black/40 font-sans">{zh ? '暂无局部 MAC 表项' : 'No local MAC entries'}</div>
                  ) : (
                    data.arp_mac_preview.mac.map((m, idx) => (
                      <div key={idx} className="px-3 py-1.5 flex items-center justify-between gap-2">
                        <span className="text-amber-600 dark:text-amber-400">{m.mac}</span>
                        <span>{m.interface}</span>
                        <span className="text-cyan-600 dark:text-cyan-400">VLAN {m.vlan || '-'}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto max-h-72">
            <table className="w-full text-left text-xs font-mono">
              <thead className="text-[11px] font-sans text-black/50 dark:text-white/50 border-b border-black/5 dark:border-white/10">
                <tr>
                  <th className="py-2 pr-3">{zh ? '本端端口' : 'Local Port'}</th>
                  <th className="py-2 pr-3">{zh ? '对端设备' : 'Peer Device'}</th>
                  <th className="py-2 pr-3">{zh ? '对端端口' : 'Peer Port'}</th>
                  <th className="py-2">{zh ? '协议来源' : 'Source'}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-black/5 dark:divide-white/5">
                {data.topology_neighbors.map((n, idx) => (
                  <tr key={idx}>
                    <td className="py-2 pr-3">{n.local_port}</td>
                    <td className="py-2 pr-3 font-semibold text-[#0891b2]">{n.peer_hostname}</td>
                    <td className="py-2 pr-3">{n.peer_port}</td>
                    <td className="py-2 text-black/50 dark:text-white/50">{n.protocol}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

export default DevicePanoramaPanel;
