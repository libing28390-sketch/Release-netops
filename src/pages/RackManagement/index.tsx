import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Columns3,
  Box,
  LayoutGrid,
  Server,
  Layers,
  Eye,
  Zap,
  Package,
  Plus,
  RefreshCw,
  Search,
  X,
  Pencil,
  Trash2,
  Download,
  PanelRightOpen,
  PanelRightClose,
  ChevronsUpDown,
  AlertTriangle,
  Maximize2,
  FileText,
  Upload
} from 'lucide-react';
import * as XLSX from 'xlsx';
import { AssetReadonlyDetailInner, normalizeAssetApiRow } from '../../components/AssetReadonlyDetail';
import PageHero from '../../components/PageHero';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../../components/ui/ActionIconButton';
import { Rack, RackType, DeviceType, RackDevice, RackLayout, RackStats, Props } from './types';
import { ROLE_COLORS, U_PX, RACK_W, LABEL_W, API, INSTALL_ASSET_PAGE_SIZE, STATUS_LABEL } from './constants';
import {
  getNormalizedRoleColor,
  authHeaders,
  fetchJson,
  postJson,
  putJson,
  deleteJson,
  matchDeviceTypeId,
  pickStartUForAsset,
  hasConflict,
  findFirstFreeStartU
} from './helpers';
import { normalizeRackToVM, HealthMap, HealthInfo } from './adapters/rackViewModel';
const Rack3DContainer = React.lazy(() => import('./Rack3D').then(m => ({ default: m.Rack3DContainer })));
import { DevicePortMatrix } from './components/DevicePortMatrix';
import RackElevation from './components/RackElevation';

import DeviceIcon from './components/DeviceIcon';
import PowerLed from './components/PowerLed';

interface Asset {
  id: string;
  asset_tag: string;
  serial_number: string;
  vendor: string;
  model: string;
  hostname: string;
  status: string;
  u_height?: number;
  planned_start_u?: number | null;
  rack_unit?: string;
}

interface SiteOption {
  id: string;
  site_code: string;
  site_name: string;
}

export const RackManagementTab: React.FC<Props> = ({ language }) => {
  const zh = language === 'zh';

  const [racks, setRacks] = useState<Rack[]>([]);
  const [rackTypes, setRackTypes] = useState<RackType[]>([]);
  const [sites, setSites] = useState<SiteOption[]>([]);
  const [deviceTypes, setDeviceTypes] = useState<DeviceType[]>([]);
  const [stats, setStats] = useState<RackStats | null>(null);
  const [selectedRackId, setSelectedRackId] = useState('');
  const [layout, setLayout] = useState<RackLayout | null>(null);
  const [viewSide, setViewSide] = useState<'front' | 'rear'>('front');
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('2d');
  const [healthMap, setHealthMap] = useState<HealthMap>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const [dcFilter, setDcFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [allLayouts, setAllLayouts] = useState<RackLayout[]>([]);

  /* -- Zoom / Collapse / Sidebar states -- */
  const [rackScale, setRackScale] = useState(1);
  const [collapseEmpty, setCollapseEmpty] = useState(false);
  const [showDeviceList, setShowDeviceList] = useState(true);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);
  const [drawerVisible, setDrawerVisible] = useState(false);
  const [drawerAssetDetail, setDrawerAssetDetail] = useState<ReturnType<typeof normalizeAssetApiRow> | null>(null);
  const [drawerAssetLoading, setDrawerAssetLoading] = useState(false);
  const rackScrollRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const layoutCacheRef = useRef<Map<string, RackLayout>>(new Map());

  const [confirmDeleteRack, setConfirmDeleteRack] = useState<{ rackId: string; rackName: string } | null>(null);
  const [blockedDeleteRack, setBlockedDeleteRack] = useState<{ rackName: string; deviceCount: number } | null>(null);
  const [confirmRemoveDevice, setConfirmRemoveDevice] = useState<{ deviceId: string; deviceName: string } | null>(null);
  const [confirmMoveDevice, setConfirmMoveDevice] = useState<{ deviceId: string; deviceName: string; oldU: number; newU: number; uHeight: number } | null>(null);

  const [showRackModal, setShowRackModal] = useState(false);
  const [editingRack, setEditingRack] = useState<Rack | null>(null);
  const [showDeviceModal, setShowDeviceModal] = useState(false);
  const [showDeviceTypeModal, setShowDeviceTypeModal] = useState(false);

  const [rackForm, setRackForm] = useState({
    name: '',
    site_id: '',
    floor: '',
    room: '',
    row: '',
    rack_type_id: '',
    total_u: 42,
    width_mm: 600,
    depth_mm: 1000,
    max_weight_kg: 0,
    description: '',
    power_capacity_watts: 0,
    allow_front_rear_mount: true,
    placement_strategy: 'bottom_first'
  });
  const [deviceForm, setDeviceForm] = useState({ name: '', device_type_id: '', start_u: 1, position: 'front' as string, status: 'active', serial_number: '', asset_id: '' });
  const [dtForm, setDtForm] = useState({ model: '', vendor: '', u_height: 1, device_role: 'switch', description: '', power_watts: 0 });
  const [formError, setFormError] = useState('');

  // Asset selection for device installation
  const [assets, setAssets] = useState<Asset[]>([]);
  const [assetsLoading, setAssetsLoading] = useState(false);
  const [assetTotal, setAssetTotal] = useState(0);
  const [assetPage, setAssetPage] = useState(1);
  const [assetSearch, setAssetSearch] = useState('');
  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null);

  // Set of installed assets/devices to prevent duplicate installation
  const installedAssetSet = useMemo(() => {
    const ids = new Set<string>();
    const snSet = new Set<string>();
    const nameSet = new Set<string>();

    allLayouts.forEach(ly => {
      ly.devices.forEach(d => {
        if (d.asset_id) ids.add(d.asset_id);
        if (d.serial_number) snSet.add(d.serial_number.trim().toLowerCase());
        if (d.name) nameSet.add(d.name.trim().toLowerCase());
      });
    });

    return { ids, snSet, nameSet };
  }, [allLayouts]);

  // Filter available assets
  const availableAssets = useMemo(() => {
    return assets.filter(a => {
      if (a.id && installedAssetSet.ids.has(a.id)) return false;
      const snNorm = (a.serial_number || '').trim().toLowerCase();
      if (snNorm && snNorm !== '—' && installedAssetSet.snSet.has(snNorm)) return false;
      const nameNorm = (a.hostname || a.asset_tag || '').trim().toLowerCase();
      if (nameNorm && installedAssetSet.nameSet.has(nameNorm)) return false;
      return true;
    });
  }, [assets, installedAssetSet]);

  const siteById = useMemo(() => new Map(sites.map(site => [site.id, site])), [sites]);
  const siteLabel = useCallback((rack?: Pick<Rack, 'site_id' | 'site_code' | 'site_name' | 'datacenter'>) => {
    if (!rack) return '';
    const site = rack.site_id ? siteById.get(rack.site_id) : undefined;
    return site?.site_code || rack.site_code || site?.site_name || rack.site_name || rack.datacenter || rack.site_id || '';
  }, [siteById]);
  const siteOptions = useMemo(
    () => sites.slice().sort((a, b) => (a.site_code || a.site_name).localeCompare(b.site_code || b.site_name)),
    [sites],
  );

  const rackTypeById = useMemo(() => {
    const map = new Map<string, RackType>();
    rackTypes.forEach(rt => map.set(rt.id, rt));
    return map;
  }, [rackTypes]);

  const getRackTypeName = useCallback((rackTypeId?: string) => {
    if (!rackTypeId) return '';
    return rackTypeById.get(rackTypeId)?.name || '';
  }, [rackTypeById]);

  const filteredRacks = useMemo(() => {
    let list = racks;
    if (dcFilter) list = list.filter(r => r.site_id === dcFilter);
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const rackIdsWithMatchingDevices = new Set<string>();
      for (const ly of allLayouts) {
        for (const d of ly.devices) {
          if (
            d.name.toLowerCase().includes(q) ||
            d.model.toLowerCase().includes(q) ||
            d.vendor.toLowerCase().includes(q) ||
            d.device_role.toLowerCase().includes(q) ||
            (d.serial_number && d.serial_number.toLowerCase().includes(q)) ||
            (d.asset_id && d.asset_id.toLowerCase().includes(q))
          ) {
            rackIdsWithMatchingDevices.add(ly.id);
          }
        }
      }
      list = list.filter(r =>
        r.name.toLowerCase().includes(q) ||
        siteLabel(r).toLowerCase().includes(q) ||
        r.datacenter.toLowerCase().includes(q) ||
        (r.floor || '').toLowerCase().includes(q) ||
        (r.rack_code || '').toLowerCase().includes(q) ||
        r.room.toLowerCase().includes(q) ||
        r.row.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q) ||
        rackIdsWithMatchingDevices.has(r.id)
      );
    }
    return list;
  }, [racks, dcFilter, searchQuery, allLayouts, siteLabel]);

  /* -- Data Fetchers -- */

  const loadRacks = useCallback(async () => {
    try {
      layoutCacheRef.current.clear();
      const data = await fetchJson<Rack[]>(`${API}/racks`);
      setRacks(data);
      if (!selectedRackId && data.length > 0) setSelectedRackId(data[0].id);
      const layouts = await Promise.all(
        data.map(r => fetchJson<RackLayout>(`${API}/racks/${r.id}/layout`).catch(() => null))
      );
      const validLayouts = layouts.filter((l): l is RackLayout => l !== null);
      validLayouts.forEach(loadedLayout => layoutCacheRef.current.set(loadedLayout.id, loadedLayout));
      setAllLayouts(validLayouts);
      const initialRackId = selectedRackId || data[0]?.id || '';
      if (initialRackId) setLayout(layoutCacheRef.current.get(initialRackId) || null);
    } catch (e: any) { setError(e.message); }
  }, [selectedRackId]);

  const loadSites = useCallback(async () => {
    try {
      setSites(await fetchJson<SiteOption[]>(`${API}/cmdb/sites`));
    } catch (e: any) {
      setError(e.message);
    }
  }, []);

  const loadDeviceTypes = useCallback(async () => {
    try { setDeviceTypes(await fetchJson<DeviceType[]>(`${API}/device-types`)); } catch {}
  }, []);
  const loadRackTypes = useCallback(async () => {
    try { setRackTypes(await fetchJson<RackType[]>(`${API}/rack-types`)); } catch {}
  }, []);

  const loadStats = useCallback(async () => {
    try { setStats(await fetchJson<RackStats>(`${API}/racks/stats`)); } catch {}
  }, []);

  const loadHealthOverview = useCallback(async () => {
    try {
      const res = await fetchJson<any>(`${API}/device-health/overview`);
      const list = Array.isArray(res) ? res : (res?.items || res?.overview || []);
      const map: HealthMap = {};
      list.forEach((item: any) => {
        const info: HealthInfo = {
          status: item.health_status || item.status,
          cpu_usage: item.cpu_usage,
          memory_usage: item.memory_usage,
          temp: item.temp,
          open_alert_count: item.open_alert_count,
          critical_open_alerts: item.critical_open_alerts,
          warning_open_alerts: item.warning_open_alerts,
          network_device_id: item.id || item.device_id
        };
        if (item.asset_id) map[item.asset_id] = info;
        if (item.id) map[item.id] = info;
        if (item.sn) map[item.sn.toLowerCase()] = info;
        if (item.hostname) map[item.hostname.toLowerCase()] = info;
      });
      setHealthMap(map);
    } catch {
      // Telemetry lookup is optional enhancement
    }
  }, []);

  const rackVM = useMemo(() => {
    if (!layout) return null;
    return normalizeRackToVM(layout, healthMap, siteLabel);
  }, [layout, healthMap, siteLabel]);


  const fetchInstallAssets = useCallback(async (q: string, page: number, append: boolean) => {
    try {
      setAssetsLoading(true);
      const params = new URLSearchParams({
        page_size: String(INSTALL_ASSET_PAGE_SIZE),
        page: String(page),
      });
      const t = q.trim();
      if (t) params.set('q', t);
      const res = await fetch(`${API}/assets?${params.toString()}`, { headers: authHeaders() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      const items = json.items || [];
      const total = typeof json.total === 'number' ? json.total : items.length;
      if (append) {
        setAssets(prev => [...prev, ...items]);
      } else {
        setAssets(items);
      }
      setAssetTotal(total);
      setAssetPage(page);
    } catch (e: any) {
      console.error('Failed to load assets:', e.message);
      if (!append) {
        setAssets([]);
        setAssetTotal(0);
      }
    } finally {
      setAssetsLoading(false);
    }
  }, []);

  const loadLayout = useCallback(async (rackId: string) => {
    if (!rackId) return;
    const cachedLayout = layoutCacheRef.current.get(rackId);
    if (cachedLayout) {
      setLayout(cachedLayout);
      setError('');
      return;
    }
    setLoading(true);
    try {
      const data = await fetchJson<RackLayout>(`${API}/racks/${rackId}/layout`);
      layoutCacheRef.current.set(rackId, data);
      setLayout(data);
      setAllLayouts(prev => {
        const exists = prev.some(l => l.id === rackId);
        if (exists) return prev.map(l => l.id === rackId ? data : l);
        return [...prev, data];
      });
      setError('');
    } catch (e: any) { setError(e.message); setLayout(null); }
    finally { setLoading(false); }

  }, []);

  useEffect(() => { loadRacks(); loadDeviceTypes(); loadRackTypes(); loadStats(); loadSites(); loadHealthOverview(); }, []);
  useEffect(() => { if (selectedRackId) loadLayout(selectedRackId); }, [selectedRackId, loadLayout]);

  useEffect(() => {
    if (racks.length === 0) {
      if (selectedRackId) {
        setSelectedRackId('');
        setLayout(null);
      }
      return;
    }
    if (selectedRackId && !racks.some(r => r.id === selectedRackId)) {
      setSelectedRackId(racks[0].id);
    }
  }, [racks, selectedRackId]);

  useEffect(() => {
    if (!showDeviceModal) return;
    const delay = assetSearch.trim().length === 0 ? 0 : 280;
    const id = window.setTimeout(() => { fetchInstallAssets(assetSearch, 1, false); }, delay);
    return () => clearTimeout(id);
  }, [showDeviceModal, assetSearch, fetchInstallAssets]);

  const installAssetsCanLoadMore = assetTotal > 0 && assets.length < assetTotal;

  const refresh = () => { loadRacks(); loadRackTypes(); loadStats(); loadHealthOverview(); };

  const applyRackTypeToForm = (rackTypeId: string) => {
    const rt = rackTypeById.get(rackTypeId);
    setRackForm(prev => ({
      ...prev,
      rack_type_id: rackTypeId,
      ...(rt ? {
        total_u: rt.total_u || prev.total_u,
        width_mm: rt.width_mm || prev.width_mm,
        depth_mm: rt.depth_mm || prev.depth_mm,
        max_weight_kg: rt.max_weight_kg || prev.max_weight_kg,
        power_capacity_watts: rt.power_capacity_watts || prev.power_capacity_watts,
        allow_front_rear_mount: rt.allow_front_rear_mount === false || rt.allow_front_rear_mount === 0 ? false : true,
      } : {})
    }));
  };

  const handleDeviceSelect = (deviceId: string) => {
    setSelectedDeviceId(deviceId);
    setDrawerVisible(true);
  };

  const handleDrawerClose = () => {
    setDrawerVisible(false);
    setSelectedDeviceId(null);
    setDrawerAssetDetail(null);
    setDrawerAssetLoading(false);
  };

  useEffect(() => {
    if (!drawerVisible || !selectedDeviceId || !layout) {
      setDrawerAssetDetail(null);
      setDrawerAssetLoading(false);
      return;
    }
    const device = layout.devices.find(d => d.id === selectedDeviceId);
    if (!device?.asset_id) {
      setDrawerAssetDetail(null);
      setDrawerAssetLoading(false);
      return;
    }
    let cancelled = false;
    setDrawerAssetLoading(true);
    (async () => {
      try {
        const res = await fetch(`${API}/assets/${device.asset_id}`, { headers: authHeaders() });
        if (!res.ok) throw new Error('asset fetch failed');
        const row = await res.json();
        if (!cancelled) setDrawerAssetDetail(normalizeAssetApiRow(row as Record<string, unknown>));
      } catch {
        if (!cancelled) setDrawerAssetDetail(null);
      } finally {
        if (!cancelled) setDrawerAssetLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [drawerVisible, selectedDeviceId, layout]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && drawerVisible) {
        handleDrawerClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [drawerVisible]);

  const COL_MAP: Record<string, string> = {
    '机柜名称*': 'name',
    '站点': 'site_id',
    '数据中心': 'site_id',
    '楼层': 'floor',
    '机房': 'room',
    '列': 'row',
    '总U位': 'total_u',
    '最大功率(W)': 'power_capacity_watts',
    '最大功率': 'power_capacity_watts',
    '散热区域': 'cooling_zone',
    '备注': 'remarks',
    'Name*': 'name',
    'Name': 'name',
    '机柜名称': 'name',
    '机柜类型': 'rack_type_name',
    '宽度(mm)': 'width_mm',
    '深度(mm)': 'depth_mm',
    '最大承重(kg)': 'max_weight_kg',
    '允许正反面': 'allow_front_rear_mount',
    'Rack Type': 'rack_type_name',
    'Rack Type Name': 'rack_type_name',
    'rack_type': 'rack_type_name',
    'rack_type_name': 'rack_type_name',
    'Site': 'site_id',
    'Datacenter': 'site_id',
    'Floor': 'floor',
    'Room': 'room',
    'Row': 'row',
    'Total U': 'total_u',
    'Width(mm)': 'width_mm',
    'Width MM': 'width_mm',
    'Depth(mm)': 'depth_mm',
    'Depth MM': 'depth_mm',
    'Max Weight(kg)': 'max_weight_kg',
    'Max Weight KG': 'max_weight_kg',
    'Max Power(W)': 'power_capacity_watts',
    'Max Power': 'power_capacity_watts',
    'Allow Front/Rear': 'allow_front_rear_mount',
    'Cooling Zone': 'cooling_zone',
    'Notes': 'remarks',
    'Description': 'remarks',
    'Remarks': 'remarks'
  };

  const handleDownloadTemplate = () => {
    const wb = XLSX.utils.book_new();
    const headers = zh
      ? ['机柜名称*', '站点', '机房', '列', '总U位', '最大功率(W)', '散热区域', '备注']
      : ['Name*', 'Site', 'Floor', 'Room', 'Row', 'Total U', 'Max Power(W)', 'Cooling Zone', 'Notes'];
    const example = zh
      ? ['A-01', '北京第一数据中心', '302机房', 'A列', 42, 6000, '冷通道A区', '测试机柜']
      : ['A-01', 'Beijing DC 1', '3F', 'Room 302', 'Row A', 42, 6000, 'Zone A', 'Test rack'];
    void headers;
    void example;
    const templateHeaders = zh
      ? ['机柜名称*', '机柜类型', '站点', '机房', '列', '总U位', '宽度(mm)', '深度(mm)', '最大承重(kg)', '最大功率(W)', '允许正反面', '散热区域', '备注']
      : ['Name*', 'Rack Type', 'Site', 'Floor', 'Room', 'Row', 'Total U', 'Width(mm)', 'Depth(mm)', 'Max Weight(kg)', 'Max Power(W)', 'Allow Front/Rear', 'Cooling Zone', 'Notes'];
    const templateExample = zh
      ? ['A-01', '48U Network Cabinet', '北京第一数据中心', '302机房', 'A列', 48, 600, 1000, 1200, 12000, '是', '冷通道A区', '核心网络机柜']
      : ['A-01', '48U Network Cabinet', 'Beijing DC 1', '3F', 'Room 302', 'Row A', 48, 600, 1000, 1200, 'yes', 'Zone A', 'Core network rack'];
    
    const ws = XLSX.utils.aoa_to_sheet([templateHeaders, templateExample]);
    ws['!cols'] = templateHeaders.map(() => ({ wch: 15 }));
    XLSX.utils.book_append_sheet(wb, ws, zh ? '机柜模板' : 'Rack Template');
    XLSX.writeFile(wb, zh ? '机柜导入模板.xlsx' : 'rack_import_template.xlsx');
  };

  const handleExport = () => {
    try {
      const rows = filteredRacks.map(r => {
        const ly = allLayouts.find(l => l.id === r.id);
        return {
          [zh ? '机柜类型' : 'Rack Type']: getRackTypeName(r.rack_type_id),
          [zh ? '宽度(mm)' : 'Width(mm)']: r.width_mm || 0,
          [zh ? '深度(mm)' : 'Depth(mm)']: r.depth_mm || 0,
          [zh ? '最大承重(kg)' : 'Max Weight(kg)']: r.max_weight_kg || 0,
          [zh ? '允许正反面' : 'Allow Front/Rear']: r.allow_front_rear_mount === false || r.allow_front_rear_mount === 0 ? (zh ? '否' : 'no') : (zh ? '是' : 'yes'),
          [zh ? '机柜名称' : 'Name']: r.name,
          [zh ? '站点' : 'Site']: siteLabel(r),
          [zh ? '楼层' : 'Floor']: r.floor || '',
          [zh ? '机房' : 'Room']: r.room || '',
          [zh ? '列' : 'Row']: r.row || '',
          [zh ? '总U位' : 'Total U']: r.total_u,
          [zh ? '最大功率(W)' : 'Max Power(W)']: r.power_capacity_watts || (r as any).power_capacity_w || 0,
          [zh ? '已用U位' : 'Used U']: ly?.total_used ?? 0,
          [zh ? '可用U位' : 'Available U']: ly?.available_u ?? r.total_u,
          [zh ? '散热区域' : 'Cooling Zone']: (r as any).cooling_zone || '',
          [zh ? '状态' : 'Status']: r.status || 'active',
          [zh ? '备注' : 'Remarks']: r.remarks || r.description || ''
        };
      });
      const ws = XLSX.utils.json_to_sheet(rows);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, 'Racks');
      const ts = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
      XLSX.writeFile(wb, `racks_${ts}.xlsx`);
    } catch (err: any) {
      setError(zh ? `导出失败: ${err.message}` : `Export failed: ${err.message}`);
    }
  };

  const handleImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async (ev) => {
      try {
        const data = new Uint8Array(ev.target?.result as ArrayBuffer);
        const wb = XLSX.read(data, { type: 'array' });
        const mapped: any[] = [];
        const wsname = wb.SheetNames[0];
        const ws = wb.Sheets[wsname];
        const raw = XLSX.utils.sheet_to_json<Record<string, any>>(ws, { defval: '' });
        
        for (const row of raw) {
          const obj: any = {};
          for (const [col, val] of Object.entries(row)) {
            const key = COL_MAP[col.trim()];
            if (key) {
              let mappedVal: any = String(val).trim();
              if (key === 'total_u') {
                mappedVal = parseInt(mappedVal) || 42;
              } else if (key === 'power_capacity_watts' || key === 'width_mm' || key === 'depth_mm' || key === 'max_weight_kg') {
                mappedVal = parseInt(mappedVal) || 0;
              } else if (key === 'allow_front_rear_mount') {
                mappedVal = !['false', '0', 'no', '否', '不允许'].includes(String(mappedVal).trim().toLowerCase());
              }
              obj[key] = mappedVal;
            }
          }
          if (obj.name) {
            if (obj.rack_type_name) {
              const rackType = rackTypes.find(rt => rt.name.trim().toLowerCase() === String(obj.rack_type_name).trim().toLowerCase());
              if (rackType) {
                obj.rack_type_id = rackType.id;
                if (!obj.total_u) obj.total_u = rackType.total_u;
                if (!obj.width_mm) obj.width_mm = rackType.width_mm || 600;
                if (!obj.depth_mm) obj.depth_mm = rackType.depth_mm || 1000;
                if (!obj.max_weight_kg) obj.max_weight_kg = rackType.max_weight_kg || 0;
                if (!obj.power_capacity_watts) obj.power_capacity_watts = rackType.power_capacity_watts || 0;
                if (obj.allow_front_rear_mount === undefined) {
                  obj.allow_front_rear_mount = rackType.allow_front_rear_mount === false || rackType.allow_front_rear_mount === 0 ? false : true;
                }
              }
              delete obj.rack_type_name;
            }
            if (!obj.total_u) obj.total_u = 42;
            if (!obj.power_capacity_watts) obj.power_capacity_watts = 0;
            if (!obj.width_mm) obj.width_mm = 600;
            if (!obj.depth_mm) obj.depth_mm = 1000;
            mapped.push(obj);
          }
        }

        if (!mapped.length) {
          setError(zh ? '未找到有效的机柜数据' : 'No valid rack data found');
          return;
        }

        const r = await fetch(`${API}/racks/batch`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...authHeaders()
          },
          body: JSON.stringify(mapped)
        });
        
        if (r.ok) {
          refresh();
          alert(zh ? `导入完成：成功导入 ${mapped.length} 个机柜` : `Import done: ${mapped.length} racks successfully imported`);
        } else {
          const errData = await r.json();
          setError(zh ? `导入失败: ${errData.detail || ''}` : `Import failed: ${errData.detail || ''}`);
        }
      } catch (err: any) {
        setError(zh ? `文件解析失败: ${err.message}` : `Failed to parse file: ${err.message}`);
      }
    };
    reader.readAsArrayBuffer(file);
    e.target.value = '';
  };

  /* -- Rack CRUD -- */

  const openNewRack = () => {
    setEditingRack(null);
    setRackForm({
      name: '',
      site_id: siteOptions[0]?.id || '',
      floor: '',
      room: '',
      row: '',
      rack_type_id: '',
      total_u: 42,
      width_mm: 600,
      depth_mm: 1000,
      max_weight_kg: 0,
      description: '',
      power_capacity_watts: 0,
      allow_front_rear_mount: true,
      placement_strategy: 'bottom_first'
    });
    setFormError(''); setShowRackModal(true);
  };
  
  const openEditRack = (rack: Rack) => {
    setEditingRack(rack);
    setRackForm({
      name: rack.name,
      site_id: rack.site_id || '',
      floor: rack.floor || '',
      room: rack.room,
      row: rack.row,
      rack_type_id: rack.rack_type_id || '',
      total_u: rack.total_u,
      width_mm: rack.width_mm || 600,
      depth_mm: rack.depth_mm || 1000,
      max_weight_kg: rack.max_weight_kg || 0,
      description: rack.description,
      power_capacity_watts: (rack as any).power_capacity_watts ?? 0,
      allow_front_rear_mount: rack.allow_front_rear_mount === false || rack.allow_front_rear_mount === 0 ? false : true,
      placement_strategy: rack.placement_strategy || 'bottom_first'
    });
    setFormError(''); setShowRackModal(true);
  };

  const saveRack = async () => {
    setFormError('');
    const payload = {
      ...rackForm,
      total_u: parseInt(String(rackForm.total_u)) || 42,
      power_capacity_watts: parseInt(String(rackForm.power_capacity_watts)) || 0,
      width_mm: parseInt(String(rackForm.width_mm)) || 600,
      depth_mm: parseInt(String(rackForm.depth_mm)) || 1000,
      max_weight_kg: parseInt(String(rackForm.max_weight_kg)) || 0,
      allow_front_rear_mount: !!rackForm.allow_front_rear_mount,
    };
    try {
      if (editingRack) {
        await putJson(`${API}/racks/${editingRack.id}`, payload);
      } else {
        const created = await postJson<Rack>(`${API}/racks`, payload);
        setSelectedRackId(created.id);
      }
      setShowRackModal(false); refresh();
    } catch (e: any) { setFormError(e.message); }
  };

  const handleDeleteRack = async (rackId: string) => {
    setError('');
    try {
      const lay = await fetchJson<RackLayout>(`${API}/racks/${rackId}/layout`);
      if (lay.devices.length > 0) {
        const rack = racks.find(r => r.id === rackId);
        setBlockedDeleteRack({ rackName: rack?.name || '', deviceCount: lay.devices.length });
        return;
      }
      const rack = racks.find(r => r.id === rackId);
      setConfirmDeleteRack({ rackId, rackName: rack?.name || '' });
    } catch (e: any) {
      setError(e.message);
      return;
    }
  };

  const confirmDeleteRackAction = async () => {
    if (!confirmDeleteRack) return;
    const { rackId } = confirmDeleteRack;
    setConfirmDeleteRack(null);
    setError('');
    try {
      await deleteJson(`${API}/racks/${rackId}`);
      if (selectedRackId === rackId) {
        setSelectedRackId('');
        setLayout(null);
      }
      await loadRacks();
      loadStats();
    } catch (e: any) {
      setError(e.message);
    }
  };

  /* -- Device Install -- */

  const closeInstallModal = () => {
    setFormError('');
    setShowDeviceModal(false);
  };

  const openInstallDevice = () => {
    setSelectedAsset(null);
    setAssetSearch('');
    setAssetTotal(0);
    setAssetPage(1);
    setDeviceForm({ name: '', device_type_id: '', start_u: 1, position: 'front', status: 'active', serial_number: '', asset_id: '' });
    setFormError('');
    setShowDeviceModal(true);
  };

  const openInstallDeviceAtU = (uNumber: number) => {
    setSelectedAsset(null);
    setAssetSearch('');
    setAssetTotal(0);
    setAssetPage(1);
    setDeviceForm({
      name: '',
      device_type_id: '',
      start_u: uNumber,
      position: viewSide,
      status: 'active',
      serial_number: '',
      asset_id: ''
    });
    setFormError('');
    setShowDeviceModal(true);
  };

  const resolveStartUForInstall = (deviceTypeId: string, position: string): number => {
    const uH = deviceTypes.find(dt => dt.id === deviceTypeId)?.u_height ?? 1;
    if (!layout || !selectedRackId) return 1;
    if (selectedAsset) {
      return pickStartUForAsset(layout, position, uH, selectedAsset);
    }
    const sideDevices = layout.devices.filter(d => d.position === position);
    return findFirstFreeStartU(layout.total_u, uH, sideDevices, layout.placement_strategy) ?? 1;
  };

  const handleAssetSelect = (asset: Asset) => {
    setSelectedAsset(asset);
    const matchedId = matchDeviceTypeId(asset, deviceTypes);
    const position = 'front';
    const uH = matchedId
      ? (deviceTypes.find(dt => dt.id === matchedId)?.u_height ?? 1)
      : Math.max(1, asset.u_height ?? 1);
    const startU =
      layout && selectedRackId ? pickStartUForAsset(layout, position, uH, asset) : 1;
    setDeviceForm({
      name: asset.hostname || asset.asset_tag || '',
      device_type_id: matchedId,
      start_u: startU,
      position,
      status: asset.status === 'in_storage' ? 'offline' : asset.status === 'active' ? 'active' : 'planned',
      serial_number: asset.serial_number || '',
      asset_id: asset.id || '',
    });
  };

  const saveDevice = async () => {
    setFormError('');
    if (!deviceForm.name.trim()) {
      setFormError(zh ? '设备名称不能为空' : 'Device name is required');
      return;
    }
    if (!deviceForm.device_type_id) {
      setFormError(zh ? '请选择设备型号' : 'Please select a device type');
      return;
    }
    if (!selectedRackId) {
      setFormError(zh ? '请先选择机柜' : 'Please select a rack first');
      return;
    }
    const dt = deviceTypes.find(x => x.id === deviceForm.device_type_id);
    const uH = dt?.u_height ?? 1;
    if (layout) {
      const sideDevices = layout.devices.filter(d => d.position === deviceForm.position);
      if (hasConflict(deviceForm.start_u, uH, layout.total_u, sideDevices)) {
        const sugg = findFirstFreeStartU(layout.total_u, uH, sideDevices, layout.placement_strategy);
        setFormError(
          zh
            ? `当前${deviceForm.position === 'front' ? '前' : '后'}面板 U${deviceForm.start_u} 已被占用或与现有设备重叠。${sugg != null ? `可尝试起始 U${sugg}。` : '无足够连续空位。'}`
            : `${deviceForm.position} side: U${deviceForm.start_u} overlaps existing gear.${sugg != null ? ` Try start U${sugg}.` : ' No contiguous space.'}`,
        );
        return;
      }
    }
    try {
      await postJson(`${API}/rack-devices`, {
        name: deviceForm.name,
        rack_id: selectedRackId,
        device_type_id: deviceForm.device_type_id,
        start_u: deviceForm.start_u,
        position: deviceForm.position,
        status: deviceForm.status,
        serial_number: deviceForm.serial_number || '',
        asset_id: deviceForm.asset_id || '',
      });
      closeInstallModal(); loadLayout(selectedRackId); loadStats();
    } catch (e: any) { setFormError(e.message); }
  };

  const handleRemoveDevice = async (deviceId: string, deviceName: string) => {
    setConfirmRemoveDevice({ deviceId, deviceName });
  };

  const confirmRemoveDeviceAction = async () => {
    if (!confirmRemoveDevice) return;
    const { deviceId } = confirmRemoveDevice;
    setConfirmRemoveDevice(null);
    setError('');
    try {
      await deleteJson(`${API}/rack-devices/${deviceId}`);
      if (selectedDeviceId === deviceId) {
        setSelectedDeviceId(null);
        setDrawerVisible(false);
        setDrawerAssetDetail(null);
        setDrawerAssetLoading(false);
      }
      loadLayout(selectedRackId);
      loadStats();
    } catch (e: any) {
      setError(e.message);
    }
  };

  /* -- Device Type -- */

  const openNewDeviceType = () => {
    setDtForm({ model: '', vendor: '', u_height: 1, device_role: 'switch', description: '', power_watts: 0 });
    setFormError(''); setShowDeviceTypeModal(true);
  };

  const saveDeviceType = async () => {
    setFormError('');
    try { await postJson(`${API}/device-types`, dtForm); setShowDeviceTypeModal(false); loadDeviceTypes(); }
    catch (e: any) { setFormError(e.message); }
  };

  /* -- Drag-to-move -- */

  const handleDeviceMove = useCallback(async (deviceId: string, newStartU: number) => {
    // Find the device info from layout to show in confirmation
    const dev = layout?.devices.find(d => d.id === deviceId);
    if (!dev) return;
    if (dev.start_u === newStartU) return; // no change
    setConfirmMoveDevice({
      deviceId,
      deviceName: dev.name || deviceId,
      oldU: dev.start_u,
      newU: newStartU,
      uHeight: dev.u_height || 1,
    });
  }, [layout]);

  const confirmMoveDeviceAction = useCallback(async () => {
    if (!confirmMoveDevice) return;
    const { deviceId, newU } = confirmMoveDevice;
    try {
      await putJson(`${API}/rack-devices/${deviceId}`, { start_u: newU });
      loadLayout(selectedRackId);
    } catch (e: any) {
      setError(e.message);
      loadLayout(selectedRackId);
    }
    setConfirmMoveDevice(null);
  }, [confirmMoveDevice, selectedRackId, loadLayout]);

  /* -- Fit-to-screen zoom -- */
  const handleFitToScreen = useCallback(() => {
    if (!rackScrollRef.current || !layout) return;
    const containerH = rackScrollRef.current.clientHeight - 40;
    const rackH = layout.total_u * U_PX + 8;
    if (rackH <= 0) return;
    const fit = Math.min(1, containerH / rackH);
    setRackScale(Math.max(0.3, Math.round(fit * 100) / 100));
  }, [layout]);

  const handleResetZoom = useCallback(() => setRackScale(1), []);

  /* -- Download PNG -- */

  const handleDownloadRack = useCallback(() => {
    if (!layout) return;
    const totalU = layout.total_u;
    const side = viewSide;
    const devices = layout.devices.filter(d => d.position === side);

    const scale = 4;
    const uH = 32; 
    const lw = 44; 
    const rw = 520; 
    const totalW = lw + rw + lw;
    const headerH = 64;
    const footerH = 80;
    const totalH = headerH + totalU * uH + footerH;

    const canvas = document.createElement('canvas');
    canvas.width = totalW * scale;
    canvas.height = totalH * scale;
    const ctx = canvas.getContext('2d')!;
    ctx.scale(scale, scale);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';

    const bgGrad = ctx.createLinearGradient(0, 0, 0, totalH);
    bgGrad.addColorStop(0, '#0f172a');
    bgGrad.addColorStop(1, '#020617');
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, totalW, totalH);

    ctx.textBaseline = 'middle';
    ctx.textAlign = 'center';
    ctx.fillStyle = '#f8fafc';
    ctx.font = 'bold 20px system-ui, sans-serif';
    ctx.fillText(`${layout.name} - ${side === 'front' ? (zh ? '前视图' : 'Front') : (zh ? '后视图' : 'Rear')}`, totalW / 2, 24);
    
    ctx.fillStyle = '#94a3b8';
    ctx.font = '12px system-ui, sans-serif';
    ctx.fillText(`${layout.datacenter}${layout.room ? ' / ' + layout.room : ''} | ${layout.total_used}U / ${totalU}U`, totalW / 2, 44);

    ctx.fillStyle = '#1e293b';
    ctx.fillRect(lw - 6, headerH - 6, rw + 12, totalU * uH + 12);
    
    ctx.fillStyle = '#020617';
    ctx.fillRect(lw, headerH, rw, totalU * uH);
    
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(lw, headerH, 18, totalU * uH);
    ctx.fillRect(lw + rw - 18, headerH, 18, totalU * uH);

    const devMap = new Map<number, (typeof devices)[0]>();
    const spanned = new Set<number>();
    for (const d of devices) {
      devMap.set(d.start_u, d);
      for (let u = d.start_u + 1; u < d.start_u + d.u_height; u++) spanned.add(u);
    }

    for (let i = 0; i < totalU; i++) {
      const uNumber = totalU - i;
      const y = headerH + i * uH;
      
      ctx.strokeStyle = '#1e293b';
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(lw, y);
      ctx.lineTo(lw + rw, y);
      ctx.stroke();

      ctx.fillStyle = '#334155';
      [lw + 9, lw + rw - 9].forEach(hx => {
        [y + uH*0.25, y + uH*0.75].forEach(hy => {
          ctx.beginPath();
          ctx.arc(hx, hy, 1.2, 0, Math.PI * 2);
          ctx.fill();
        });
      });

      ctx.textAlign = 'center';
      ctx.font = 'bold 10px monospace';
      ctx.fillStyle = '#475569';
      ctx.fillText(String(uNumber), lw / 2, y + uH / 2);
      ctx.fillText(String(uNumber), lw + rw + lw / 2, y + uH / 2);

      const device = devMap.get(uNumber);
      if (device) {
        const h = device.u_height * uH;
        const rc = getNormalizedRoleColor(device.device_role, device.name, device.model);
        
        const devGrad = ctx.createLinearGradient(lw + 2, y + 1, lw + 2, y + h - 1);
        devGrad.addColorStop(0, rc.bg);
        devGrad.addColorStop(1, rc.border);
        ctx.fillStyle = devGrad;
        
        ctx.beginPath();
        ctx.roundRect(lw + 2, y + 1, rw - 4, h - 2, 2);
        ctx.fill();
        
        ctx.strokeStyle = 'rgba(255,255,255,0.15)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(lw + 4, y + 2);
        ctx.lineTo(lw + rw - 4, y + 2);
        ctx.stroke();

        const ledX = lw + 32;
        const ledY = y + h / 2;
        const ledColor = device.status === 'active' ? '#4ade80' : device.status === 'planned' ? '#fbbf24' : '#ef4444';
        
        ctx.shadowBlur = device.status === 'active' ? 8 : 0;
        ctx.shadowColor = ledColor;
        ctx.beginPath();
        ctx.arc(ledX, ledY, 4, 0, Math.PI * 2);
        ctx.fillStyle = ledColor;
        ctx.fill();
        ctx.shadowBlur = 0;

        ctx.fillStyle = '#ffffff';
        ctx.textAlign = 'left';
        
        ctx.font = 'bold 13px system-ui, sans-serif';
        ctx.fillText(device.name, lw + 48, y + h / 2);
        const nameW = ctx.measureText(device.name).width;

        ctx.font = '11px system-ui, sans-serif';
        ctx.globalAlpha = 0.7;
        const modelStr = `${device.vendor} ${device.model}`;
        ctx.fillText(modelStr, lw + 48 + nameW + 24, y + h / 2);
        const modelW = ctx.measureText(modelStr).width;

        const sn = device.serial_number || device.asset_id;
        if (sn && (lw + 48 + nameW + 24 + modelW + 40 < lw + rw - 60)) {
          ctx.font = 'italic 10px monospace';
          ctx.globalAlpha = 0.5;
          ctx.fillText(`[${sn}]`, lw + 48 + nameW + 24 + modelW + 16, y + h / 2);
        }

        ctx.globalAlpha = 1;
        ctx.textAlign = 'right';
        ctx.font = 'bold 10px monospace';
        ctx.fillStyle = 'rgba(255,255,255,0.6)';
        ctx.fillText(`${device.u_height}U`, lw + rw - 24, y + h / 2);
      } else {
        ctx.strokeStyle = '#0f172a';
        ctx.lineWidth = 1;
        ctx.setLineDash([2, 4]);
        ctx.strokeRect(lw + 20, y + 4, rw - 40, uH - 8);
        ctx.setLineDash([]);
      }
    }

    const legendY = headerH + totalU * uH + 28;
    ctx.textAlign = 'left';
    ctx.globalAlpha = 1;
    let lx = 20;
    
    ctx.font = 'bold 10px system-ui, sans-serif';
    ctx.fillStyle = '#64748b';
    ctx.fillText(zh ? '状态:' : 'Status:', lx, legendY);
    lx += 40;

    [
      [zh ? '通电' : 'ON', '#4ade80'],
      [zh ? '断电' : 'OFF', '#ef4444'],
      [zh ? '规划' : 'Plan', '#fbbf24'],
    ].forEach(([label, color]) => {
      ctx.beginPath();
      ctx.arc(lx + 4, legendY, 3.5, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.fillStyle = '#94a3b8';
      ctx.font = '10px system-ui, sans-serif';
      ctx.fillText(label, lx + 12, legendY);
      lx += ctx.measureText(label).width + 32;
    });

    lx += 20;
    ctx.fillStyle = '#64748b';
    ctx.font = 'bold 10px system-ui, sans-serif';
    ctx.fillText(zh ? '角色:' : 'Role:', lx, legendY);
    lx += 40;

    const visibleRoles = Object.entries(ROLE_COLORS).slice(0, 7);
    visibleRoles.forEach(([, rc]) => {
      ctx.fillStyle = rc.bg;
      ctx.beginPath();
      ctx.roundRect(lx, legendY - 5, 10, 10, 2);
      ctx.fill();
      ctx.fillStyle = '#94a3b8';
      ctx.font = '10px system-ui, sans-serif';
      const rLabel = zh ? rc.labelZh : rc.label;
      ctx.fillText(rLabel, lx + 14, legendY);
      lx += ctx.measureText(rLabel).width + 28;
    });

    const nowStr = new Date().toLocaleString(zh ? 'zh-CN' : 'en-US');
    ctx.textAlign = 'right';
    ctx.font = '9px system-ui, sans-serif';
    ctx.fillStyle = '#475569';
    ctx.fillText(`${zh ? '生成于' : 'Generated at'}: ${nowStr}`, totalW - 20, totalH - 16);

    const link = document.createElement('a');
    link.download = `rack-${layout.name}-${side}-${new Date().toISOString().slice(0, 10)}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
  }, [layout, viewSide, zh]);

  const selectedRack = racks.find(r => r.id === selectedRackId);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <input ref={fileInputRef} type="file" accept=".xlsx,.xls,.csv" className="hidden" onChange={handleImport} />
      <PageHero
        icon={Columns3}
        title={zh ? '机柜管理' : 'Rack Management'}
        subtitle={zh ? '拖拽设备调整U位 · 可视化机柜布局' : 'Drag devices to reposition · Visual rack layout'}
        actions={
          <>
            {stats && (
              <div className="hidden lg:flex items-center gap-2 mr-2">
                {[
                  { label: zh ? '机柜' : 'Racks', value: stats.total_racks, color: '#06b6d4', icon: <LayoutGrid size={14} /> },
                  { label: zh ? '设备' : 'Devices', value: stats.total_devices, color: '#6366f1', icon: <Server size={14} /> },
                  { label: zh ? 'U位' : 'U', value: `${stats.used_u}/${stats.total_u}`, color: '#10b981', icon: <Layers size={14} /> },
                  { label: zh ? '利用率' : 'Util', value: `${stats.utilization}%`, color: stats.utilization > 80 ? '#ef4444' : stats.utilization > 60 ? '#f59e0b' : '#10b981', icon: <Eye size={14} /> },
                  ...(stats.total_power_used_watts != null ? [{
                    label: zh ? '总功率' : 'Power',
                    value: stats.total_power_capacity_watts
                      ? `${stats.total_power_used_watts}/${stats.total_power_capacity_watts}W`
                      : `${stats.total_power_used_watts}W (${zh ? '未设上限' : 'No cap'})`,
                    color: stats.total_power_capacity_watts && (stats.power_utilization_pct ?? 0) > 80 ? '#ef4444' : stats.total_power_capacity_watts && (stats.power_utilization_pct ?? 0) > 60 ? '#f59e0b' : '#10b981',
                    icon: <Zap size={14} />,
                  }] : []),
                ].map((s, i) => (
                  <div key={i} className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5" style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }}>
                    <span style={{ color: s.color }}>{s.icon}</span>
                    <span className="text-[11px] font-bold" style={{ color: s.color }}>{s.value}</span>
                    <span className="text-[10px]" style={{ color: 'var(--muted-text)' }}>{s.label}</span>
                  </div>
                ))}
              </div>
            )}
            <button onClick={openNewDeviceType} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors" style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)', color: 'var(--body-text)' }}>
              <Package size={14} /> {zh ? '设备型号' : 'Device Types'}
            </button>
            <button onClick={openNewRack} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white bg-cyan-600 hover:bg-cyan-700 transition-colors">
              <Plus size={14} /> {zh ? '新建机柜' : 'New Rack'}
            </button>
            <ActionIconGroup label={zh ? '机柜工具' : 'Rack tools'}>
              <ActionIconButton icon={FileText} label={zh ? '下载导入模板' : 'Download import template'} variant="accent" onClick={handleDownloadTemplate} />
              <ActionIconButton icon={Upload} label={zh ? '导入机柜' : 'Import racks'} variant="accent" onClick={() => fileInputRef.current?.click()} />
              <ActionIconButton icon={Download} label={zh ? '导出机柜' : 'Export racks'} variant="accent" onClick={handleExport} />
              <ActionIconButton icon={RefreshCw} label={zh ? '刷新' : 'Refresh'} onClick={refresh} />
            </ActionIconGroup>
          </>
        }
      />

      <div className="flex-1 flex flex-col gap-3 overflow-hidden px-6 py-5">

      {/* -- Stats cards (small screens) -- */}
      {stats && (
        <div className="flex-shrink-0 grid grid-cols-2 sm:grid-cols-4 gap-2 lg:hidden">
          {[
            { label: zh ? '机柜总数' : 'Racks', value: stats.total_racks, color: '#06b6d4', icon: <LayoutGrid size={16} /> },
            { label: zh ? '已安装设备' : 'Devices', value: stats.total_devices, color: '#6366f1', icon: <Server size={16} /> },
            { label: zh ? '总U位' : 'Total U', value: `${stats.used_u} / ${stats.total_u}`, color: '#10b981', icon: <Layers size={16} /> },
            { label: zh ? '利用率' : 'Utilization', value: `${stats.utilization}%`, color: stats.utilization > 80 ? '#ef4444' : stats.utilization > 60 ? '#f59e0b' : '#10b981', icon: <Eye size={16} /> },
            ...(stats.total_power_used_watts != null ? [{
              label: zh ? '机柜功率' : 'Power',
              value: stats.total_power_capacity_watts
                ? `${stats.total_power_used_watts} / ${stats.total_power_capacity_watts} W`
                : `${stats.total_power_used_watts} W (${zh ? '未设上限' : 'No cap'})`,
              color: stats.total_power_capacity_watts && (stats.power_utilization_pct ?? 0) > 80 ? '#ef4444' : stats.total_power_capacity_watts && (stats.power_utilization_pct ?? 0) > 60 ? '#f59e0b' : '#10b981',
              icon: <Zap size={16} />,
            }] : []),
          ].map((s, i) => (
            <div key={i} className="rounded-lg px-3 py-2" style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }}>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-[10px] font-medium" style={{ color: 'var(--muted-text)' }}>{s.label}</p>
                  <p className="text-lg font-bold" style={{ color: s.color }}>{s.value}</p>
                </div>
                <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: s.color + '15', color: s.color }}>{s.icon}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* -- Main: Rack List + Elevation -- */}
      <div className="flex gap-3 flex-1 min-h-0">
        {/* Left: rack list */}
        <div className="w-56 flex-shrink-0 rounded-xl overflow-hidden flex flex-col" style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }}>
          <div className="p-3 space-y-2 border-b" style={{ borderColor: 'var(--card-border)' }}>
            <div className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5" style={{ background: 'var(--app-hover-bg)' }}>
              <Search size={14} style={{ color: 'var(--muted-text)' }} />
              <input value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder={zh ? '搜索机柜/设备...' : 'Search rack/device...'} className="flex-1 bg-transparent text-xs outline-none" style={{ color: 'var(--body-text)' }} />
              {searchQuery && <button onClick={() => setSearchQuery('')}><X size={12} style={{ color: 'var(--muted-text)' }} /></button>}
            </div>
            {siteOptions.length > 1 && (
              <select value={dcFilter} onChange={e => setDcFilter(e.target.value)} className="w-full text-[11px] rounded-lg px-2 py-1.5 outline-none" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}>
                <option value="">{zh ? '全部站点' : 'All Sites'}</option>
                {siteOptions.map(site => <option key={site.id} value={site.id}>{site.site_code} · {site.site_name}</option>)}
              </select>
            )}
          </div>
          <div className="flex-1 overflow-auto p-1.5 space-y-0.5">
            {filteredRacks.length === 0 ? (
              <p className="text-center text-xs py-8" style={{ color: 'var(--muted-text)' }}>{zh ? '暂无机柜' : 'No racks'}</p>
            ) : filteredRacks.map(rack => {
              const ly = allLayouts.find(l => l.id === rack.id);
              const pUsed = (ly as any)?.power_used_watts ?? 0;
              const pCap = (ly as any)?.power_capacity_watts ?? 0;
              const pPct = (ly as any)?.power_utilization_pct ?? 0;
              return (
                <button
                  key={rack.id}
                  onClick={() => setSelectedRackId(rack.id)}
                  className={`w-full text-left rounded-lg px-3 py-2 transition-all group ${rack.id === selectedRackId ? 'ring-1 ring-cyan-500/50' : ''}`}
                  style={{ background: rack.id === selectedRackId ? 'var(--app-hover-bg)' : 'transparent', color: 'var(--body-text)' }}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-[13px] font-semibold truncate">{rack.name}</span>
                    <ActionIconGroup className="opacity-0 group-hover:opacity-100 transition-opacity">
                      <ActionIconButton icon={Pencil} label={zh ? `编辑${rack.name}` : `Edit ${rack.name}`} size="xs" onClick={(e) => { e.stopPropagation(); openEditRack(rack); }} />
                      <ActionIconButton icon={Trash2} label={zh ? `删除${rack.name}` : `Delete ${rack.name}`} size="xs" variant="danger" onClick={(e) => { e.stopPropagation(); handleDeleteRack(rack.id); }} />
                    </ActionIconGroup>
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    {siteLabel(rack) && <span className="text-[10px] px-1.5 py-0.5 rounded-full" style={{ background: '#06b6d415', color: '#06b6d4' }}>{siteLabel(rack)}</span>}
                    {rack.floor && <span className="text-[10px] px-1.5 py-0.5 rounded-full" style={{ background: '#8b5cf615', color: '#7c3aed' }}>{rack.floor}</span>}
                    {rack.rack_type_id && <span className="text-[10px] truncate max-w-[120px]" style={{ color: 'var(--muted-text)' }}>{getRackTypeName(rack.rack_type_id)}</span>}
                    <span className="text-[10px]" style={{ color: 'var(--muted-text)' }}>{rack.total_u}U</span>
                    {(rack.width_mm || rack.depth_mm) && <span className="text-[10px]" style={{ color: 'var(--muted-text)' }}>{rack.width_mm || '-'}×{rack.depth_mm || '-'}mm</span>}
                  </div>
                  {searchQuery && (() => {
                    const q = searchQuery.toLowerCase();
                    const matches = ly?.devices.filter(d =>
                      d.name.toLowerCase().includes(q) ||
                      d.model.toLowerCase().includes(q) ||
                      d.vendor.toLowerCase().includes(q) ||
                      (d.serial_number && d.serial_number.toLowerCase().includes(q))
                    ) || [];
                    return matches.length > 0 ? (
                      <div className="mt-1 space-y-0.5">
                        {matches.slice(0, 3).map(m => (
                          <div key={m.id} className="text-[9px] truncate flex items-center gap-1" style={{ color: '#06b6d4' }}>
                            <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: getNormalizedRoleColor(m.device_role, m.name, m.model).bg }} />
                            {m.name} <span style={{ color: 'var(--muted-text)' }}>U{m.start_u}</span>
                          </div>
                        ))}
                        {matches.length > 3 && <span className="text-[9px]" style={{ color: 'var(--muted-text)' }}>+{matches.length - 3} {zh ? '更多' : 'more'}</span>}
                      </div>
                    ) : null;
                  })()}
                  {ly && (
                    <div className="mt-1.5 pt-1.5 border-t border-black/5 dark:border-white/5 space-y-1">
                      <div className="flex items-center justify-between text-[10px]">
                        <span className="text-slate-500 flex items-center gap-1 font-medium">
                          <Zap size={10} className="text-amber-500" />
                          {zh ? '功率' : 'Power'}
                        </span>
                        <span className="font-mono font-semibold" style={{ color: pCap > 0 && pPct > 80 ? '#ef4444' : pCap > 0 && pPct > 60 ? '#f59e0b' : '#10b981' }}>
                          {pCap > 0 ? `${pUsed} / ${pCap} W ( ${pPct}%)` : `${pUsed} W`}
                        </span>
                      </div>
                      {pCap > 0 && (
                        <div className="w-full bg-slate-200 dark:bg-slate-700 h-1 rounded-full overflow-hidden">
                          <div
                            className="h-full transition-all duration-300 rounded-full"
                            style={{
                              width: `${Math.min(100, pPct)}%`,
                              background: pPct > 80 ? '#ef4444' : pPct > 60 ? '#f59e0b' : '#10b981'
                            }}
                          />
                        </div>
                      )}
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* Center: rack elevation */}
        <div className="flex-1 rounded-xl overflow-hidden flex flex-col relative" style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }}>
          {selectedRack && layout ? (
            <>
              <div className="flex items-center justify-between px-4 py-2.5 border-b" style={{ borderColor: 'var(--card-border)' }}>
                <div className="flex items-center gap-3">
                  <h3 className="text-sm font-bold" style={{ color: 'var(--heading-text)' }}>
                    {selectedRack.name}
                    <span className="text-[11px] font-normal ml-2" style={{ color: 'var(--muted-text)' }}>
                      {siteLabel(selectedRack)}{selectedRack.floor ? ` / ${selectedRack.floor}` : ''}{selectedRack.room ? ` / ${selectedRack.room}` : ''}
                    </span>
                  </h3>
                  {/* 2D / 3D Mode Switch */}
                  <div className="flex items-center rounded-lg p-0.5" style={{ background: 'var(--app-hover-bg)', border: '1px solid var(--card-border)' }}>
                    <button
                      onClick={() => setViewMode('2d')}
                      className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all ${
                        viewMode === '2d' ? 'bg-cyan-600 text-white shadow-sm' : ''
                      }`}
                      style={viewMode !== '2d' ? { color: 'var(--muted-text)' } : {}}
                    >
                      <Columns3 size={12} />
                      {zh ? '2D 机柜' : '2D'}
                    </button>
                    <button
                      onClick={() => setViewMode('3d')}
                      className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all ${
                        viewMode === '3d' ? 'bg-cyan-600 text-white shadow-sm' : ''
                      }`}
                      style={viewMode !== '3d' ? { color: 'var(--muted-text)' } : {}}
                    >
                      <Box size={12} />
                      {zh ? '3D 孪生' : '3D'}
                    </button>
                  </div>

                  {viewMode === '2d' && (
                    <>
                      <div className="flex items-center rounded-lg p-0.5" style={{ background: 'var(--app-hover-bg)' }}>
                        <button onClick={() => setViewSide('front')} className={`px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all ${viewSide === 'front' ? 'bg-cyan-600 text-white shadow-sm' : ''}`} style={viewSide !== 'front' ? { color: 'var(--muted-text)' } : {}}>
                          {zh ? '前面板' : 'Front'}
                        </button>
                        <button onClick={() => setViewSide('rear')} className={`px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all ${viewSide === 'rear' ? 'bg-cyan-600 text-white shadow-sm' : ''}`} style={viewSide !== 'rear' ? { color: 'var(--muted-text)' } : {}}>
                          {zh ? '后面板' : 'Rear'}
                        </button>
                      </div>
                      <div className="flex items-center gap-1">
                        <button onClick={handleFitToScreen} className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium transition-colors hover:bg-cyan-50" style={{ color: 'var(--muted-text)' }} title={zh ? '适应屏幕' : 'Fit to Screen'}>
                          <Maximize2 size={12} />
                        </button>
                        <button onClick={handleResetZoom} className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium transition-colors hover:bg-cyan-50" style={{ color: 'var(--muted-text)' }} title={zh ? '原始大小' : '100%'}>
                          100%
                        </button>
                      </div>

                      <div className="flex items-center gap-1 ml-3 pl-3 border-l" style={{ borderColor: 'var(--card-border)' }}>
                        <button
                          onClick={() => setCollapseEmpty(!collapseEmpty)}
                          className={`flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium transition-all ${collapseEmpty ? 'bg-cyan-600/20 text-cyan-600' : 'hover:bg-cyan-50'}`}
                          style={!collapseEmpty ? { color: 'var(--muted-text)' } : {}}
                          title={zh ? '折叠空U位' : 'Collapse empty'}
                        >
                          {collapseEmpty ? <ChevronsUpDown size={12} /> : <Layers size={12} />}
                          {collapseEmpty ? (zh ? '已折叠' : 'Collapsed') : (zh ? '全展开' : 'Expand')}
                        </button>
                        <button
                          onClick={() => setShowDeviceList(!showDeviceList)}
                          className={`flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium transition-all ${showDeviceList ? 'bg-cyan-600/20 text-cyan-600' : 'hover:bg-cyan-50'}`}
                          style={!showDeviceList ? { color: 'var(--muted-text)' } : {}}
                          title={zh ? '设备栏' : 'Device list'}
                        >
                          {showDeviceList ? <PanelRightOpen size={12} /> : <PanelRightClose size={12} />}
                          {showDeviceList ? (zh ? '已显示' : 'Shown') : (zh ? '已隐藏' : 'Hidden')}
                        </button>
                      </div>
                    </>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-medium" style={{ color: 'var(--muted-text)' }}>
                    {layout.total_used}U / {layout.total_u}U ({layout.available_u}U {zh ? '可用' : 'free'})
                  </span>
                  {(layout as any).power_capacity_watts > 0 && (
                    <span className={`text-[11px] font-medium flex items-center gap-1 ${
                      ((layout as any).power_utilization_pct ?? 0) > 80 ? 'text-red-500' :
                      ((layout as any).power_utilization_pct ?? 0) > 60 ? 'text-amber-500' : 'text-emerald-500'
                    }`}>
                      <Zap size={11} />
                      {(layout as any).power_used_watts ?? 0} / {(layout as any).power_capacity_watts} W
                      {(layout as any).power_utilization_pct != null && (
                        <span className="text-[10px]">({(layout as any).power_utilization_pct}%)</span>
                      )}
                    </span>
                  )}
                  <ActionButton icon={Download} variant="accent" size="sm" onClick={handleDownloadRack}>{zh ? '下载 PNG' : 'Download PNG'}</ActionButton>
                  <button onClick={openInstallDevice} className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold text-white bg-cyan-600 hover:bg-cyan-700 transition-colors">
                    <Plus size={12} /> {zh ? '安装' : 'Install'}
                  </button>
                </div>
              </div>

              {viewMode === '3d' && rackVM ? (
                <div className="flex-1 min-h-0 relative" style={{ paddingRight: drawerVisible ? 396 : undefined }}>
                  <React.Suspense fallback={
                    <div className="flex items-center justify-center h-full" style={{ background: 'var(--card-bg)' }}>
                      <div className="text-center space-y-2">
                        <div className="animate-spin w-8 h-8 border-2 border-cyan-500 border-t-transparent rounded-full mx-auto" />
                        <p className="text-xs" style={{ color: 'var(--muted-text)' }}>{zh ? '正在加载 3D 引擎...' : 'Loading 3D Engine...'}</p>
                      </div>
                    </div>
                  }>
                    <Rack3DContainer
                      rackVM={rackVM}
                      selectedDeviceId={selectedDeviceId}
                      onSelectDevice={handleDeviceSelect}
                      onFallbackTo2D={() => setViewMode('2d')}
                      zh={zh}
                    />
                  </React.Suspense>
                </div>

              ) : (
                <div className="flex-1 min-h-0 overflow-y-auto p-3" ref={rackScrollRef} style={{ paddingRight: drawerVisible ? 396 : undefined }}>
                  <div className="text-[10px] font-semibold text-center mb-1.5 sticky top-0 z-10 pb-1" style={{ color: 'var(--muted-text)', background: 'var(--card-bg)' }}>
                    {viewSide === 'front' ? (zh ? '▼ 前面板 · 可拖拽' : '▼ Front · Draggable') : (zh ? '▼ 后面板 · 可拖拽' : '▼ Rear · Draggable')}
                  </div>
                  <div style={{ transform: `scale(${rackScale})`, transformOrigin: 'top center' }}>
                    <RackElevation
                      layout={layout}
                      viewSide={viewSide}
                      zh={zh}
                      collapseEmpty={collapseEmpty}
                      rackScale={rackScale}
                      scrollContainerRef={rackScrollRef}
                      onDeviceMove={handleDeviceMove}
                      onDeviceSelect={handleDeviceSelect}
                      onEmptySlotClick={openInstallDeviceAtU}
                    />
                  </div>
                </div>
              )}

              {/* Device Detail Drawer Overlay */}
              {drawerVisible && selectedDeviceId && (() => {
                const device = layout.devices.find(d => d.id === selectedDeviceId);
                if (!device) return null;
                const rc = getNormalizedRoleColor(device.device_role, device.name, device.model);
                const statusInfo = STATUS_LABEL[device.status] || { zh: device.status, en: device.status };
                const endU = device.start_u + device.u_height - 1;
                return (
                  <AnimatePresence>
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.2 }}
                      onClick={handleDrawerClose}
                      className="absolute inset-0 z-40 bg-black/20"
                      style={{ borderRadius: 'inherit' }}
                    />
                    <motion.div
                      initial={{ x: '100%' }}
                      animate={{ x: 0 }}
                      exit={{ x: '100%' }}
                      transition={{ duration: 0.3, ease: 'easeOut' }}
                      className="absolute right-0 top-0 bottom-0 z-50 flex flex-col w-96 rounded-xl overflow-hidden"
                      style={{ background: 'var(--card-bg)', boxShadow: '-2px 0 12px rgba(0,0,0,0.15)' }}
                    >
                      <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: 'var(--card-border)' }}>
                        <h3 className="text-sm font-bold" style={{ color: 'var(--heading-text)' }}>{device.name}</h3>
                        <button onClick={handleDrawerClose} className="p-1 rounded-lg hover:bg-black/5">
                          <X size={18} style={{ color: 'var(--muted-text)' }} />
                        </button>
                      </div>
                      <div className="flex-1 overflow-y-auto p-4 space-y-3">
                        {drawerAssetLoading && (
                          <div className="text-xs flex items-center gap-2 mb-3" style={{ color: 'var(--muted-text)' }}>
                            <RefreshCw size={12} className="animate-spin" />
                            {zh ? '正在加载资产详情…' : 'Loading asset details...'}
                          </div>
                        )}
                        {drawerAssetDetail ? (
                          <div className="rounded-xl border border-black/10 bg-white p-3">
                            <AssetReadonlyDetailInner asset={drawerAssetDetail} zh={zh} />
                          </div>
                        ) : (
                          <>
                            <div className="flex gap-2 flex-wrap mb-2">
                              <span className="text-xs px-2.5 py-1 rounded-lg font-semibold" style={{ background: rc.bg + '20', color: rc.bg }}>
                                {zh ? rc.labelZh : rc.label}
                              </span>
                              <span className="text-xs px-2.5 py-1 rounded-lg font-semibold flex items-center gap-1" style={{ background: device.status === 'active' ? '#4ade80' + '20' : device.status === 'planned' ? '#fbbf24' + '20' : '#ef4444' + '20', color: device.status === 'active' ? '#4ade80' : device.status === 'planned' ? '#fbbf24' : '#ef4444' }}>
                                <span className="w-2 h-2 rounded-full" style={{ background: 'currentColor' }} />
                                {zh ? statusInfo.zh : statusInfo.en}
                              </span>
                              <span className="text-xs px-2.5 py-1 rounded-lg font-semibold flex items-center gap-1" style={{ background: '#f59e0b20', color: '#f59e0b' }}>
                                <Zap size={13} />
                                {device.power_watts ?? 0} W
                              </span>
                            </div>

                            {/* Quick U-Position Relocation Control */}
                            <div className="p-3 rounded-xl border" style={{ background: 'var(--app-hover-bg)', borderColor: 'var(--card-border)' }}>
                              <div className="flex items-center justify-between mb-2">
                                <label className="text-[11px] font-bold" style={{ color: 'var(--heading-text)' }}>
                                  {zh ? '快速迁移 U 位' : 'Quick Move U Position'}
                                </label>
                                <span className="text-[10px] font-mono" style={{ color: 'var(--muted-text)' }}>
                                  {device.u_height}U {zh ? '高度' : 'Height'}
                                </span>
                              </div>
                              <div className="flex items-center gap-2">
                                <button
                                  type="button"
                                  onClick={() => {
                                    if (device.start_u > 1) {
                                      handleDeviceMove(device.id, device.start_u - 1);
                                    }
                                  }}
                                  disabled={device.start_u <= 1}
                                  className="px-2.5 py-1.5 rounded-lg text-xs font-bold border disabled:opacity-35 hover:bg-cyan-500/10 transition-colors"
                                  style={{ borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                                  title={zh ? '下移 1U (向 U1 方向)' : 'Move Down 1U'}
                                >
                                  -1U (下移)
                                </button>
                                <div className="flex-1 text-center py-1 rounded-lg font-mono font-bold text-xs bg-black/5" style={{ color: 'var(--heading-text)' }}>
                                  U{device.start_u} {endU !== device.start_u ? `~ U${endU}` : ''}
                                </div>
                                <button
                                  type="button"
                                  onClick={() => {
                                    if (layout && device.start_u + device.u_height - 1 < layout.total_u) {
                                      handleDeviceMove(device.id, device.start_u + 1);
                                    }
                                  }}
                                  disabled={!layout || device.start_u + device.u_height - 1 >= layout.total_u}
                                  className="px-2.5 py-1.5 rounded-lg text-xs font-bold border disabled:opacity-35 hover:bg-cyan-500/10 transition-colors"
                                  style={{ borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                                  title={zh ? '上移 1U (向顶部方向)' : 'Move Up 1U'}
                                >
                                  +1U (上移)
                                </button>
                              </div>
                            </div>

                            <div className="grid grid-cols-2 gap-x-2.5 gap-y-2 text-[11px]">
                              <div>
                                <label className="block text-[10px] font-semibold mb-0.5" style={{ color: 'var(--muted-text)' }}>{zh ? '厂商' : 'Vendor'}</label>
                                <div className="px-2.5 py-1.5 rounded border" style={{ background: 'var(--app-hover-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}>{device.vendor || '—'}</div>
                              </div>
                              <div>
                                <label className="block text-[10px] font-semibold mb-0.5" style={{ color: 'var(--muted-text)' }}>{zh ? '型号' : 'Model'}</label>
                                <div className="px-2.5 py-1.5 rounded border" style={{ background: 'var(--app-hover-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}>{device.model || '—'}</div>
                              </div>
                              <div>
                                <label className="block text-[10px] font-semibold mb-0.5 text-amber-500 font-medium">{zh ? '额定功率' : 'Rated Power'}</label>
                                <div className="px-2.5 py-1.5 rounded border font-mono font-bold text-amber-500 flex items-center gap-1" style={{ background: 'var(--app-hover-bg)', borderColor: 'var(--card-border)' }}>
                                  <Zap size={12} /> {device.power_watts ?? 0} W
                                </div>
                              </div>
                              <div>
                                <label className="block text-[10px] font-semibold mb-0.5" style={{ color: 'var(--muted-text)' }}>{zh ? 'U位' : 'Unit'}</label>
                                <div className="px-2.5 py-1.5 rounded border" style={{ background: 'var(--app-hover-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}>U{device.start_u}{endU !== device.start_u ? `-U${endU}` : ''}</div>
                              </div>
                              <div>
                                <label className="block text-[10px] font-semibold mb-0.5" style={{ color: 'var(--muted-text)' }}>{zh ? '序列号' : 'Serial No.'}</label>
                                <div className="px-2.5 py-1.5 rounded border font-mono text-[10px]" style={{ background: 'var(--app-hover-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}>{device.serial_number || '—'}</div>
                              </div>
                              <div>
                                <label className="block text-[10px] font-semibold mb-0.5" style={{ color: 'var(--muted-text)' }}>{zh ? '资产ID' : 'Asset ID'}</label>
                                <div className="px-2.5 py-1.5 rounded border font-mono text-[10px]" style={{ background: 'var(--app-hover-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}>{device.asset_id || '—'}</div>
                              </div>
                              <div>
                                <label className="block text-[10px] font-semibold mb-0.5" style={{ color: 'var(--muted-text)' }}>{zh ? '位置' : 'Side'}</label>
                                <div className="px-2.5 py-1.5 rounded border" style={{ background: 'var(--app-hover-bg)', borderColor: 'var(--card-border)', color: 'var(--body-text)' }}>{device.position === 'front' ? (zh ? '前面板' : 'Front') : (zh ? '后面板' : 'Rear')}</div>
                              </div>
                            </div>

                            {/* Live SNMP Port Matrix */}
                            <div className="pt-2">
                              <DevicePortMatrix
                                deviceId={device.asset_id || device.id}
                                deviceName={device.name}
                                deviceRole={device.device_role}
                                zh={zh}
                              />
                            </div>
                          </>
                        )}
                      </div>

                      <div className="p-4 border-t" style={{ borderColor: 'var(--card-border)' }}>
                        <button onClick={() => handleRemoveDevice(device.id, device.name)} className="w-full px-3 py-2 rounded-lg text-[12px] font-medium text-red-500 hover:bg-red-50/80">{zh ? '移除设备' : 'Remove'}</button>
                      </div>
                    </motion.div>
                  </AnimatePresence>
                );
              })()}
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center" style={{ color: 'var(--muted-text)' }}>
              {loading ? <RefreshCw size={20} className="animate-spin" /> : (zh ? '请选择机柜' : 'Select a rack')}
            </div>
          )}
        </div>

        {/* Right: installed device list */}
        {showDeviceList && (
          <div className="w-64 flex-shrink-0 rounded-xl overflow-hidden flex flex-col" style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }}>
            {!layout ? (
              <div className="flex-1 flex items-center justify-center" style={{ color: 'var(--muted-text)' }}>
                {zh ? '请选择机柜' : 'Select a rack'}
              </div>
            ) : (
              <>
                <div className="p-3 border-b" style={{ borderColor: 'var(--card-border)' }}>
                  <h4 className="text-[12px] font-semibold" style={{ color: 'var(--heading-text)' }}>
                    {zh ? '已安装设备' : 'Installed Devices'} ({layout?.devices.length || 0})
                  </h4>
                  <p className="text-[10px] mt-1" style={{ color: 'var(--muted-text)' }}>
                    {zh ? '点击查看详情' : 'Click to view details'}
                  </p>
                </div>
                <div className="flex-1 overflow-y-auto p-2.5 space-y-1.5">
                  {layout.devices.length === 0 ? (
                    <p className="text-xs py-6 text-center" style={{ color: 'var(--muted-text)' }}>
                      {zh ? '暂无设备' : 'No devices'}
                    </p>
                  ) : layout.devices.map(d => {
                    const rc = getNormalizedRoleColor(d.device_role, d.name, d.model);
                    const isSelected = selectedDeviceId === d.id;
                    return (
                      <button
                        key={d.id}
                        onClick={() => handleDeviceSelect(d.id)}
                        className={`w-full flex items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-all text-[12px] ${isSelected ? 'ring-1 ring-cyan-500 bg-cyan-50' : 'hover:bg-black/5 border border-transparent'}`}
                      >
                        <div className="w-6 h-6 rounded flex items-center justify-center flex-shrink-0" style={{ background: rc.bg + '20', color: rc.bg }}>
                          <DeviceIcon role={d.device_role} name={d.name} model={d.model} size={12} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="font-semibold truncate" style={{ color: 'var(--heading-text)' }}>{d.name}</p>
                          <div className="flex items-center gap-2 text-[10px]" style={{ color: 'var(--muted-text)' }}>
                            <span>U{d.start_u}</span>
                            <span>•</span>
                            <span className="font-mono text-amber-500 flex items-center gap-0.5 font-semibold">
                              <Zap size={10} /> {d.power_watts ?? 0}W
                            </span>
                          </div>
                        </div>
                        <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: d.status === 'active' ? '#4ade80' : d.status === 'planned' ? '#fbbf24' : '#ef4444' }} />
                      </button>
                    );
                  })}
                </div>
              </>
            )}
            {layout && layout.devices.length > 0 && (
              <div className="p-3 border-t space-y-1.5" style={{ borderColor: 'var(--card-border)' }}>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="text-[10px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '电源' : 'Power'}:</span>
                  {[
                    { color: '#4ade80', glow: true,  label: zh ? '通电' : 'ON' },
                    { color: '#ef4444', glow: false, label: zh ? '断电' : 'OFF' },
                    { color: '#fbbf24', glow: false, label: zh ? '规划' : 'Plan' },
                  ].map((item, i) => (
                    <div key={i} className="flex items-center gap-1">
                      <span
                        className="w-2 h-2 rounded-full"
                        style={{
                          background: item.color,
                          boxShadow: item.glow ? `0 0 4px ${item.color}` : 'none',
                        }}
                      />
                      <span className="text-[9px]" style={{ color: 'var(--muted-text)' }}>{item.label}</span>
                    </div>
                  ))}
                </div>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-[10px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '设备类型' : 'Device Types'}:</span>
                  {Object.entries(ROLE_COLORS).map(([role, rc]) => (
                    <div key={role} className="flex items-center gap-1">
                      <span className="w-2 h-2 rounded" style={{ background: rc.bg }} />
                      <span className="text-[9px]" style={{ color: 'var(--muted-text)' }}>{zh ? rc.labelZh : rc.label}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-2.5 rounded-xl bg-red-600 text-white text-sm shadow-lg">
          <AlertTriangle size={16} />
          <span className="max-w-xs truncate">{error}</span>
          <button onClick={() => setError('')}><X size={14} /></button>
        </div>
      )}

      <AnimatePresence>
        {blockedDeleteRack && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setBlockedDeleteRack(null)}>
            <motion.div initial={{ scale: 0.97, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.97, opacity: 0 }} transition={{ duration: 0.15 }} className="w-full max-w-lg rounded-3xl bg-white shadow-2xl border border-black/5 overflow-hidden" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-start gap-3 p-5 border-b border-black/5 bg-red-50">
                <div className="rounded-2xl bg-red-100 p-3 text-red-700"><AlertTriangle size={22} /></div>
                <div>
                  <h3 className="text-lg font-semibold text-red-900">{zh ? '无法删除机柜' : 'Cannot Delete Rack'}</h3>
                  <p className="mt-2 text-sm text-black/70">
                    {zh
                      ? `机柜 ${blockedDeleteRack.rackName || ''} 当前还有 ${blockedDeleteRack.deviceCount} 台已安装设备。请先移除机柜中的设备，然后再删除机柜。`
                      : `Rack ${blockedDeleteRack.rackName || ''} still contains ${blockedDeleteRack.deviceCount} installed devices. Remove those devices before deleting the rack.`}
                  </p>
                </div>
              </div>
              <div className="flex justify-end gap-3 p-5 bg-black/[0.02]">
                <button onClick={() => setBlockedDeleteRack(null)} className="px-4 py-2 rounded-xl border border-black/10 text-sm font-medium text-black/70 hover:bg-black/5 transition-all">
                  {zh ? '知道了' : 'Got it'}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}

        {confirmDeleteRack && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setConfirmDeleteRack(null)}>
            <motion.div initial={{ scale: 0.97, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.97, opacity: 0 }} transition={{ duration: 0.15 }} className="w-full max-w-lg rounded-3xl bg-white shadow-2xl border border-black/5 overflow-hidden" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-start gap-3 p-5 border-b border-black/5 bg-red-50">
                <div className="rounded-2xl bg-red-100 p-3 text-red-700"><AlertTriangle size={22} /></div>
                <div>
                  <h3 className="text-lg font-semibold text-red-900">{zh ? '确认删除机柜' : 'Confirm Delete Rack'}</h3>
                  <p className="mt-2 text-sm text-black/70">
                    {zh
                      ? `确认要删除机柜 ${confirmDeleteRack.rackName || ''} 吗？此操作会永久删除该空机柜，无法撤销。`
                      : `Are you sure you want to delete rack ${confirmDeleteRack.rackName || ''}? This will permanently remove the empty rack.`}
                  </p>
                </div>
              </div>
              <div className="flex justify-end gap-3 p-5 bg-black/[0.02]">
                <button onClick={() => setConfirmDeleteRack(null)} className="px-4 py-2 rounded-xl border border-black/10 text-sm font-medium text-black/70 hover:bg-black/5 transition-all">
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button onClick={confirmDeleteRackAction} className="px-4 py-2 rounded-xl bg-red-600 text-white text-sm font-semibold hover:bg-red-700 transition-all">
                  {zh ? '删除机柜' : 'Delete Rack'}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}

        {confirmRemoveDevice && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setConfirmRemoveDevice(null)}>
            <motion.div initial={{ scale: 0.97, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.97, opacity: 0 }} transition={{ duration: 0.15 }} className="w-full max-w-lg rounded-3xl bg-white shadow-2xl border border-black/5 overflow-hidden" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-start gap-3 p-5 border-b border-black/5 bg-amber-50">
                <div className="rounded-2xl bg-amber-100 p-3 text-amber-700"><AlertTriangle size={22} /></div>
                <div>
                  <h3 className="text-lg font-semibold text-amber-900">{zh ? '确认移除设备' : 'Confirm Remove Device'}</h3>
                  <p className="mt-2 text-sm text-black/70">
                    {zh
                      ? `确认要将设备 ${confirmRemoveDevice.deviceName} 从机柜中移除吗？该设备记录将保留。`
                      : `Remove ${confirmRemoveDevice.deviceName} from the rack? The asset record will remain intact.`}
                  </p>
                </div>
              </div>
              <div className="flex justify-end gap-3 p-5 bg-black/[0.02]">
                <button onClick={() => setConfirmRemoveDevice(null)} className="px-4 py-2 rounded-xl border border-black/10 text-sm font-medium text-black/70 hover:bg-black/5 transition-all">
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button onClick={confirmRemoveDeviceAction} className="px-4 py-2 rounded-xl bg-red-600 text-white text-sm font-semibold hover:bg-red-700 transition-all">
                  {zh ? '移除设备' : 'Remove Device'}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}

        {confirmMoveDevice && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setConfirmMoveDevice(null)}>
            <motion.div initial={{ scale: 0.97, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.97, opacity: 0 }} transition={{ duration: 0.15 }} className="w-full max-w-lg rounded-3xl bg-white shadow-2xl border border-black/5 overflow-hidden" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-start gap-3 p-5 border-b border-black/5 bg-blue-50">
                <div className="rounded-2xl bg-blue-100 p-3 text-blue-700"><ChevronsUpDown size={22} /></div>
                <div>
                  <h3 className="text-lg font-semibold text-blue-900">{zh ? '确认调整U位' : 'Confirm U-Position Move'}</h3>
                  <p className="mt-2 text-sm text-black/70">
                    {zh
                      ? `确认将设备 "${confirmMoveDevice.deviceName}" 从 U${confirmMoveDevice.oldU}-U${confirmMoveDevice.oldU + confirmMoveDevice.uHeight - 1} 移动至 U${confirmMoveDevice.newU}-U${confirmMoveDevice.newU + confirmMoveDevice.uHeight - 1}？调整后将自动同步更新资产管理中的起始U位信息。`
                      : `Move "${confirmMoveDevice.deviceName}" from U${confirmMoveDevice.oldU}-U${confirmMoveDevice.oldU + confirmMoveDevice.uHeight - 1} to U${confirmMoveDevice.newU}-U${confirmMoveDevice.newU + confirmMoveDevice.uHeight - 1}? The asset record will be updated automatically.`}
                  </p>
                </div>
              </div>
              <div className="flex justify-end gap-3 p-5 bg-black/[0.02]">
                <button onClick={() => setConfirmMoveDevice(null)} className="px-4 py-2 rounded-xl border border-black/10 text-sm font-medium text-black/70 hover:bg-black/5 transition-all">
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button onClick={confirmMoveDeviceAction} className="px-4 py-2 rounded-xl bg-[#00bceb] text-white text-sm font-semibold hover:bg-[#00a5d0] transition-all shadow-sm">
                  {zh ? '确认调整' : 'Confirm Move'}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ========== MODAL: Create/Edit Rack ========== */}
      <AnimatePresence>
        {showRackModal && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setShowRackModal(false)}>
            <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }} transition={{ duration: 0.15 }} className="w-full max-w-md rounded-2xl shadow-2xl p-6" style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }} onClick={e => e.stopPropagation()}>
              <h3 className="text-base font-bold mb-4" style={{ color: 'var(--heading-text)' }}>
                {editingRack ? (zh ? '编辑机柜' : 'Edit Rack') : (zh ? '新建机柜' : 'New Rack')}
              </h3>
              <div className="space-y-3">
                <div>
                  <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '机柜名称' : 'Name'} *</label>
                  <input value={rackForm.name} onChange={e => setRackForm({ ...rackForm, name: e.target.value })} className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} placeholder="A-01" />
                </div>
                <div>
                  <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '机柜类型模板' : 'Rack Type Template'}</label>
                  <select
                    value={rackForm.rack_type_id}
                    onChange={e => applyRackTypeToForm(e.target.value)}
                    className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30"
                    style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}
                  >
                    <option value="">{zh ? '不使用模板 / 自定义' : 'Custom / No template'}</option>
                    {rackTypes.map(rt => (
                      <option key={rt.id} value={rt.id}>
                        {rt.name} · {rt.total_u}U{rt.width_mm || rt.depth_mm ? ` · ${rt.width_mm || '-'}x${rt.depth_mm || '-'}mm` : ''}
                      </option>
                    ))}
                  </select>
                  <p className="text-[10px] mt-0.5" style={{ color: 'var(--muted-text)' }}>
                    {zh ? '选择模板会自动填充规格，保存前仍可覆盖。' : 'Selecting a template pre-fills specs; you can still override them.'}
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '站点' : 'Site'} *</label>
                    <select value={rackForm.site_id} onChange={e => setRackForm({ ...rackForm, site_id: e.target.value })} className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}>
                      <option value="">{zh ? '请选择站点' : 'Select site'}</option>
                      {siteOptions.map(site => <option key={site.id} value={site.id}>{site.site_code} · {site.site_name}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '楼层' : 'Floor'}</label>
                    <input value={rackForm.floor} onChange={e => setRackForm({ ...rackForm, floor: e.target.value })} className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} placeholder={zh ? '例如 3F' : 'e.g. 3F'} />
                  </div>
                  <div>
                    <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '机房' : 'Room'}</label>
                    <input value={rackForm.room} onChange={e => setRackForm({ ...rackForm, room: e.target.value })} className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '列' : 'Row'}</label>
                    <input value={rackForm.row} onChange={e => setRackForm({ ...rackForm, row: e.target.value })} className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                  </div>
                  <div>
                    <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '总U位' : 'Total U'}</label>
                    <input type="number" min={1} max={60} value={rackForm.total_u ?? ''} onChange={e => {
                      const val = e.target.value;
                      setRackForm({ ...rackForm, total_u: val === '' ? '' as any : (parseInt(val) || 0) });
                    }} className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                  </div>
                  <div>
                    <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '最大功率 (W)' : 'Max Power (W)'}</label>
                    <input type="number" min={0} value={rackForm.power_capacity_watts ?? ''} onChange={e => {
                      const val = e.target.value;
                      setRackForm({ ...rackForm, power_capacity_watts: val === '' ? '' as any : (parseInt(val) || 0) });
                    }} placeholder="e.g. 6000" className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                    <p className="text-[10px] mt-0.5" style={{ color: 'var(--muted-text)' }}>{zh ? '机柜 PDU 最大承载功率，0 表示不限制' : 'PDU capacity, 0 = unlimited'}</p>
                  </div>
                  <div>
                    <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '上架安装策略' : 'Placement Strategy'}</label>
                    <select
                      value={rackForm.placement_strategy || 'bottom_first'}
                      onChange={e => setRackForm({ ...rackForm, placement_strategy: e.target.value })}
                      className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30"
                      style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}
                    >
                      <option value="bottom_first">{zh ? '底部优先 (Bottom First)' : 'Bottom First'}</option>
                      <option value="top_first">{zh ? '顶部优先 (Top First)' : 'Top First'}</option>
                    </select>
                    <p className="text-[10px] mt-0.5" style={{ color: 'var(--muted-text)' }}>{zh ? '推荐空闲U位时的搜索方向' : 'Recommendation search direction'}</p>
                  </div>
                </div>
                <div>
                  <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '备注' : 'Description'}</label>
                  <div className="mb-3 grid grid-cols-2 gap-3">
                    <input aria-label="rack width mm" type="number" min={0} value={rackForm.width_mm ?? ''} onChange={e => {
                      const val = e.target.value;
                      setRackForm({ ...rackForm, width_mm: val === '' ? '' as any : (parseInt(val) || 0) });
                    }} placeholder={zh ? '宽度(mm)' : 'Width (mm)'} className="w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                    <input aria-label="rack depth mm" type="number" min={0} value={rackForm.depth_mm ?? ''} onChange={e => {
                      const val = e.target.value;
                      setRackForm({ ...rackForm, depth_mm: val === '' ? '' as any : (parseInt(val) || 0) });
                    }} placeholder={zh ? '深度(mm)' : 'Depth (mm)'} className="w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                    <input aria-label="rack max weight kg" type="number" min={0} value={rackForm.max_weight_kg ?? ''} onChange={e => {
                      const val = e.target.value;
                      setRackForm({ ...rackForm, max_weight_kg: val === '' ? '' as any : (parseInt(val) || 0) });
                    }} placeholder={zh ? '最大承重(kg)' : 'Max Weight (kg)'} className="w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                    <select
                      aria-label="rack front rear mount"
                      value={rackForm.allow_front_rear_mount ? 'true' : 'false'}
                      onChange={e => setRackForm({ ...rackForm, allow_front_rear_mount: e.target.value === 'true' })}
                      className="w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30"
                      style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}
                    >
                      <option value="true">{zh ? '允许正反面' : 'Front/Rear allowed'}</option>
                      <option value="false">{zh ? '仅单面' : 'Single side only'}</option>
                    </select>
                  </div>
                  <textarea value={rackForm.description} onChange={e => setRackForm({ ...rackForm, description: e.target.value })} rows={2} className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none resize-none focus:ring-2 ring-cyan-500/30" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                </div>
              </div>
              {formError && <p className="text-xs text-red-500 mt-2">{formError}</p>}
              <div className="flex justify-end gap-2 mt-5">
                <button onClick={() => setShowRackModal(false)} className="px-4 py-1.5 rounded-lg text-xs font-medium" style={{ color: 'var(--muted-text)' }}>{zh ? '取消' : 'Cancel'}</button>
                <button onClick={saveRack} className="px-4 py-1.5 rounded-lg text-xs font-semibold text-white bg-cyan-600 hover:bg-cyan-700">{zh ? '保存' : 'Save'}</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ========== MODAL: Install Device ========== */}
      <AnimatePresence>
        {showDeviceModal && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={closeInstallModal}>
            <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }} transition={{ duration: 0.15 }} className="w-full max-w-xl rounded-2xl shadow-2xl p-6" style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }} onClick={e => e.stopPropagation()}>
              <h3 className="text-base font-bold mb-4" style={{ color: 'var(--heading-text)' }}>
                {zh ? '安装设备到机柜' : 'Install Device to Rack'}
              </h3>

              <div className="space-y-4 max-h-[70vh] overflow-y-auto">
                <div>
                  <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '搜索设备（名称或SN号）' : 'Search Device (Name or SN)'} *</label>
                  <div className="relative mt-1">
                    <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'var(--muted-text)' }} />
                    <input
                      value={assetSearch}
                      onChange={e => setAssetSearch(e.target.value)}
                      placeholder={zh ? '输入设备名称或SN号...' : 'Enter device name or SN...'}
                      className="w-full pl-9 pr-3 py-2 text-sm rounded-lg outline-none focus:ring-2 ring-cyan-500/30"
                      style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}
                      autoComplete="off"
                    />
                  </div>
                  {!assetSearch.trim() && assetTotal > INSTALL_ASSET_PAGE_SIZE && (
                    <p className="mt-1.5 text-[10px] leading-snug" style={{ color: 'var(--muted-text)' }}>
                      {zh
                        ? `资产库共 ${assetTotal} 台，当前每页 ${INSTALL_ASSET_PAGE_SIZE} 条；可点「加载更多」或输入关键字筛选。`
                        : `${assetTotal} assets; listing ${INSTALL_ASSET_PAGE_SIZE} per page. Use “Load more” or type to filter.`}
                    </p>
                  )}
                </div>

                <div>
                  {assetsLoading ? (
                    <div className="p-3 text-center text-[11px]" style={{ color: 'var(--muted-text)' }}>{zh ? '加载中...' : 'Loading...'}</div>
                  ) : availableAssets.length === 0 ? (
                    <div className="p-3 text-center text-[11px]" style={{ color: 'var(--muted-text)' }}>
                      {assets.length > 0
                        ? (zh ? '已加载的设备均已在机柜中上架' : 'All loaded devices are already installed in racks')
                        : assetSearch.trim()
                          ? (zh ? '未找到匹配的设备' : 'No devices match your search')
                          : (zh ? '资产库中无可用设备' : 'No devices available in asset library')}
                    </div>
                  ) : (
                    <div className="max-h-56 overflow-y-auto rounded-lg border" style={{ borderColor: 'var(--card-border)', background: 'var(--app-hover-bg)' }}>
                      {availableAssets.map(a => (
                        <button
                          key={a.id}
                          onClick={() => {
                            handleAssetSelect(a);
                            setAssetSearch('');
                          }}
                          className={`w-full text-left p-3 border-b transition-colors hover:opacity-80 ${
                            selectedAsset?.id === a.id ? 'bg-cyan-500/20' : ''
                          }`}
                          style={{ borderColor: 'var(--card-border)' }}
                        >
                          <div className="font-semibold text-[11px]">{a.hostname || a.asset_tag}</div>
                          <div className="text-[10px] mt-0.5" style={{ color: 'var(--muted-text)' }}>
                            {a.vendor} {a.model} • SN: {a.serial_number || '—'}
                          </div>
                        </button>
                      ))}
                    </div>
                  )}
                  {assets.length > 0 && (
                    <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[10px]" style={{ color: 'var(--muted-text)' }}>
                      <span>
                        {zh
                          ? `未上架可用 ${availableAssets.length} 台 (共已加载 ${assets.length} / ${assetTotal} 台)`
                          : `Available ${availableAssets.length} (Loaded ${assets.length} / ${assetTotal})`}
                      </span>
                      {installAssetsCanLoadMore && (
                        <button
                          type="button"
                          disabled={assetsLoading}
                          onClick={() => fetchInstallAssets(assetSearch, assetPage + 1, true)}
                          className="px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-opacity disabled:opacity-50"
                          style={{ borderColor: 'var(--card-border)', color: 'var(--body-text)' }}
                        >
                          {assetsLoading ? (zh ? '加载中…' : 'Loading…') : (zh ? '加载更多' : 'Load more')}
                        </button>
                      )}
                    </div>
                  )}
                </div>

                {selectedAsset && (
                  <div className="rounded-lg p-4" style={{ background: 'var(--app-hover-bg)', border: '2px solid var(--card-border)' }}>
                    <div className="text-sm font-bold mb-3" style={{ color: 'var(--heading-text)' }}>
                      {zh ? '✓ 已选择设备信息' : '✓ Selected Device Information'}
                    </div>
                    <div className="space-y-2">
                      <div className="grid grid-cols-2 gap-3 text-[11px]">
                        <div>
                          <span style={{ color: 'var(--muted-text)' }}>{zh ? '设备名称' : 'Device Name'}:</span>
                          <div style={{ color: 'var(--body-text)', fontWeight: 600 }}>{selectedAsset.hostname || selectedAsset.asset_tag}</div>
                        </div>
                        <div>
                          <span style={{ color: 'var(--muted-text)' }}>{zh ? '序列号' : 'Serial No'}:</span>
                          <div style={{ color: 'var(--body-text)', fontWeight: 600, fontFamily: 'monospace' }}>{selectedAsset.serial_number || '—'}</div>
                        </div>
                        <div>
                          <span style={{ color: 'var(--muted-text)' }}>{zh ? '制造商' : 'Vendor'}:</span>
                          <div style={{ color: 'var(--body-text)', fontWeight: 600 }}>{selectedAsset.vendor}</div>
                        </div>
                        <div>
                          <span style={{ color: 'var(--muted-text)' }}>{zh ? '型号' : 'Model'}:</span>
                          <div style={{ color: 'var(--body-text)', fontWeight: 600 }}>{selectedAsset.model}</div>
                        </div>
                        <div>
                          <span style={{ color: 'var(--muted-text)' }}>{zh ? '状态' : 'Status'}:</span>
                          <div style={{ color: 'var(--body-text)', fontWeight: 600 }}>
                            {selectedAsset.status === 'active' ? (zh ? '在用' : 'In Use') :
                             selectedAsset.status === 'in_storage' ? (zh ? '库存中' : 'In Storage') :
                             selectedAsset.status === 'maintenance' ? (zh ? '维护中' : 'Maintenance') :
                             selectedAsset.status === 'inactive' ? (zh ? '闲置' : 'Idle') : selectedAsset.status}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {selectedAsset && (
                  <div className="space-y-3 pt-2 border-t" style={{ borderColor: 'var(--card-border)' }}>
                    <div className="text-sm font-bold" style={{ color: 'var(--heading-text)' }}>
                      {zh ? '部署配置' : 'Deployment Configuration'}
                    </div>

                    <div>
                      <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '设备名称' : 'Device Name'} *</label>
                      <input
                        value={deviceForm.name}
                        onChange={e => setDeviceForm({ ...deviceForm, name: e.target.value })}
                        className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30"
                        style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}
                      />
                    </div>

                    <div>
                      <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '设备型号' : 'Device Type'} *</label>
                      <select
                        value={deviceForm.device_type_id}
                        onChange={e => {
                          const device_type_id = e.target.value;
                          const start_u = resolveStartUForInstall(device_type_id, deviceForm.position);
                          setDeviceForm({ ...deviceForm, device_type_id, start_u });
                        }}
                        className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30"
                        style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}
                      >
                        <option value="" disabled>{zh ? '选择设备型号' : 'Select device type'}</option>
                        {deviceTypes.map(dt => (
                          <option key={dt.id} value={dt.id}>{dt.vendor} {dt.model} ({dt.u_height}U - {dt.device_role})</option>
                        ))}
                      </select>
                      {selectedAsset && !deviceForm.device_type_id && deviceTypes.length > 0 && (
                        <p className="mt-1.5 text-[10px] leading-snug text-amber-600 dark:text-amber-400">
                          {zh
                            ? '未根据厂商/型号自动匹配机柜设备类型，请手动选择；若列表中无对应型号，请先在「设备型号」中新增。'
                            : 'No device type matched this asset’s vendor/model — pick one manually, or add a device type first.'}
                        </p>
                      )}
                    </div>

                    <div className="grid grid-cols-3 gap-3">
                      <div>
                        <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '起始U位' : 'Start U'} *</label>
                        <input
                          type="number"
                          min={1}
                          max={layout?.total_u || 60}
                          value={deviceForm.start_u}
                          onChange={e => setDeviceForm({ ...deviceForm, start_u: parseInt(e.target.value) || 1 })}
                          className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30"
                          style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}
                        />
                      </div>
                      <div>
                        <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '面板' : 'Side'}</label>
                        <select
                          value={deviceForm.position}
                          onChange={e => {
                            const position = e.target.value;
                            const start_u = resolveStartUForInstall(deviceForm.device_type_id, position);
                            setDeviceForm({ ...deviceForm, position, start_u });
                          }}
                          className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30"
                          style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}
                        >
                          <option value="front">{zh ? '前面板' : 'Front'}</option>
                          <option value="rear">{zh ? '后面板' : 'Rear'}</option>
                        </select>
                      </div>
                      <div>
                        <label className="text-[11px] font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '状态' : 'Status'}</label>
                        <select
                          value={deviceForm.status}
                          onChange={e => setDeviceForm({ ...deviceForm, status: e.target.value })}
                          className="mt-1 w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-cyan-500/30"
                          style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}
                        >
                          <option value="active">{zh ? '在线' : 'Active'}</option>
                          <option value="offline">{zh ? '离线' : 'Offline'}</option>
                          <option value="planned">{zh ? '规划中' : 'Planned'}</option>
                        </select>
                      </div>
                    </div>
                  </div>
                )}

                {formError && <p className="text-xs text-red-500 mt-2">{formError}</p>}
              </div>

              <div className="flex justify-end gap-2 mt-6 pt-4 border-t" style={{ borderColor: 'var(--card-border)' }}>
                {selectedAsset && (
                  <button
                    onClick={() => {
                      setFormError('');
                      setSelectedAsset(null);
                      setAssetSearch('');
                      setDeviceForm({ name: '', device_type_id: '', start_u: 1, position: 'front', status: 'active', serial_number: '', asset_id: '' });
                    }}
                    className="px-4 py-1.5 rounded-lg text-xs font-medium"
                    style={{ color: 'var(--muted-text)' }}
                  >
                    {zh ? '重新选择' : 'Reselect'}
                  </button>
                )}
                <button
                  onClick={closeInstallModal}
                  className="px-4 py-1.5 rounded-lg text-xs font-medium"
                  style={{ color: 'var(--muted-text)' }}
                >
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button
                  onClick={saveDevice}
                  disabled={!selectedAsset}
                  className="px-4 py-1.5 rounded-lg text-xs font-semibold text-white"
                  style={{
                    background: selectedAsset ? 'rgb(6, 182, 212)' : 'rgb(156, 163, 175)',
                    cursor: selectedAsset ? 'pointer' : 'not-allowed',
                  }}
                >
                  {zh ? '确认安装' : 'Confirm Install'}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ========== MODAL: Device Types ========== */}
      <AnimatePresence>
        {showDeviceTypeModal && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setShowDeviceTypeModal(false)}>
            <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }} transition={{ duration: 0.15 }} className="w-full max-w-lg rounded-2xl shadow-2xl p-6" style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }} onClick={e => e.stopPropagation()}>
              <h3 className="text-base font-bold mb-4" style={{ color: 'var(--heading-text)' }}>
                {zh ? '设备型号管理' : 'Device Type Management'}
              </h3>
              <div className="max-h-48 overflow-auto mb-4 rounded-lg" style={{ border: '1px solid var(--card-border)' }}>
                <table className="nx-data-table nx-data-table--compact text-[11px]">
                  <thead>
                    <tr style={{ background: 'var(--app-hover-bg)' }}>
                      <th className="px-2 py-1.5 text-left font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '型号' : 'Model'}</th>
                      <th className="px-2 py-1.5 text-left font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '厂商' : 'Vendor'}</th>
                      <th className="px-2 py-1.5 text-center font-semibold" style={{ color: 'var(--muted-text)' }}>U</th>
                      <th className="px-2 py-1.5 text-left font-semibold" style={{ color: 'var(--muted-text)' }}>{zh ? '角色' : 'Role'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {deviceTypes.map(dt => (
                      <tr key={dt.id} style={{ borderTop: '1px solid var(--card-border)' }}>
                        <td className="px-2 py-1.5 font-medium" style={{ color: 'var(--body-text)' }}>{dt.model}</td>
                        <td className="px-2 py-1.5" style={{ color: 'var(--muted-text)' }}>{dt.vendor}</td>
                        <td className="px-2 py-1.5 text-center font-mono" style={{ color: 'var(--body-text)' }}>{dt.u_height}</td>
                        <td className="px-2 py-1.5">
                          {(() => {
                            const rcDt = getNormalizedRoleColor(dt.device_role, dt.model, dt.vendor);
                            return (
                              <span className="px-1.5 py-0.5 rounded-full text-[9px] font-semibold" style={{ background: rcDt.bg + '20', color: rcDt.bg }}>
                                {zh ? rcDt.labelZh : rcDt.label}
                              </span>
                            );
                          })()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="pt-3 border-t" style={{ borderColor: 'var(--card-border)' }}>
                <p className="text-[11px] font-semibold mb-2" style={{ color: 'var(--heading-text)' }}>{zh ? '添加新型号' : 'Add New Type'}</p>
                <div className="grid grid-cols-2 gap-2">
                  <input value={dtForm.model} onChange={e => setDtForm({ ...dtForm, model: e.target.value })} placeholder={zh ? '型号 *' : 'Model *'} className="rounded-lg px-3 py-1.5 text-xs outline-none" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                  <input value={dtForm.vendor} onChange={e => setDtForm({ ...dtForm, vendor: e.target.value })} placeholder={zh ? '厂商' : 'Vendor'} className="rounded-lg px-3 py-1.5 text-xs outline-none" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                  <div className="flex items-center gap-2">
                    <label className="text-[10px] flex-shrink-0" style={{ color: 'var(--muted-text)' }}>U{zh ? '高度' : ' Height'}:</label>
                    <input type="number" min={1} max={20} value={dtForm.u_height} onChange={e => setDtForm({ ...dtForm, u_height: parseInt(e.target.value) || 1 })} className="w-16 rounded-lg px-2 py-1.5 text-xs outline-none" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                  </div>
                  <div className="flex items-center gap-2">
                    <label className="text-[10px] flex-shrink-0" style={{ color: 'var(--muted-text)' }}>{zh ? '功率(W)' : 'Power(W)'}:</label>
                    <input type="number" min={0} value={dtForm.power_watts} onChange={e => setDtForm({ ...dtForm, power_watts: parseInt(e.target.value) || 0 })} placeholder="0" className="w-20 rounded-lg px-2 py-1.5 text-xs outline-none" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }} />
                  </div>
                  <select value={dtForm.device_role} onChange={e => setDtForm({ ...dtForm, device_role: e.target.value })} className="rounded-lg px-2 py-1.5 text-xs outline-none" style={{ background: 'var(--app-hover-bg)', color: 'var(--body-text)', border: '1px solid var(--card-border)' }}>
                    {Object.entries(ROLE_COLORS).map(([key, rc]) => (
                      <option key={key} value={key}>{zh ? rc.labelZh : rc.label}</option>
                    ))}
                  </select>
                </div>
              </div>
              {formError && <p className="text-xs text-red-500 mt-2">{formError}</p>}
              <div className="flex justify-end gap-2 mt-4">
                <button onClick={() => setShowDeviceTypeModal(false)} className="px-4 py-1.5 rounded-lg text-xs font-medium" style={{ color: 'var(--muted-text)' }}>{zh ? '关闭' : 'Close'}</button>
                <button onClick={saveDeviceType} className="px-4 py-1.5 rounded-lg text-xs font-semibold text-white bg-cyan-600 hover:bg-cyan-700">{zh ? '添加' : 'Add'}</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
      </div>
    </div>
  );
};

export default RackManagementTab;
