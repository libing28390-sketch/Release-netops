import React, { useState, useCallback } from 'react';
import { Search, MapPin, ArrowRight, Loader2, Server, Monitor, Network, AlertCircle, ChevronDown, ChevronUp, Cable } from 'lucide-react';
import { formatMacAddress } from '../utils/resourceFormatters';

interface IPLocatorProps {
  language: string;
}

interface LocationEntry {
  switch_id: string;
  switch_name: string;
  port: string;
  vlan: string;
  type: string;
  is_uplink: boolean;
  uplink_neighbor?: string;
  uplink_port?: string;
}

interface TraceHop {
  switch_id?: string;
  switch_name?: string;
  port?: string;
  is_aggregation?: boolean;
  is_trunk?: boolean;
}

interface LocateResult {
  target_ip: string;
  found: boolean;
  mac: string | null;
  mac_display: string | null;
  arp_source: { device_id: string; device: string; interface: string } | null;
  locations: LocationEntry[];
  searched_devices: { arp: string[]; mac: string[]; lldp: string[] };
  timestamp: string;
  errors: string[];
  trace_status?: string;
  trace_hops?: TraceHop[];
}

const IPLocatorPanel: React.FC<IPLocatorProps> = ({ language }) => {
  const zh = language === 'zh';
  const [ip, setIp] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<LocateResult | null>(null);
  const [error, setError] = useState('');
  const [showDetails, setShowDetails] = useState(false);
  const [history, setHistory] = useState<{ ip: string; found: boolean; mac: string; switch_name: string; port: string; time: string }[]>([]);

  const token = localStorage.getItem('netops_token') || '';

  const doLocate = useCallback(async () => {
    const trimmed = ip.trim();
    if (!trimmed) return;
    setLoading(true);
    setError('');
    setResult(null);

    try {
      const resp = await fetch('/api/ip-locator/locate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ ip: trimmed }),
      });
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${resp.status}`);
      }
      const data: LocateResult = await resp.json();
      setResult(data);

      // 追加历史
      const primary = data.locations?.find(l => !l.is_uplink) || data.locations?.[0];
      setHistory(prev => [{
        ip: trimmed,
        found: data.found,
        mac: data.mac_display || '-',
        switch_name: primary?.switch_name || '-',
        port: primary?.port || '-',
        time: new Date().toLocaleTimeString(),
      }, ...prev].slice(0, 10));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [ip, token]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !loading) doLocate();
  };

  const accessLocations = result?.locations?.filter(l => !l.is_uplink) || [];
  const uplinkLocations = result?.locations?.filter(l => l.is_uplink) || [];

  return (
    <div className="space-y-3">
      {/* ── Search Bar ── */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1 max-w-md">
          <MapPin size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#0891b2]" />
          <input
            type="text"
            value={ip}
            onChange={e => setIp(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={zh ? '输入 IP 地址定位，如 10.1.1.100' : 'Enter IP to locate, e.g. 10.1.1.100'}
            className="w-full pl-9 pr-3 py-2.5 rounded-xl border border-black/10 text-sm bg-white focus:ring-2 focus:ring-[#06b6d4]/30 focus:border-[#06b6d4] outline-none transition-all placeholder:text-black/30"
          />
        </div>
        <button
          onClick={doLocate}
          disabled={loading || !ip.trim()}
          className="px-5 py-2.5 rounded-xl bg-[#0891b2] text-white text-sm font-semibold hover:bg-[#0e7490] disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center gap-2 shadow-sm"
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
          {zh ? '定位' : 'Locate'}
        </button>
      </div>

      {/* ── Loading ── */}
      {loading && (
        <div className="bg-[#ecfeff]/60 border border-[#06b6d4]/20 rounded-xl px-5 py-4">
          <div className="flex items-center gap-3">
            <Loader2 size={18} className="animate-spin text-[#0891b2]" />
            <div>
              <p className="text-sm font-medium text-[#164e63]">{zh ? '正在定位...' : 'Locating...'}</p>
              <p className="text-[11px] text-[#0891b2] mt-0.5">{zh ? '正在查询网关 ARP 表和交换机 MAC 地址表，请稍候' : 'Querying gateway ARP tables and switch MAC tables, please wait'}</p>
            </div>
          </div>
        </div>
      )}

      {/* ── Error ── */}
      {error && !loading && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 flex items-start gap-2.5">
          <AlertCircle size={16} className="text-red-500 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm font-medium text-red-700">{zh ? '查询失败' : 'Locate Failed'}</p>
            <p className="text-xs text-red-500 mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* ── Result ── */}
      {result && !loading && (
        <div className="space-y-3">
          {/* Path visualization */}
          {result.found && accessLocations.length > 0 ? (
            <div className="bg-gradient-to-r from-emerald-50 to-[#ecfeff] border border-emerald-200/60 rounded-xl overflow-hidden">
              {/* Path header */}
              <div className="px-4 py-3 border-b border-emerald-200/40 bg-white/40">
                <div className="flex items-center gap-2">
                  <div className="w-5 h-5 rounded-full bg-emerald-500 flex items-center justify-center">
                    <MapPin size={11} className="text-white" />
                  </div>
                  <span className="text-sm font-bold text-emerald-800">{zh ? '定位成功' : 'Located'}</span>
                  <span className="text-xs text-emerald-600 ml-auto font-mono">{result.timestamp?.replace('T', ' ').slice(0, 19)}</span>
                </div>
              </div>

              {/* Path flow: IP → MAC → Switch:Port */}
              <div className="px-4 py-4">
                <div className="flex items-center gap-1 flex-wrap">
                  {/* IP */}
                  <div className="flex items-center gap-2 bg-white rounded-lg px-3 py-2 border border-black/8 shadow-sm">
                    <Monitor size={14} className="text-violet-500" />
                    <div>
                      <p className="text-[10px] text-black/40 font-medium uppercase tracking-wide">IP</p>
                      <p className="text-sm font-bold text-[#164e63] font-mono">{result.target_ip}</p>
                    </div>
                  </div>

                  <ArrowRight size={14} className="text-black/20 mx-1 flex-shrink-0" />

                  {/* MAC */}
                  <div className="flex items-center gap-2 bg-white rounded-lg px-3 py-2 border border-black/8 shadow-sm">
                    <Cable size={14} className="text-amber-500" />
                    <div>
                      <p className="text-[10px] text-black/40 font-medium uppercase tracking-wide">MAC</p>
                      <p className="text-sm font-bold text-[#164e63] font-mono">{formatMacAddress(result.mac_display)}</p>
                      {result.arp_source && (
                        <p className="text-[10px] text-black/35 mt-0.5">
                          via {result.arp_source.device} ({result.arp_source.interface})
                        </p>
                      )}
                    </div>
                  </div>

                  <ArrowRight size={14} className="text-black/20 mx-1 flex-shrink-0" />

                  {/* Switch:Port(s) */}
                  {accessLocations.map((loc, i) => (
                    <React.Fragment key={i}>
                      {i > 0 && <span className="text-[10px] text-black/30 mx-1">/</span>}
                      <div className="flex items-center gap-2 bg-white rounded-lg px-3 py-2 border border-[#06b6d4]/30 shadow-sm ring-1 ring-[#06b6d4]/10">
                        <Server size={14} className="text-[#0891b2]" />
                        <div>
                          <p className="text-[10px] text-black/40 font-medium uppercase tracking-wide">{zh ? '交换机:端口' : 'Switch:Port'}</p>
                          <p className="text-sm font-bold text-[#164e63]">
                            <span className="font-mono">{loc.switch_name}</span>
                            <span className="text-[#0891b2] mx-1">:</span>
                            <span className="font-mono text-[#0891b2]">{loc.port}</span>
                          </p>
                          <div className="flex items-center gap-2 mt-0.5">
                            {loc.vlan && <span className="text-[10px] bg-cyan-50 text-cyan-700 rounded px-1.5 py-0.5 font-medium">VLAN {loc.vlan}</span>}
                            {loc.type && <span className="text-[10px] text-black/35">{loc.type}</span>}
                          </div>
                          {loc.uplink_neighbor && (
                            <p className="text-[10px] text-black/35 mt-0.5 flex items-center gap-1">
                              <Network size={9} />
                              {zh ? '上联' : 'Uplink'}: {loc.uplink_neighbor} ({loc.uplink_port})
                            </p>
                          )}
                        </div>
                      </div>
                    </React.Fragment>
                  ))}
                </div>

                {/* Uplink entries if any */}
                {uplinkLocations.length > 0 && (
                  <div className="mt-3 pt-2 border-t border-emerald-200/40">
                    <p className="text-[10px] text-black/35 font-medium mb-1.5">{zh ? '上联口也匹配到该 MAC（可忽略）' : 'Also seen on uplink ports (can ignore)'}:</p>
                    <div className="flex flex-wrap gap-1.5">
                      {uplinkLocations.map((loc, i) => (
                        <span key={i} className="text-[10px] bg-black/5 text-black/50 rounded px-2 py-0.5 font-mono">
                          {loc.switch_name}:{loc.port}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : result.trace_status === 'incomplete' ? (
            <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
              <div className="flex items-start gap-2.5">
                <AlertCircle size={16} className="text-amber-500 mt-0.5 flex-shrink-0" />
                <div className="min-w-0">
                  <p className="text-sm font-medium text-amber-800">{zh ? '链路追踪未完成' : 'Path Trace Incomplete'}</p>
                  <p className="text-xs text-amber-600 mt-0.5">
                    {zh ? 'MAC 已从 ARP 获取，但当前路径证据不足，未判定中间接口为主机端口。' : 'The MAC was resolved from ARP, but the path evidence is incomplete, so an intermediate interface is not marked as a host port.'}
                  </p>
                  {result.errors?.map((err, i) => (
                    <p key={i} className="text-xs text-amber-600 mt-1">{err}</p>
                  ))}
                  {(result.trace_hops?.length ?? 0) > 0 && (
                    <div className="mt-2 flex flex-wrap items-center gap-1 text-[10px] text-amber-800">
                      {result.trace_hops?.map((hop, i) => (
                        <React.Fragment key={`${hop.switch_id || hop.switch_name}-${hop.port}-${i}`}>
                          {i > 0 && <ArrowRight size={10} className="text-amber-400" />}
                          <span className="rounded bg-white/70 px-1.5 py-0.5 font-mono">
                            {hop.switch_name || hop.switch_id || '-'}:{hop.port || '-'}
                            {hop.is_aggregation ? ' · LAG' : hop.is_trunk ? ' · Trunk' : ''}
                          </span>
                        </React.Fragment>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          ) : !result.found ? (
            <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
              <div className="flex items-start gap-2.5">
                <AlertCircle size={16} className="text-amber-500 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="text-sm font-medium text-amber-800">{zh ? '未找到' : 'Not Found'}</p>
                  {result.errors?.map((err, i) => (
                    <p key={i} className="text-xs text-amber-600 mt-0.5">{err}</p>
                  ))}
                  {result.mac && (
                    <p className="text-xs text-amber-600 mt-1">
                      {zh ? `MAC 地址 ${formatMacAddress(result.mac_display)} 已获取，但未在交换机 MAC 表中匹配到端口` : `MAC ${formatMacAddress(result.mac_display)} resolved but not found in switch MAC tables`}
                    </p>
                  )}
                </div>
              </div>
            </div>
          ) : null}

          {/* Detail toggle */}
          {result.searched_devices && (
            <button
              onClick={() => setShowDetails(!showDetails)}
              className="flex items-center gap-1.5 text-[11px] text-black/40 hover:text-black/60 transition-colors"
            >
              {showDetails ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              {zh ? `查询详情（扫描了 ${result.searched_devices.arp?.length || 0} 台 ARP + ${result.searched_devices.mac?.length || 0} 台 MAC）` :
                `Details (scanned ${result.searched_devices.arp?.length || 0} ARP + ${result.searched_devices.mac?.length || 0} MAC devices)`}
            </button>
          )}

          {showDetails && result.searched_devices && (
            <div className="bg-black/[0.02] rounded-xl border border-black/5 px-4 py-3 text-[11px] text-black/50 space-y-2">
              <div>
                <span className="font-semibold text-black/60">{zh ? 'ARP 查询设备' : 'ARP Devices'}:</span>{' '}
                {result.searched_devices.arp?.join(', ') || '-'}
              </div>
              <div>
                <span className="font-semibold text-black/60">{zh ? 'MAC 查询设备' : 'MAC Devices'}:</span>{' '}
                {result.searched_devices.mac?.join(', ') || '-'}
              </div>
              {(result.searched_devices.lldp?.length ?? 0) > 0 && (
                <div>
                  <span className="font-semibold text-black/60">{zh ? 'LLDP 查询设备' : 'LLDP Devices'}:</span>{' '}
                  {result.searched_devices.lldp?.join(', ')}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── History ── */}
      {history.length > 0 && !loading && (
        <div className="mt-1">
          <p className="text-[10px] font-semibold text-black/35 uppercase tracking-wider mb-1.5">{zh ? '查询历史' : 'Recent'}</p>
          <div className="flex flex-wrap gap-1.5">
            {history.map((h, i) => (
              <button
                key={i}
                onClick={() => { setIp(h.ip); }}
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-[11px] font-mono transition-all hover:shadow-sm ${h.found ? 'border-emerald-200 bg-emerald-50/50 text-emerald-700 hover:bg-emerald-50' : 'border-amber-200 bg-amber-50/50 text-amber-700 hover:bg-amber-50'}`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${h.found ? 'bg-emerald-400' : 'bg-amber-400'}`} />
                {h.ip}
                {h.found && <span className="text-[10px] text-black/30">→ {h.switch_name}:{h.port}</span>}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default IPLocatorPanel;
