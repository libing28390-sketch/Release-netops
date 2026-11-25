import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Cable,
  Plus,
  Search,
  RefreshCw,
  Pencil,
  Trash2,
  X,
  CheckCircle2,
  AlertTriangle,
  Clock,
  Circle,
  Download,
  ArrowRight,
  Layers,
  List,
  Link2,
  Unlink,
} from 'lucide-react';
import PageHero from '../../components/PageHero';
import Pagination from '../../components/Pagination';
import { ActionButton } from '../../components/ui/ActionIconButton';
import { API } from '../RackManagement/constants';
import { authHeaders } from '../RackManagement/helpers';
import {
  DeviceOption,
  InterfaceOption,
  SearchableDevicePicker,
  SearchableInterfacePicker,
} from './SearchablePickers';

export interface OdfTraySummary {
  id: string;
  tray_no: number;
  tray_code: string;
  label: string;
  port_count: number;
  fiber_mode: string;
  connector_type: string;
  occupied_count: number;
  reserved_count: number;
  fault_count: number;
  idle_count?: number;
  ports?: OdfPortRecord[];
}

export interface OdfPortRecord {
  id: string;
  frame_id: string;
  tray_id: string;
  tray_no: number;
  port_no: number;
  port_code: string;
  status: 'idle' | 'occupied' | 'reserved' | 'fault';
  fiber_type: string;
  connector_type: string;
  a_device_id: string;
  a_device_name: string;
  a_interface_name: string;
  a_rack_name: string;
  z_endpoint_type: 'device' | 'odf' | 'carrier' | 'other';
  z_device_id: string;
  z_device_name: string;
  z_interface_name: string;
  z_odf_frame_id: string;
  z_odf_port_code: string;
  z_peer_label: string;
  cable_tag: string;
  circuit_id: string;
  attenuation_db: number | null;
  remarks: string;
  updated_by?: string;
  updated_at?: string;
  frame_name?: string;
}

export interface OdfFrameSummary {
  id: string;
  site_id: string;
  site_code?: string;
  site_name?: string;
  site_label: string;
  frame_code: string;
  name: string;
  vendor: string;
  model: string;
  floor: string;
  room: string;
  row: string;
  rack_id: string;
  tray_count: number;
  ports_per_tray: number;
  total_cores: number;
  occupied_cores: number;
  reserved_cores: number;
  fault_cores: number;
  idle_cores: number;
  utilization_pct: number;
  connector_type: string;
  fiber_mode: string;
  status: string;
  remarks: string;
  trays: OdfTraySummary[];
  active_links?: OdfPortRecord[];
}

interface OdfStats {
  total_frames: number;
  total_trays: number;
  total_cores: number;
  occupied_cores: number;
  reserved_cores: number;
  fault_cores: number;
  idle_cores: number;
  utilization_pct: number;
}

interface SiteOption {
  id: string;
  site_code: string;
  site_name: string;
}

async function apiJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(init?.headers || {}) },
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok || payload?.success === false) {
    throw new Error(payload?.detail?.message || payload?.detail || payload?.message || `HTTP ${res.status}`);
  }
  return (payload?.data !== undefined ? payload.data : payload) as T;
}

const CAPACITY_PRESETS = [
  { label: '144 芯 (6×24)', trays: 6, perTray: 24, model: 'GPX147-144F' },
  { label: '288 芯 (12×24)', trays: 12, perTray: 24, model: 'GPX147-288F' },
  { label: '576 芯 (12×48)', trays: 12, perTray: 48, model: 'GPX147-576F' },
  { label: '720 芯 (15×48)', trays: 15, perTray: 48, model: 'GPX147-720F' },
];

const STATUS_META: Record<string, { zh: string; en: string; chip: string; dot: string }> = {
  occupied: { zh: '占用', en: 'Occupied', chip: 'border-emerald-500/50 bg-emerald-500/15 text-emerald-300', dot: 'bg-emerald-400' },
  reserved: { zh: '预留', en: 'Reserved', chip: 'border-amber-500/50 bg-amber-500/15 text-amber-300', dot: 'bg-amber-400' },
  fault: { zh: '故障', en: 'Fault', chip: 'border-rose-500/50 bg-rose-500/15 text-rose-300', dot: 'bg-rose-400' },
  idle: { zh: '空闲', en: 'Idle', chip: 'border-slate-700 bg-slate-900/70 text-slate-400', dot: 'bg-slate-600' },
};

const OdfManagementTab: React.FC<{ language: 'zh' | 'en' }> = ({ language }) => {
  const zh = language === 'zh';

  const [frames, setFrames] = useState<OdfFrameSummary[]>([]);
  const [stats, setStats] = useState<OdfStats | null>(null);
  const [sites, setSites] = useState<SiteOption[]>([]);
  const [devices, setDevices] = useState<DeviceOption[]>([]);
  const [siteFilter, setSiteFilter] = useState('');
  const [keyword, setKeyword] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [selectedFrameId, setSelectedFrameId] = useState(() => {
    try {
      return new URLSearchParams(window.location.search).get('frameId') || '';
    } catch {
      return '';
    }
  });
  const [frameDetail, setFrameDetail] = useState<OdfFrameSummary | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [selectedTrayNo, setSelectedTrayNo] = useState(1);
  const [centerTab, setCenterTab] = useState<'matrix' | 'ledger'>('matrix');
  const [ledgerQuery, setLedgerQuery] = useState('');
  const [ledgerStatusFilter, setLedgerStatusFilter] = useState<'all' | 'occupied' | 'reserved' | 'fault'>('all');
  const [ledgerPage, setLedgerPage] = useState(1);
  const [ledgerPageSize, setLedgerPageSize] = useState(20);

  // Global optical trace search
  const [traceQuery, setTraceQuery] = useState('');
  const [traceResults, setTraceResults] = useState<OdfPortRecord[]>([]);
  const [tracing, setTracing] = useState(false);

  // Port editor drawer state
  const [editingPort, setEditingPort] = useState<OdfPortRecord | null>(null);
  const [portForm, setPortForm] = useState({
    status: 'occupied' as 'idle' | 'occupied' | 'reserved' | 'fault',
    fiber_type: 'OS2',
    connector_type: 'LC/UPC',
    a_device_id: '',
    a_device_name: '',
    a_interface_name: '',
    a_rack_name: '',
    z_endpoint_type: 'device' as 'device' | 'odf' | 'carrier' | 'other',
    z_device_id: '',
    z_device_name: '',
    z_interface_name: '',
    z_odf_frame_id: '',
    z_odf_port_code: '',
    z_peer_label: '',
    cable_tag: '',
    circuit_id: '',
    attenuation_db: '',
    remarks: '',
    pair_next: true,
  });
  const [aInterfaces, setAInterfaces] = useState<InterfaceOption[]>([]);
  const [zInterfaces, setZInterfaces] = useState<InterfaceOption[]>([]);
  const [loadingAInterfaces, setLoadingAInterfaces] = useState(false);
  const [loadingZInterfaces, setLoadingZInterfaces] = useState(false);
  const [savingPort, setSavingPort] = useState(false);

  // Create / Edit ODF Frame modal
  const [showFrameModal, setShowFrameModal] = useState(false);
  const [editingFrame, setEditingFrame] = useState<OdfFrameSummary | null>(null);
  const [frameForm, setFrameForm] = useState({
    name: '',
    frame_code: '',
    site_id: '',
    vendor: 'Huawei',
    model: 'GPX147-576F',
    floor: '',
    room: '',
    row: '',
    tray_count: 12,
    ports_per_tray: 48,
    connector_type: 'LC/UPC',
    fiber_mode: 'mixed',
    remarks: '',
  });
  const [savingFrame, setSavingFrame] = useState(false);

  // Tray inline editor modal
  const [editingTray, setEditingTray] = useState<OdfTraySummary | null>(null);
  const [trayForm, setTrayForm] = useState({ label: '', fiber_mode: 'OS2', connector_type: 'LC/UPC' });

  const loadListAndStats = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const qs = new URLSearchParams();
      if (siteFilter) qs.set('site_id', siteFilter);
      if (keyword.trim()) qs.set('keyword', keyword.trim());
      const [listData, statsData] = await Promise.all([
        apiJson<OdfFrameSummary[]>(`${API}/odf/frames${qs.toString() ? `?${qs.toString()}` : ''}`),
        apiJson<OdfStats>(`${API}/odf/stats`),
      ]);
      setFrames(listData || []);
      setStats(statsData || null);
      setSelectedFrameId(prev => {
        if (prev && listData.some(f => f.id === prev)) return prev;
        return listData[0]?.id || '';
      });
    } catch (e: any) {
      setError(e?.message || 'Failed to load ODF CMDB');
    } finally {
      setLoading(false);
    }
  }, [siteFilter, keyword]);

  const loadFrameDetail = useCallback(async (frameId: string) => {
    if (!frameId) {
      setFrameDetail(null);
      return;
    }
    setDetailLoading(true);
    try {
      const detail = await apiJson<OdfFrameSummary>(`${API}/odf/frames/${encodeURIComponent(frameId)}/detail`);
      setFrameDetail(detail);
      setSelectedTrayNo(prev => {
        if (detail.trays?.some(t => t.tray_no === prev)) return prev;
        return detail.trays?.[0]?.tray_no || 1;
      });
    } catch (e: any) {
      setError(e?.message || 'Failed to load ODF detail');
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadListAndStats();
  }, [loadListAndStats]);

  useEffect(() => {
    void loadFrameDetail(selectedFrameId);
  }, [selectedFrameId, loadFrameDetail]);

  useEffect(() => {
    apiJson<SiteOption[]>(`${API}/cmdb/sites`).then(setSites).catch(() => {});
    apiJson<DeviceOption[]>(`${API}/odf/lookup/devices?limit=150`).then(setDevices).catch(() => {});
  }, []);

  const searchRemoteDevices = useCallback(async (q: string): Promise<DeviceOption[]> => {
    return apiJson<DeviceOption[]>(
      `${API}/odf/lookup/devices?q=${encodeURIComponent(q)}&limit=60`,
    );
  }, []);

  useEffect(() => {
    if (!portForm.a_device_id) {
      setAInterfaces([]);
      setLoadingAInterfaces(false);
      return;
    }
    let cancelled = false;
    setLoadingAInterfaces(true);
    apiJson<InterfaceOption[]>(`${API}/odf/lookup/devices/${encodeURIComponent(portForm.a_device_id)}/interfaces`)
      .then(list => { if (!cancelled) setAInterfaces(list); })
      .catch(() => { if (!cancelled) setAInterfaces([]); })
      .finally(() => { if (!cancelled) setLoadingAInterfaces(false); });
    return () => { cancelled = true; };
  }, [portForm.a_device_id]);

  useEffect(() => {
    if (portForm.z_endpoint_type !== 'device' || !portForm.z_device_id) {
      setZInterfaces([]);
      setLoadingZInterfaces(false);
      return;
    }
    let cancelled = false;
    setLoadingZInterfaces(true);
    apiJson<InterfaceOption[]>(`${API}/odf/lookup/devices/${encodeURIComponent(portForm.z_device_id)}/interfaces`)
      .then(list => { if (!cancelled) setZInterfaces(list); })
      .catch(() => { if (!cancelled) setZInterfaces([]); })
      .finally(() => { if (!cancelled) setLoadingZInterfaces(false); });
    return () => { cancelled = true; };
  }, [portForm.z_endpoint_type, portForm.z_device_id]);

  const activeTray = useMemo(
    () => frameDetail?.trays?.find(t => t.tray_no === selectedTrayNo) || frameDetail?.trays?.[0] || null,
    [frameDetail, selectedTrayNo],
  );

  const openPortEditor = (port: OdfPortRecord) => {
    setSelectedTrayNo(port.tray_no);
    setEditingPort(port);
    setPortForm({
      status: port.status === 'idle' ? 'occupied' : port.status,
      fiber_type: port.fiber_type || activeTray?.fiber_mode || 'OS2',
      connector_type: port.connector_type || activeTray?.connector_type || 'LC/UPC',
      a_device_id: port.a_device_id || '',
      a_device_name: port.a_device_name || '',
      a_interface_name: port.a_interface_name || '',
      a_rack_name: port.a_rack_name || '',
      z_endpoint_type: port.z_endpoint_type || 'device',
      z_device_id: port.z_device_id || '',
      z_device_name: port.z_device_name || '',
      z_interface_name: port.z_interface_name || '',
      z_odf_frame_id: port.z_odf_frame_id || '',
      z_odf_port_code: port.z_odf_port_code || '',
      z_peer_label: port.z_peer_label || '',
      cable_tag: port.cable_tag || '',
      circuit_id: port.circuit_id || '',
      attenuation_db: port.attenuation_db != null ? String(port.attenuation_db) : '',
      remarks: port.remarks || '',
      pair_next: port.status === 'idle' && port.port_no % 2 === 1,
    });
  };

  const handleSavePort = async (release = false) => {
    if (!editingPort || !frameDetail) return;
    setSavingPort(true);
    try {
      const body = release
        ? { status: 'idle', pair_next: false }
        : {
            ...portForm,
            attenuation_db: portForm.attenuation_db.trim() === '' ? null : Number(portForm.attenuation_db),
          };
      await apiJson(
        `${API}/odf/frames/${encodeURIComponent(frameDetail.id)}/ports/${editingPort.tray_no}/${editingPort.port_no}`,
        { method: 'PUT', body: JSON.stringify(body) },
      );
      setEditingPort(null);
      await Promise.all([loadFrameDetail(frameDetail.id), loadListAndStats()]);
    } catch (e: any) {
      setError(e?.message || 'Failed to save port binding');
    } finally {
      setSavingPort(false);
    }
  };

  const openCreateFrameModal = () => {
    setEditingFrame(null);
    setFrameForm({
      name: `ODF-${String(frames.length + 1).padStart(2, '0')}`,
      frame_code: `ODF-${String(frames.length + 1).padStart(2, '0')}`,
      site_id: sites[0]?.id || '',
      vendor: 'Huawei',
      model: 'GPX147-576F',
      floor: '1F',
      room: '核心机房',
      row: 'ODF-A',
      tray_count: 12,
      ports_per_tray: 48,
      connector_type: 'LC/UPC',
      fiber_mode: 'mixed',
      remarks: '',
    });
    setShowFrameModal(true);
  };

  const openEditFrameModal = (frame: OdfFrameSummary) => {
    setEditingFrame(frame);
    setFrameForm({
      name: frame.name,
      frame_code: frame.frame_code,
      site_id: frame.site_id,
      vendor: frame.vendor || '',
      model: frame.model || '',
      floor: frame.floor || '',
      room: frame.room || '',
      row: frame.row || '',
      tray_count: frame.tray_count,
      ports_per_tray: frame.ports_per_tray,
      connector_type: frame.connector_type || 'LC/UPC',
      fiber_mode: frame.fiber_mode || 'OS2',
      remarks: frame.remarks || '',
    });
    setShowFrameModal(true);
  };

  const handleSaveFrame = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingFrame(true);
    setError('');
    try {
      if (editingFrame) {
        const updated = await apiJson<OdfFrameSummary>(`${API}/odf/frames/${encodeURIComponent(editingFrame.id)}`, {
          method: 'PUT',
          body: JSON.stringify({
            name: frameForm.name,
            frame_code: frameForm.frame_code,
            site_id: frameForm.site_id,
            vendor: frameForm.vendor,
            model: frameForm.model,
            floor: frameForm.floor,
            room: frameForm.room,
            row: frameForm.row,
            connector_type: frameForm.connector_type,
            fiber_mode: frameForm.fiber_mode,
            remarks: frameForm.remarks,
          }),
        });
        setFrameDetail(updated);
      } else {
        const created = await apiJson<OdfFrameSummary>(`${API}/odf/frames`, {
          method: 'POST',
          body: JSON.stringify(frameForm),
        });
        setSelectedFrameId(created.id);
        setFrameDetail(created);
      }
      setShowFrameModal(false);
      await loadListAndStats();
    } catch (err: any) {
      setError(err?.message || 'Save ODF failed');
    } finally {
      setSavingFrame(false);
    }
  };

  const handleDeleteFrame = async (frame: OdfFrameSummary) => {
    if (!window.confirm(zh ? `确认删除 ODF 配线架「${frame.name}」吗？` : `Delete ODF frame "${frame.name}"?`)) return;
    try {
      await apiJson(`${API}/odf/frames/${encodeURIComponent(frame.id)}`, { method: 'DELETE' });
      await loadListAndStats();
    } catch (err: any) {
      setError(err?.message || 'Delete failed');
    }
  };

  const handleSaveTray = async () => {
    if (!editingTray || !frameDetail) return;
    try {
      await apiJson(`${API}/odf/trays/${encodeURIComponent(editingTray.id)}`, {
        method: 'PUT',
        body: JSON.stringify(trayForm),
      });
      setEditingTray(null);
      await Promise.all([loadFrameDetail(frameDetail.id), loadListAndStats()]);
    } catch (err: any) {
      setError(err?.message || 'Failed to update tray');
    }
  };

  const handleRunTrace = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const q = traceQuery.trim();
    if (!q) {
      setTraceResults([]);
      return;
    }
    setTracing(true);
    try {
      const items = await apiJson<OdfPortRecord[]>(`${API}/odf/trace?q=${encodeURIComponent(q)}`);
      setTraceResults(items || []);
    } catch {
      setTraceResults([]);
    } finally {
      setTracing(false);
    }
  };

  const handleExportCsv = () => {
    if (!frameDetail) return;
    const links = frameDetail.active_links || [];
    const header = ['ODF配线架', '端子编号', '状态', '光纤类型', 'A端设备', 'A端接口', 'Z端类型', 'Z端设备/对端', 'Z端接口/端子', '光缆标签', '电路号', '衰耗(dB)', '备注'];
    const rows = links.map(l => [
      frameDetail.name,
      l.port_code,
      STATUS_META[l.status]?.zh || l.status,
      l.fiber_type,
      l.a_device_name,
      l.a_interface_name,
      l.z_endpoint_type,
      l.z_endpoint_type === 'device' ? l.z_device_name : l.z_peer_label,
      l.z_endpoint_type === 'device' ? l.z_interface_name : l.z_odf_port_code,
      l.cable_tag,
      l.circuit_id,
      l.attenuation_db ?? '',
      l.remarks,
    ]);
    const csv = '\uFEFF' + [header, ...rows].map(r => r.map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${frameDetail.name}-ODF-cross-connects.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const portGroups = useMemo(() => {
    const ports = activeTray?.ports || [];
    const groups: OdfPortRecord[][] = [];
    for (let i = 0; i < ports.length; i += 12) {
      groups.push(ports.slice(i, i + 12));
    }
    return groups;
  }, [activeTray]);

  const filteredLedgerLinks = useMemo(() => {
    const links = frameDetail?.active_links || [];
    const q = ledgerQuery.trim().toLowerCase();
    return links.filter(link => {
      if (ledgerStatusFilter !== 'all' && link.status !== ledgerStatusFilter) return false;
      if (!q) return true;
      const hay = [
        link.port_code,
        link.a_device_name,
        link.a_interface_name,
        link.z_device_name,
        link.z_interface_name,
        link.z_peer_label,
        link.z_odf_port_code,
        link.cable_tag,
        link.circuit_id,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return hay.includes(q);
    });
  }, [frameDetail?.active_links, ledgerQuery, ledgerStatusFilter]);

  useEffect(() => {
    setLedgerPage(1);
  }, [selectedFrameId, ledgerQuery, ledgerStatusFilter, ledgerPageSize]);

  const ledgerTotalPages = Math.max(1, Math.ceil(filteredLedgerLinks.length / ledgerPageSize));
  const effectiveLedgerPage = Math.min(ledgerPage, ledgerTotalPages);
  const paginatedLedgerLinks = useMemo(() => {
    const start = (effectiveLedgerPage - 1) * ledgerPageSize;
    return filteredLedgerLinks.slice(start, start + ledgerPageSize);
  }, [filteredLedgerLinks, effectiveLedgerPage, ledgerPageSize]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <PageHero
        icon={Cable}
        title={zh ? '光配管理 (ODF CMDB)' : 'ODF Optical Distribution CMDB'}
        subtitle={
          zh
            ? '管理 ODF 光纤配线架、熔配盘与 576 芯 LC/SC 端子跳接台账，实时联动 3D 机房数字孪生'
            : 'Manage ODF frames, modular splice trays, and fiber cross-connect ledgers synced live with the 3D Data Center'
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {stats && (
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className="rounded-lg border border-slate-300/60 dark:border-slate-700 bg-white/70 dark:bg-slate-900/70 px-2.5 py-1 font-medium">
                  {stats.total_frames} {zh ? '台 ODF' : 'Frames'}
                </span>
                <span className="rounded-lg border border-emerald-500/35 bg-emerald-500/10 px-2.5 py-1 font-semibold text-emerald-600 dark:text-emerald-300">
                  {stats.occupied_cores}/{stats.total_cores} {zh ? '芯已用' : 'Used'} ({stats.utilization_pct}%)
                </span>
                {stats.fault_cores > 0 && (
                  <span className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-2.5 py-1 font-semibold text-rose-500">
                    {stats.fault_cores} {zh ? '故障' : 'Fault'}
                  </span>
                )}
              </div>
            )}
            <ActionButton
              variant="primary"
              size="sm"
              icon={Plus}
              onClick={openCreateFrameModal}
            >
              {zh ? '新建 ODF 配线架' : 'New ODF Frame'}
            </ActionButton>
          </div>
        }
      />

      {/* Global End-to-End Fiber Trace Bar */}
      <form
        onSubmit={handleRunTrace}
        className="flex flex-wrap items-center gap-2 rounded-xl border px-3 py-2"
        style={{ background: 'var(--card-bg)', borderColor: 'var(--card-border)' }}
      >
        <Search size={14} className="text-cyan-500 shrink-0" />
        <input
          value={traceQuery}
          onChange={e => setTraceQuery(e.target.value)}
          placeholder={zh ? '全局光路追溯：输入设备名、接口（如 GE1/0/49）、端子号（A01-01）、光缆标签或电路号…' : 'Trace optical path by device, interface, port code, cable tag, or circuit ID…'}
          className="min-w-[260px] flex-1 bg-transparent text-xs outline-none"
          style={{ color: 'var(--body-text)' }}
        />
        <button
          type="submit"
          disabled={tracing}
          className="rounded-lg bg-cyan-600 px-3 py-1 text-xs font-medium text-white hover:bg-cyan-700 disabled:opacity-50"
        >
          {tracing ? (zh ? '追溯中…' : 'Tracing…') : (zh ? '光路追溯' : 'Trace')}
        </button>
        {traceResults.length > 0 && (
          <button
            type="button"
            onClick={() => { setTraceQuery(''); setTraceResults([]); }}
            className="rounded-lg border px-2 py-1 text-xs"
            style={{ borderColor: 'var(--card-border)', color: 'var(--muted-text)' }}
          >
            {zh ? '清空' : 'Clear'}
          </button>
        )}
      </form>

      {traceResults.length > 0 && (
        <div
          className="rounded-xl border p-2.5 text-xs"
          style={{ background: 'var(--card-bg)', borderColor: 'var(--card-border)' }}
        >
          <div className="mb-1.5 flex items-center justify-between font-semibold" style={{ color: 'var(--heading-text)' }}>
            <span>{zh ? `光路追溯命中 ${traceResults.length} 条记录` : `${traceResults.length} optical trace hit(s)`}</span>
          </div>
          <div className="max-h-36 space-y-1 overflow-y-auto">
            {traceResults.map(hit => (
              <button
                key={`${hit.frame_id}-${hit.port_code}`}
                type="button"
                onClick={() => {
                  setSelectedFrameId(hit.frame_id);
                  setSelectedTrayNo(hit.tray_no);
                  setCenterTab('matrix');
                  openPortEditor(hit);
                }}
                className="flex w-full items-center justify-between gap-2 rounded-lg border border-transparent px-2.5 py-1.5 text-left hover:border-cyan-500/40 hover:bg-cyan-500/5"
              >
                <span className="font-mono font-bold text-cyan-500">
                  {hit.frame_name || hit.frame_id} · {hit.port_code}
                </span>
                <span className="flex-1 truncate" style={{ color: 'var(--body-text)' }}>
                  {hit.a_device_name || '—'} {hit.a_interface_name} ⇄ {hit.z_device_name || hit.z_peer_label || '—'} {hit.z_interface_name || hit.z_odf_port_code}
                </span>
                {hit.cable_tag && <span className="font-mono text-[10px] text-amber-500">{hit.cable_tag}</span>}
              </button>
            ))}
          </div>
        </div>
      )}

      {error && (
        <div className="flex items-center justify-between rounded-xl border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-500">
          <span>{error}</span>
          <button type="button" onClick={() => setError('')}><X size={14} /></button>
        </div>
      )}

      {/* Main 3-Column ODF Engineering Workbench */}
      <div className="flex min-h-0 flex-1 gap-3 overflow-hidden">
        {/* Left: ODF Frame List */}
        <div
          className="flex w-64 shrink-0 flex-col rounded-xl border overflow-hidden"
          style={{ background: 'var(--card-bg)', borderColor: 'var(--card-border)' }}
        >
          <div className="space-y-2 border-b p-2.5" style={{ borderColor: 'var(--card-border)' }}>
            <input
              value={keyword}
              onChange={e => setKeyword(e.target.value)}
              placeholder={zh ? '搜索 ODF 名称 / 编号 / 机房' : 'Filter ODF frames…'}
              className="w-full rounded-lg border px-2.5 py-1.5 text-xs outline-none"
              style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
            />
            <select
              value={siteFilter}
              onChange={e => setSiteFilter(e.target.value)}
              className="w-full rounded-lg border px-2 py-1.5 text-xs"
              style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
            >
              <option value="">{zh ? '全部站点' : 'All Sites'}</option>
              {sites.map(s => (
                <option key={s.id} value={s.id}>{s.site_name || s.site_code}</option>
              ))}
            </select>
          </div>

          <div className="flex-1 space-y-1.5 overflow-y-auto p-2">
            {loading ? (
              <div className="flex items-center justify-center py-10 text-xs" style={{ color: 'var(--muted-text)' }}>
                <RefreshCw size={14} className="mr-1.5 animate-spin" /> {zh ? '加载中…' : 'Loading…'}
              </div>
            ) : frames.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-2 px-3 py-10 text-center">
                <Cable size={28} className="text-slate-400" />
                <div className="text-xs font-medium" style={{ color: 'var(--heading-text)' }}>
                  {zh ? '暂未纳管 ODF 配线架' : 'No ODF frames yet'}
                </div>
                <p className="text-[11px]" style={{ color: 'var(--muted-text)' }}>
                  {zh ? '新建首台 ODF 后，将自动生成熔配盘并实时同步到 3D 机房光配区。' : 'Create an ODF frame to manage fiber cores and sync live into the 3D hall.'}
                </p>
                <button
                  type="button"
                  onClick={openCreateFrameModal}
                  className="mt-1 rounded-lg bg-cyan-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-cyan-700"
                >
                  + {zh ? '新建首台 ODF' : 'Create ODF'}
                </button>
              </div>
            ) : (
              frames.map(frame => {
                const selected = frame.id === selectedFrameId;
                return (
                  <div
                    key={frame.id}
                    onClick={() => setSelectedFrameId(frame.id)}
                    className={`cursor-pointer rounded-xl border p-2.5 transition-all ${
                      selected
                        ? 'border-cyan-500 bg-cyan-500/10 shadow-sm'
                        : 'border-transparent hover:border-slate-500/30 hover:bg-slate-500/5'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-1">
                      <div className="min-w-0">
                        <div className="truncate text-xs font-bold" style={{ color: 'var(--heading-text)' }}>{frame.name}</div>
                        <div className="truncate text-[10px]" style={{ color: 'var(--muted-text)' }}>
                          {frame.site_label} · {frame.room || '—'} · {frame.connector_type}
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-0.5">
                        <button
                          type="button"
                          onClick={e => { e.stopPropagation(); openEditFrameModal(frame); }}
                          className="rounded p-1 hover:bg-slate-500/15"
                          title={zh ? '编辑' : 'Edit'}
                        >
                          <Pencil size={11} />
                        </button>
                        <button
                          type="button"
                          onClick={e => { e.stopPropagation(); void handleDeleteFrame(frame); }}
                          className="rounded p-1 text-rose-500 hover:bg-rose-500/15"
                          title={zh ? '删除' : 'Delete'}
                        >
                          <Trash2 size={11} />
                        </button>
                      </div>
                    </div>
                    <div className="mt-2 flex items-center justify-between text-[10px]">
                      <span className="font-mono font-semibold text-emerald-500">
                        {frame.occupied_cores}/{frame.total_cores} {zh ? '芯' : 'F'}
                      </span>
                      <span style={{ color: 'var(--muted-text)' }}>{frame.utilization_pct}%</span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-700/30">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-emerald-400"
                        style={{ width: `${Math.min(100, frame.utilization_pct)}%` }}
                      />
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Center: 2D ODF Tray Elevation + 48-Core LC/UPC Matrix OR Cross-Connect Ledger */}
        <div
          className="flex min-w-0 flex-1 flex-col rounded-xl border overflow-hidden"
          style={{ background: 'var(--card-bg)', borderColor: 'var(--card-border)' }}
        >
          {!frameDetail ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 text-xs" style={{ color: 'var(--muted-text)' }}>
              {detailLoading ? (
                <>
                  <RefreshCw size={18} className="animate-spin text-cyan-500" />
                  <span>{zh ? '正在加载 ODF 熔配盘…' : 'Loading ODF trays…'}</span>
                </>
              ) : (
                <span>{zh ? '请在左侧选择或新建一台 ODF 配线架' : 'Select or create an ODF frame on the left'}</span>
              )}
            </div>
          ) : (
            <>
              {/* Top sub-toolbar */}
              <div
                className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2"
                style={{ borderColor: 'var(--card-border)' }}
              >
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold" style={{ color: 'var(--heading-text)' }}>{frameDetail.name}</span>
                  <span className="rounded border border-slate-500/30 px-1.5 py-0.5 font-mono text-[10px]" style={{ color: 'var(--muted-text)' }}>
                    {frameDetail.vendor} {frameDetail.model}
                  </span>
                  <span className="rounded border border-cyan-500/35 bg-cyan-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-cyan-500">
                    {frameDetail.tray_count} 盘 × {frameDetail.ports_per_tray} 芯 = {frameDetail.total_cores}F
                  </span>
                </div>

                <div className="flex items-center gap-1.5">
                  <div className="flex rounded-lg border p-0.5 text-xs" style={{ borderColor: 'var(--card-border)' }}>
                    <button
                      type="button"
                      onClick={() => setCenterTab('matrix')}
                      className={`flex items-center gap-1 rounded-md px-2.5 py-1 font-medium ${
                        centerTab === 'matrix' ? 'bg-cyan-600 text-white' : ''
                      }`}
                    >
                      <Layers size={12} /> {zh ? '2D 熔配盘矩阵' : '2D Tray Matrix'}
                    </button>
                    <button
                      type="button"
                      onClick={() => setCenterTab('ledger')}
                      className={`flex items-center gap-1 rounded-md px-2.5 py-1 font-medium ${
                        centerTab === 'ledger' ? 'bg-cyan-600 text-white' : ''
                      }`}
                    >
                      <List size={12} /> {zh ? `跳纤台账 (${frameDetail.active_links?.length || 0})` : `Ledger (${frameDetail.active_links?.length || 0})`}
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={handleExportCsv}
                    className="flex items-center gap-1 rounded-lg border px-2.5 py-1 text-xs hover:bg-slate-500/10"
                    style={{ borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                  >
                    <Download size={12} /> CSV
                  </button>
                </div>
              </div>

              {centerTab === 'matrix' ? (
                <div className="flex min-h-0 flex-1 overflow-hidden">
                  {/* Left Sub-column: 12-Tray ODF Rack Elevation Selector */}
                  <div
                    className="w-52 shrink-0 space-y-1.5 overflow-y-auto border-r p-2.5"
                    style={{ borderColor: 'var(--card-border)' }}
                  >
                    <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide" style={{ color: 'var(--muted-text)' }}>
                      {zh ? '熔配单元框 (自上而下)' : 'Splice Trays'}
                    </div>
                    {[...(frameDetail.trays || [])].reverse().map(tray => {
                      const active = tray.tray_no === activeTray?.tray_no;
                      const pct = tray.port_count > 0 ? Math.round((tray.occupied_count / tray.port_count) * 100) : 0;
                      const isOm4 = tray.fiber_mode === 'OM4' || tray.fiber_mode === 'OM3';
                      return (
                        <div
                          key={tray.id}
                          onClick={() => setSelectedTrayNo(tray.tray_no)}
                          className={`cursor-pointer rounded-lg border p-2 transition-all ${
                            active
                              ? 'border-cyan-500 bg-cyan-500/12 shadow-sm'
                              : 'border-slate-500/20 hover:border-slate-500/45'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-1">
                            <span className="font-mono text-xs font-bold" style={{ color: 'var(--heading-text)' }}>
                              {tray.tray_code}
                            </span>
                            <span
                              className={`rounded px-1 py-0.5 text-[9px] font-bold ${
                                isOm4 ? 'bg-teal-500/15 text-teal-400' : 'bg-blue-500/15 text-blue-400'
                              }`}
                            >
                              {tray.fiber_mode}
                            </span>
                            <button
                              type="button"
                              onClick={e => {
                                e.stopPropagation();
                                setEditingTray(tray);
                                setTrayForm({
                                  label: tray.label || '',
                                  fiber_mode: tray.fiber_mode || 'OS2',
                                  connector_type: tray.connector_type || 'LC/UPC',
                                });
                              }}
                              className="rounded p-0.5 opacity-60 hover:opacity-100"
                              title={zh ? '编辑熔配盘' : 'Edit Tray'}
                            >
                              <Pencil size={10} />
                            </button>
                          </div>
                          <div className="mt-0.5 truncate text-[10px]" style={{ color: 'var(--muted-text)' }}>
                            {tray.label || `${zh ? '第' : 'Tray '} ${tray.tray_no}`}
                          </div>
                          <div className="mt-1.5 flex items-center gap-1.5">
                            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-700/35">
                              <div className="h-full rounded-full bg-emerald-400" style={{ width: `${pct}%` }} />
                            </div>
                            <span className="font-mono text-[9px]" style={{ color: 'var(--muted-text)' }}>
                              {tray.occupied_count}/{tray.port_count}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Right Sub-column: Zoomed 48-Core LC/UPC Industrial Patch Faceplate */}
                  <div className="flex-1 overflow-y-auto p-4">
                    {activeTray && (
                      <div className="space-y-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div>
                            <h3 className="text-sm font-bold" style={{ color: 'var(--heading-text)' }}>
                              {activeTray.tray_code} · {activeTray.label}
                            </h3>
                            <p className="text-[11px]" style={{ color: 'var(--muted-text)' }}>
                              {activeTray.fiber_mode} · {activeTray.connector_type} · {zh ? '点击任意纤芯端子配置或追溯 A/Z 端跳纤关系' : 'Click any fiber port to bind or inspect A/Z cross-connect'}
                            </p>
                          </div>
                          <div className="flex items-center gap-3 text-[11px]">
                            {(['occupied', 'reserved', 'fault', 'idle'] as const).map(st => (
                              <span key={st} className="flex items-center gap-1" style={{ color: 'var(--muted-text)' }}>
                                <span className={`h-2 w-2 rounded-full ${STATUS_META[st].dot}`} />
                                {zh ? STATUS_META[st].zh : STATUS_META[st].en}
                              </span>
                            ))}
                          </div>
                        </div>

                        {/* Authentic Dark Metallic ODF Subrack Panel with 4 × 12-Core Adapter Cartridges */}
                        <div className="rounded-2xl border border-slate-700 bg-slate-950 p-4 shadow-inner">
                          <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
                            {portGroups.map((group, gIdx) => {
                              const startNo = gIdx * 12 + 1;
                              const endNo = Math.min(activeTray.port_count, startNo + 11);
                              return (
                                <div
                                  key={`grp-${gIdx}`}
                                  className="rounded-xl border border-slate-800 bg-slate-900/90 p-3"
                                >
                                  <div className="mb-2 flex items-center justify-between text-[10px] font-mono text-slate-400">
                                    <span>
                                      {zh ? `模块盒 #${gIdx + 1}` : `Cassette #${gIdx + 1}`} ({String(startNo).padStart(2, '0')}–{String(endNo).padStart(2, '0')})
                                    </span>
                                    <span className="text-slate-500">{activeTray.connector_type}</span>
                                  </div>
                                  <div className="grid grid-cols-6 gap-1.5">
                                    {group.map(port => {
                                      const isSelected =
                                        editingPort?.tray_no === port.tray_no && editingPort?.port_no === port.port_no;
                                      const meta = STATUS_META[port.status] || STATUS_META.idle;
                                      const peerSummary =
                                        port.a_device_name || port.z_device_name || port.z_peer_label
                                          ? `${port.a_device_name || '?'} ${port.a_interface_name || ''} ⇄ ${port.z_device_name || port.z_peer_label || '?'}`
                                          : (zh ? '空闲端子 · 点击绑定' : 'Idle · Click to bind');
                                      return (
                                        <button
                                          key={port.port_code}
                                          type="button"
                                          onClick={() => openPortEditor(port)}
                                          title={`${port.port_code} (${zh ? meta.zh : meta.en})\n${peerSummary}`}
                                          className={`group flex flex-col items-center justify-between rounded-lg border px-1.5 py-2 transition-all ${
                                            isSelected
                                              ? 'border-cyan-400 bg-cyan-500/20 ring-2 ring-cyan-400/50'
                                              : meta.chip + ' hover:border-cyan-400/70'
                                          }`}
                                        >
                                          <span className="font-mono text-[10px] font-bold">
                                            {String(port.port_no).padStart(2, '0')}
                                          </span>
                                          <span className={`my-1 h-2 w-2 rounded-full ${meta.dot}`} />
                                          <span className="w-full truncate text-center text-[8px] opacity-80">
                                            {port.a_device_name || (port.status === 'idle' ? '—' : (zh ? meta.zh : meta.en))}
                                          </span>
                                        </button>
                                      );
                                    })}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                /* Active Cross-Connect Ledger Table with Inline Search & Status Filter */
                <div className="flex flex-1 flex-col overflow-hidden">
                  <div
                    className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2"
                    style={{ borderColor: 'var(--card-border)' }}
                  >
                    <div className="flex min-w-[200px] flex-1 items-center gap-1.5 rounded-lg border px-2.5 py-1" style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)' }}>
                      <Search size={12} className="shrink-0 text-slate-400" />
                      <input
                        value={ledgerQuery}
                        onChange={e => setLedgerQuery(e.target.value)}
                        placeholder={zh ? '筛选端子、A/Z 端设备、接口、光缆或电路号…' : 'Filter by port, device, interface, cable, or circuit…'}
                        className="min-w-0 flex-1 bg-transparent text-xs outline-none"
                        style={{ color: 'var(--body-text)' }}
                      />
                      {ledgerQuery && (
                        <button type="button" onClick={() => setLedgerQuery('')} className="text-slate-400 hover:text-slate-200">
                          <X size={12} />
                        </button>
                      )}
                    </div>
                    <div className="flex items-center gap-1 text-[11px]">
                      {(['all', 'occupied', 'reserved', 'fault'] as const).map(st => {
                        const active = ledgerStatusFilter === st;
                        const label = st === 'all' ? (zh ? '全部' : 'All') : (zh ? STATUS_META[st].zh : STATUS_META[st].en);
                        return (
                          <button
                            key={st}
                            type="button"
                            onClick={() => setLedgerStatusFilter(st)}
                            className={`rounded-md border px-2 py-0.5 font-medium transition-colors ${
                              active
                                ? 'border-cyan-500 bg-cyan-500/15 text-cyan-500'
                                : 'border-transparent hover:bg-slate-500/10'
                            }`}
                            style={{ color: active ? undefined : 'var(--muted-text)' }}
                          >
                            {label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <div className="flex-1 overflow-auto p-3">
                    {filteredLedgerLinks.length === 0 ? (
                      <div className="flex h-full flex-col items-center justify-center gap-2 text-xs" style={{ color: 'var(--muted-text)' }}>
                        <Link2 size={24} className="opacity-40" />
                        <span>
                          {(frameDetail.active_links || []).length === 0
                            ? (zh ? '当前 ODF 暂无已登记跳纤，切回 2D 熔配盘点击任意端子即可绑定。' : 'No cross-connects recorded yet.')
                            : (zh ? '没有符合筛选条件的跳纤记录。' : 'No cross-connects match the filter.')}
                        </span>
                      </div>
                    ) : (
                      <table className="w-full table-auto border-collapse text-left text-xs">
                        <thead>
                          <tr className="border-b text-[11px]" style={{ borderColor: 'var(--card-border)', color: 'var(--muted-text)' }}>
                            <th className="px-1.5 py-2 whitespace-nowrap">{zh ? '端子号' : 'Port'}</th>
                            <th className="px-1.5 py-2 whitespace-nowrap">{zh ? '状态' : 'Status'}</th>
                            <th className="px-1.5 py-2">{zh ? 'A 端设备 / 接口' : 'A-End Device / Port'}</th>
                            <th className="px-1.5 py-2">{zh ? 'Z 端对端' : 'Z-End Peer'}</th>
                            <th className="px-1.5 py-2">{zh ? '光缆 / 电路号' : 'Cable / Circuit'}</th>
                            <th className="px-1.5 py-2 whitespace-nowrap">{zh ? '衰耗' : 'Loss'}</th>
                            <th className="px-1.5 py-2 text-right whitespace-nowrap">{zh ? '操作' : 'Action'}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {paginatedLedgerLinks.map(link => {
                            const meta = STATUS_META[link.status] || STATUS_META.idle;
                            return (
                              <tr key={link.id || link.port_code} className="border-b hover:bg-slate-500/5" style={{ borderColor: 'var(--card-border)' }}>
                                <td className="px-1.5 py-1.5 font-mono font-bold text-cyan-500 whitespace-nowrap">{link.port_code}</td>
                                <td className="px-1.5 py-1.5 whitespace-nowrap">
                                  <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium ${meta.chip}`}>
                                    <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
                                    {zh ? meta.zh : meta.en}
                                  </span>
                                </td>
                                <td className="px-1.5 py-1.5 max-w-[170px]">
                                  <div className="truncate font-medium" style={{ color: 'var(--heading-text)' }}>{link.a_device_name || '—'}</div>
                                  <div className="truncate font-mono text-[10px]" style={{ color: 'var(--muted-text)' }}>{link.a_interface_name || '—'}</div>
                                </td>
                                <td className="px-1.5 py-1.5 max-w-[170px]">
                                  <div className="truncate font-medium" style={{ color: 'var(--heading-text)' }}>
                                    {link.z_endpoint_type === 'device' ? (link.z_device_name || '—') : (link.z_peer_label || '—')}
                                  </div>
                                  <div className="truncate font-mono text-[10px]" style={{ color: 'var(--muted-text)' }}>
                                    {link.z_endpoint_type === 'device' ? (link.z_interface_name || '—') : (link.z_odf_port_code || link.z_endpoint_type)}
                                  </div>
                                </td>
                                <td className="px-1.5 py-1.5 max-w-[130px] font-mono text-[11px]">
                                  <div className="truncate">{link.cable_tag || '—'}</div>
                                  {link.circuit_id && <div className="truncate text-[10px] text-amber-500">{link.circuit_id}</div>}
                                </td>
                                <td className="px-1.5 py-1.5 font-mono text-[11px] whitespace-nowrap">
                                  {link.attenuation_db != null ? `${link.attenuation_db} dB` : '—'}
                                </td>
                                <td className="px-1.5 py-1.5 text-right whitespace-nowrap">
                                  <button
                                    type="button"
                                    onClick={() => openPortEditor(link)}
                                    className="rounded-md border border-cyan-500/40 px-2 py-0.5 text-[11px] text-cyan-500 hover:bg-cyan-500/10"
                                  >
                                    {zh ? '编辑' : 'Edit'}
                                  </button>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    )}
                  </div>
                  <Pagination
                    currentPage={effectiveLedgerPage}
                    totalItems={filteredLedgerLinks.length}
                    itemsPerPage={ledgerPageSize}
                    onPageChange={setLedgerPage}
                    onItemsPerPageChange={size => {
                      setLedgerPageSize(size);
                      setLedgerPage(1);
                    }}
                    language={language}
                    itemLabel={zh ? '条跳纤' : 'links'}
                  />
                </div>
              )}
            </>
          )}
        </div>

        {/* Right: Port Cross-Connect Binding Drawer */}
        {editingPort && frameDetail && (
          <div
            className="flex w-80 shrink-0 flex-col rounded-xl border overflow-hidden shadow-xl"
            style={{ background: 'var(--card-bg)', borderColor: 'var(--card-border)' }}
          >
            <div className="flex items-center justify-between border-b px-3 py-2.5" style={{ borderColor: 'var(--card-border)' }}>
              <div>
                <div className="font-mono text-sm font-bold text-cyan-500">{frameDetail.name} · {editingPort.port_code}</div>
                <div className="text-[10px]" style={{ color: 'var(--muted-text)' }}>
                  {zh ? '纤芯跳接与端到端光路绑定' : 'Fiber Cross-Connect Binding'}
                </div>
              </div>
              <button type="button" onClick={() => setEditingPort(null)} className="rounded p-1 hover:bg-slate-500/15">
                <X size={15} />
              </button>
            </div>

            <div className="flex-1 space-y-3 overflow-y-auto p-3 text-xs">
              {/* Visual Optical Path Preview */}
              <div className="rounded-xl border border-cyan-500/30 bg-slate-950/85 p-2.5 text-[11px] text-slate-200">
                <div className="flex items-center justify-between gap-1 font-mono">
                  <span className="truncate text-emerald-400">{portForm.a_device_name || (zh ? 'A 端设备' : 'A-End')}</span>
                  <ArrowRight size={12} className="shrink-0 text-slate-500" />
                  <span className="shrink-0 font-bold text-cyan-300">{editingPort.port_code}</span>
                  <ArrowRight size={12} className="shrink-0 text-slate-500" />
                  <span className="truncate text-amber-300">
                    {portForm.z_endpoint_type === 'device' ? (portForm.z_device_name || (zh ? 'Z 端设备' : 'Z-End')) : (portForm.z_peer_label || (zh ? '对端目标' : 'Peer'))}
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <label className="block">
                  <span className="text-[10px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '端子状态' : 'Status'}</span>
                  <select
                    value={portForm.status}
                    onChange={e => setPortForm(p => ({ ...p, status: e.target.value as any }))}
                    className="mt-1 w-full rounded-lg border px-2 py-1.5 text-xs"
                    style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                  >
                    <option value="occupied">{zh ? '占用 (在用)' : 'Occupied'}</option>
                    <option value="reserved">{zh ? '预留' : 'Reserved'}</option>
                    <option value="fault">{zh ? '故障 / 断纤' : 'Fault'}</option>
                    <option value="idle">{zh ? '空闲' : 'Idle'}</option>
                  </select>
                </label>
                <label className="block">
                  <span className="text-[10px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '光纤模式' : 'Fiber Type'}</span>
                  <select
                    value={portForm.fiber_type}
                    onChange={e => setPortForm(p => ({ ...p, fiber_type: e.target.value }))}
                    className="mt-1 w-full rounded-lg border px-2 py-1.5 text-xs"
                    style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                  >
                    <option value="OS2">OS2 单模</option>
                    <option value="OM4">OM4 多模</option>
                    <option value="OM3">OM3 多模</option>
                  </select>
                </label>
              </div>

              {/* A-End Searchable CMDB Device & Interface Picker */}
              <div className="space-y-1.5 rounded-xl border p-2.5" style={{ borderColor: 'var(--card-border)' }}>
                <div className="text-[10px] font-bold uppercase text-emerald-500">{zh ? 'A 端（本端 CMDB 设备）' : 'A-End (Local Device)'}</div>
                <SearchableDevicePicker
                  valueId={portForm.a_device_id}
                  valueName={portForm.a_device_name}
                  initialDevices={devices}
                  onSearchRemote={searchRemoteDevices}
                  onSelect={dev => {
                    if (dev) {
                      setPortForm(p => ({
                        ...p,
                        a_device_id: dev.id,
                        a_device_name: dev.hostname,
                        a_rack_name: dev.rack_name || '',
                        a_interface_name: '',
                      }));
                    } else {
                      setPortForm(p => ({
                        ...p,
                        a_device_id: '',
                        a_device_name: '',
                        a_rack_name: '',
                        a_interface_name: '',
                      }));
                    }
                  }}
                  placeholder={zh ? '搜索 A 端设备名 / IP / 型号 / 机柜…' : 'Search A-end device, IP, rack…'}
                  zh={zh}
                />
                <input
                  value={portForm.a_device_name}
                  onChange={e => setPortForm(p => ({ ...p, a_device_name: e.target.value }))}
                  placeholder={zh ? 'A 端设备名（可手动覆写）' : 'A-end hostname'}
                  className="w-full rounded-lg border px-2 py-1.5 text-xs"
                  style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                />
                <SearchableInterfacePicker
                  value={portForm.a_interface_name}
                  options={aInterfaces}
                  loading={loadingAInterfaces}
                  onChange={val => setPortForm(p => ({ ...p, a_interface_name: val }))}
                  placeholder={zh ? '搜索或手填 A 端物理接口（如 Ten-GigabitEthernet1/0/49）' : 'Search or type A-end interface…'}
                  zh={zh}
                />
              </div>

              {/* Z-End Peer Picker */}
              <div className="space-y-1.5 rounded-xl border p-2.5" style={{ borderColor: 'var(--card-border)' }}>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-bold uppercase text-amber-500">{zh ? 'Z 端（对端目标）' : 'Z-End (Peer)'}</span>
                  <select
                    value={portForm.z_endpoint_type}
                    onChange={e => setPortForm(p => ({ ...p, z_endpoint_type: e.target.value as any }))}
                    className="rounded border px-1.5 py-0.5 text-[10px]"
                    style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                  >
                    <option value="device">{zh ? '网络设备' : 'Device'}</option>
                    <option value="odf">{zh ? '对端 ODF' : 'Peer ODF'}</option>
                    <option value="carrier">{zh ? '运营商专线' : 'Carrier'}</option>
                    <option value="other">{zh ? '其他' : 'Other'}</option>
                  </select>
                </div>

                {portForm.z_endpoint_type === 'device' ? (
                  <>
                    <SearchableDevicePicker
                      valueId={portForm.z_device_id}
                      valueName={portForm.z_device_name}
                      initialDevices={devices}
                      onSearchRemote={searchRemoteDevices}
                      onSelect={dev => {
                        if (dev) {
                          setPortForm(p => ({
                            ...p,
                            z_device_id: dev.id,
                            z_device_name: dev.hostname,
                            z_interface_name: '',
                          }));
                        } else {
                          setPortForm(p => ({
                            ...p,
                            z_device_id: '',
                            z_device_name: '',
                            z_interface_name: '',
                          }));
                        }
                      }}
                      placeholder={zh ? '搜索 Z 端设备名 / IP / 型号 / 机柜…' : 'Search Z-end device, IP, rack…'}
                      zh={zh}
                    />
                    <input
                      value={portForm.z_device_name}
                      onChange={e => setPortForm(p => ({ ...p, z_device_name: e.target.value }))}
                      placeholder={zh ? 'Z 端设备名（可手动覆写）' : 'Z-end hostname'}
                      className="w-full rounded-lg border px-2 py-1.5 text-xs"
                      style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                    />
                    <SearchableInterfacePicker
                      value={portForm.z_interface_name}
                      options={zInterfaces}
                      loading={loadingZInterfaces}
                      onChange={val => setPortForm(p => ({ ...p, z_interface_name: val }))}
                      placeholder={zh ? '搜索或手填 Z 端物理接口' : 'Search or type Z-end interface…'}
                      zh={zh}
                    />
                  </>
                ) : (
                  <>
                    {portForm.z_endpoint_type === 'odf' && frames.filter(f => f.id !== frameDetail.id).length > 0 && (
                      <select
                        value={portForm.z_odf_frame_id}
                        onChange={e => {
                          const targetOdf = frames.find(f => f.id === e.target.value);
                          setPortForm(p => ({
                            ...p,
                            z_odf_frame_id: e.target.value,
                            z_peer_label: targetOdf ? `${targetOdf.name}${targetOdf.room ? ` (${targetOdf.room})` : ''}` : p.z_peer_label,
                          }));
                        }}
                        className="w-full rounded-lg border px-2 py-1.5 text-xs"
                        style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                      >
                        <option value="">{zh ? '选择 CMDB 对端 ODF（或下方手填）' : 'Select peer ODF frame…'}</option>
                        {frames.filter(f => f.id !== frameDetail.id).map(f => (
                          <option key={f.id} value={f.id}>
                            {f.name} · {f.site_label}{f.room ? ` / ${f.room}` : ''}
                          </option>
                        ))}
                      </select>
                    )}
                    <input
                      value={portForm.z_peer_label}
                      onChange={e => setPortForm(p => ({ ...p, z_peer_label: e.target.value }))}
                      placeholder={zh ? '对端机房 / 运营商局端 / 对端 ODF 名称' : 'Peer room / carrier / ODF name'}
                      className="w-full rounded-lg border px-2 py-1.5 text-xs"
                      style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                    />
                    <input
                      value={portForm.z_odf_port_code}
                      onChange={e => setPortForm(p => ({ ...p, z_odf_port_code: e.target.value }))}
                      placeholder={zh ? '对端端子号（如 ODF-02 A01-01）' : 'Peer port code'}
                      className="w-full rounded-lg border px-2 py-1.5 text-xs font-mono"
                      style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                    />
                  </>
                )}
              </div>

              {/* Cable Metadata */}
              <div className="grid grid-cols-2 gap-2">
                <input
                  value={portForm.cable_tag}
                  onChange={e => setPortForm(p => ({ ...p, cable_tag: e.target.value }))}
                  placeholder={zh ? '光缆/跳纤标签号' : 'Cable tag'}
                  className="rounded-lg border px-2 py-1.5 text-xs font-mono"
                  style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                />
                <input
                  value={portForm.circuit_id}
                  onChange={e => setPortForm(p => ({ ...p, circuit_id: e.target.value }))}
                  placeholder={zh ? '专线/电路编号' : 'Circuit ID'}
                  className="rounded-lg border px-2 py-1.5 text-xs font-mono"
                  style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <input
                  type="number"
                  step="0.01"
                  value={portForm.attenuation_db}
                  onChange={e => setPortForm(p => ({ ...p, attenuation_db: e.target.value }))}
                  placeholder={zh ? '衰耗 (dB)' : 'Loss (dB)'}
                  className="rounded-lg border px-2 py-1.5 text-xs font-mono"
                  style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                />
                <input
                  value={portForm.remarks}
                  onChange={e => setPortForm(p => ({ ...p, remarks: e.target.value }))}
                  placeholder={zh ? '备注' : 'Remarks'}
                  className="rounded-lg border px-2 py-1.5 text-xs"
                  style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                />
              </div>

              {editingPort.port_no % 2 === 1 && editingPort.port_no < (activeTray?.port_count || 48) && (
                <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-cyan-500/30 bg-cyan-500/8 px-2.5 py-2 text-[11px]">
                  <input
                    type="checkbox"
                    checked={portForm.pair_next}
                    onChange={e => setPortForm(p => ({ ...p, pair_next: e.target.checked }))}
                  />
                  <span>
                    {zh
                      ? `同时绑定双工对端（${String(editingPort.port_no).padStart(2, '0')} & ${String(editingPort.port_no + 1).padStart(2, '0')} TX/RX）`
                      : `Bind duplex pair (${editingPort.port_no} & ${editingPort.port_no + 1})`}
                  </span>
                </label>
              )}
            </div>

            <div className="flex items-center justify-between gap-2 border-t p-3" style={{ borderColor: 'var(--card-border)' }}>
              {editingPort.status !== 'idle' ? (
                <button
                  type="button"
                  disabled={savingPort}
                  onClick={() => void handleSavePort(true)}
                  className="flex items-center gap-1 rounded-lg border border-rose-500/40 px-2.5 py-1.5 text-xs text-rose-500 hover:bg-rose-500/10"
                >
                  <Unlink size={12} /> {zh ? '释放端子' : 'Release'}
                </button>
              ) : <span />}
              <button
                type="button"
                disabled={savingPort}
                onClick={() => void handleSavePort(false)}
                className="flex items-center gap-1 rounded-lg bg-cyan-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-cyan-700 disabled:opacity-50"
              >
                <CheckCircle2 size={13} /> {savingPort ? (zh ? '保存中…' : 'Saving…') : (zh ? '保存跳纤' : 'Save Binding')}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Create / Edit ODF Frame Modal */}
      {showFrameModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4">
          <form
            onSubmit={handleSaveFrame}
            className="w-full max-w-lg rounded-2xl border p-5 shadow-2xl space-y-3"
            style={{ background: 'var(--card-bg)', borderColor: 'var(--card-border)' }}
          >
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold" style={{ color: 'var(--heading-text)' }}>
                {editingFrame ? (zh ? '编辑 ODF 配线架' : 'Edit ODF Frame') : (zh ? '新建 ODF 光纤配线架' : 'New ODF Frame')}
              </h3>
              <button type="button" onClick={() => setShowFrameModal(false)}><X size={16} /></button>
            </div>

            {!editingFrame && (
              <div>
                <div className="mb-1 text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>
                  {zh ? '快速容量规格预设' : 'Capacity Preset'}
                </div>
                <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
                  {CAPACITY_PRESETS.map(p => (
                    <button
                      key={p.label}
                      type="button"
                      onClick={() => setFrameForm(f => ({ ...f, tray_count: p.trays, ports_per_tray: p.perTray, model: p.model }))}
                      className={`rounded-lg border px-2 py-1.5 text-[11px] font-medium ${
                        frameForm.tray_count === p.trays && frameForm.ports_per_tray === p.perTray
                          ? 'border-cyan-500 bg-cyan-500/15 text-cyan-500'
                          : 'border-slate-500/30'
                      }`}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="grid grid-cols-2 gap-2.5 text-xs">
              <label className="block">
                <span className="text-[11px]" style={{ color: 'var(--muted-text)' }}>{zh ? '名称 *' : 'Name *'}</span>
                <input
                  required
                  value={frameForm.name}
                  onChange={e => setFrameForm(f => ({ ...f, name: e.target.value }))}
                  className="mt-1 w-full rounded-lg border px-2.5 py-1.5"
                  style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                />
              </label>
              <label className="block">
                <span className="text-[11px]" style={{ color: 'var(--muted-text)' }}>{zh ? '资产编号' : 'Frame Code'}</span>
                <input
                  value={frameForm.frame_code}
                  onChange={e => setFrameForm(f => ({ ...f, frame_code: e.target.value }))}
                  className="mt-1 w-full rounded-lg border px-2.5 py-1.5 font-mono"
                  style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                />
              </label>
              <label className="block">
                <span className="text-[11px]" style={{ color: 'var(--muted-text)' }}>{zh ? '所属站点' : 'Site'}</span>
                <select
                  value={frameForm.site_id}
                  onChange={e => setFrameForm(f => ({ ...f, site_id: e.target.value }))}
                  className="mt-1 w-full rounded-lg border px-2.5 py-1.5"
                  style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                >
                  {sites.map(s => (
                    <option key={s.id} value={s.id}>{s.site_name || s.site_code}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-[11px]" style={{ color: 'var(--muted-text)' }}>{zh ? '厂商' : 'Vendor'}</span>
                <input
                  value={frameForm.vendor}
                  onChange={e => setFrameForm(f => ({ ...f, vendor: e.target.value }))}
                  className="mt-1 w-full rounded-lg border px-2.5 py-1.5"
                  style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                />
              </label>
              <label className="block">
                <span className="text-[11px]" style={{ color: 'var(--muted-text)' }}>{zh ? '型号' : 'Model'}</span>
                <input
                  value={frameForm.model}
                  onChange={e => setFrameForm(f => ({ ...f, model: e.target.value }))}
                  className="mt-1 w-full rounded-lg border px-2.5 py-1.5"
                  style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                />
              </label>
              <label className="block">
                <span className="text-[11px]" style={{ color: 'var(--muted-text)' }}>{zh ? '接口类型' : 'Connector'}</span>
                <select
                  value={frameForm.connector_type}
                  onChange={e => setFrameForm(f => ({ ...f, connector_type: e.target.value }))}
                  className="mt-1 w-full rounded-lg border px-2.5 py-1.5"
                  style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                >
                  {['LC/UPC', 'LC/APC', 'SC/UPC', 'SC/APC', 'MPO-12', 'MPO-24'].map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-[11px]" style={{ color: 'var(--muted-text)' }}>{zh ? '光纤模式' : 'Fiber Mode'}</span>
                <select
                  value={frameForm.fiber_mode}
                  onChange={e => setFrameForm(f => ({ ...f, fiber_mode: e.target.value }))}
                  className="mt-1 w-full rounded-lg border px-2.5 py-1.5"
                  style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                >
                  <option value="mixed">{zh ? '混合（下 2/3 OS2 单模 + 上 1/3 OM4 多模）' : 'Mixed (OS2 + OM4)'}</option>
                  <option value="OS2">OS2 单模</option>
                  <option value="OM4">OM4 多模</option>
                  <option value="OM3">OM3 多模</option>
                </select>
              </label>
              <label className="block">
                <span className="text-[11px]" style={{ color: 'var(--muted-text)' }}>{zh ? '机房 / 区域' : 'Room'}</span>
                <input
                  value={frameForm.room}
                  onChange={e => setFrameForm(f => ({ ...f, room: e.target.value }))}
                  className="mt-1 w-full rounded-lg border px-2.5 py-1.5"
                  style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                />
              </label>
              <label className="block">
                <span className="text-[11px]" style={{ color: 'var(--muted-text)' }}>{zh ? '楼层' : 'Floor'}</span>
                <input
                  value={frameForm.floor}
                  onChange={e => setFrameForm(f => ({ ...f, floor: e.target.value }))}
                  placeholder="1F"
                  className="mt-1 w-full rounded-lg border px-2.5 py-1.5"
                  style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                />
              </label>
              <label className="block">
                <span className="text-[11px]" style={{ color: 'var(--muted-text)' }}>{zh ? '列号' : 'Row'}</span>
                <input
                  value={frameForm.row}
                  onChange={e => setFrameForm(f => ({ ...f, row: e.target.value }))}
                  placeholder="ODF-A"
                  className="mt-1 w-full rounded-lg border px-2.5 py-1.5"
                  style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                />
              </label>
            </div>
            <label className="block text-xs">
              <span className="text-[11px]" style={{ color: 'var(--muted-text)' }}>{zh ? '备注' : 'Remarks'}</span>
              <input
                value={frameForm.remarks}
                onChange={e => setFrameForm(f => ({ ...f, remarks: e.target.value }))}
                placeholder={zh ? '补充机位说明、光缆路由等备注' : 'Optional remarks…'}
                className="mt-1 w-full rounded-lg border px-2.5 py-1.5"
                style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
              />
            </label>

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowFrameModal(false)}
                className="rounded-lg border px-3 py-1.5 text-xs"
                style={{ borderColor: 'var(--card-border)', color: 'var(--muted-text)' }}
              >
                {zh ? '取消' : 'Cancel'}
              </button>
              <button
                type="submit"
                disabled={savingFrame}
                className="rounded-lg bg-cyan-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-cyan-700 disabled:opacity-50"
              >
                {savingFrame ? (zh ? '提交中…' : 'Saving…') : (zh ? '保存' : 'Save')}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Edit Tray Modal */}
      {editingTray && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4">
          <div
            className="w-full max-w-sm rounded-2xl border p-4 shadow-2xl space-y-3 text-xs"
            style={{ background: 'var(--card-bg)', borderColor: 'var(--card-border)' }}
          >
            <div className="flex items-center justify-between">
              <h4 className="font-bold" style={{ color: 'var(--heading-text)' }}>
                {zh ? `编辑熔配盘 ${editingTray.tray_code}` : `Edit Tray ${editingTray.tray_code}`}
              </h4>
              <button type="button" onClick={() => setEditingTray(null)}><X size={15} /></button>
            </div>
            <label className="block">
              <span className="text-[11px]" style={{ color: 'var(--muted-text)' }}>{zh ? '盘位用途标签' : 'Tray Label'}</span>
              <input
                value={trayForm.label}
                onChange={e => setTrayForm(t => ({ ...t, label: e.target.value }))}
                className="mt-1 w-full rounded-lg border px-2.5 py-1.5"
                style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
              />
            </label>
            <div className="grid grid-cols-2 gap-2">
              <label className="block">
                <span className="text-[11px]" style={{ color: 'var(--muted-text)' }}>{zh ? '光纤类型' : 'Fiber Mode'}</span>
                <select
                  value={trayForm.fiber_mode}
                  onChange={e => setTrayForm(t => ({ ...t, fiber_mode: e.target.value }))}
                  className="mt-1 w-full rounded-lg border px-2 py-1.5"
                  style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                >
                  <option value="OS2">OS2</option>
                  <option value="OM4">OM4</option>
                  <option value="OM3">OM3</option>
                </select>
              </label>
              <label className="block">
                <span className="text-[11px]" style={{ color: 'var(--muted-text)' }}>{zh ? '接口类型' : 'Connector'}</span>
                <select
                  value={trayForm.connector_type}
                  onChange={e => setTrayForm(t => ({ ...t, connector_type: e.target.value }))}
                  className="mt-1 w-full rounded-lg border px-2 py-1.5"
                  style={{ background: 'var(--input-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                >
                  {['LC/UPC', 'LC/APC', 'SC/UPC', 'SC/APC', 'MPO-12'].map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </label>
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setEditingTray(null)}
                className="rounded-lg border px-3 py-1"
                style={{ borderColor: 'var(--card-border)', color: 'var(--muted-text)' }}
              >
                {zh ? '取消' : 'Cancel'}
              </button>
              <button
                type="button"
                onClick={() => void handleSaveTray()}
                className="rounded-lg bg-cyan-600 px-3 py-1 font-semibold text-white hover:bg-cyan-700"
              >
                {zh ? '保存' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default OdfManagementTab;
