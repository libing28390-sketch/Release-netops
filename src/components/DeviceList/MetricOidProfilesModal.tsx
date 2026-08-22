import React, { useEffect, useState } from 'react';
import { Cpu, Database, Plus, Sparkles, X } from 'lucide-react';
import { apiRequest } from '../../api/http';
import OidPickerModal, { MibNodeItem } from '../SnmpMib/OidPickerModal';
import MibUploadModal from '../SnmpMib/MibUploadModal';
import PresetProfilesModal, { ModelPresetItem } from '../SnmpMib/PresetProfilesModal';

import {
  MetricRow,
  MetricDefinition,
  createDefinition,
  hasDefinition,
  toPayload,
  allowedModes,
  metricLabel,
  catalogEntry,
  METRIC_CATALOG,
  MetricMode,
  CounterBits,
} from '../SnmpMib/components/MetricRowItem';
import {
  InterfaceOidConfig,
  DEFAULT_INTERFACE_CONFIG,
} from '../SnmpMib/components/InterfaceConfigSection';
import {
  MetricOidProfile,
  MetricProfileList,
} from '../SnmpMib/components/MetricProfileList';
import {
  ProfileForm,
  MetricProfileEditor,
  InterfaceTestResult,
} from '../SnmpMib/components/MetricProfileEditor';
import { CandidateDevice } from '../SnmpMib/components/LiveWalkInspector';
import type { InspectorTab } from '../SnmpMib/components/LiveWalkInspector';

interface MetricProfileListResponse {
  success: boolean;
  data: MetricOidProfile[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

interface MetricProfileMapping {
  collector_status: string;
  matched_device_count: number;
  profile_applied_device_count: number;
  blocked_device_count: number;
  metric_keys?: string[];
  interface_configured?: boolean;
  interface_verification_status?: string;
  interface_collector_status?: string;
  sample_device_id?: string | null;
  devices?: CandidateDevice[];
}

export interface Props {
  open: boolean;
  onClose: () => void;
  onChanged?: () => void;
  language: string;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  embedded?: boolean;
}

const DEFAULT_METRIC_KEYS = ['cpu', 'memory'];

const createDefaultRows = (keys = DEFAULT_METRIC_KEYS): MetricRow[] =>
  keys
    .map(key => catalogEntry(key))
    .filter((item): item is typeof METRIC_CATALOG[0] => Boolean(item))
    .map(item => ({ key: item.key, definition: createDefinition(item.key) }));

const textValue = (value: unknown, fallback = '') => {
  if (Array.isArray(value)) return value.join(',');
  return value === undefined || value === null ? fallback : String(value);
};

const definitionFromProfile = (
  key: string,
  config: Record<string, unknown> | undefined,
  legacyOid = '',
): MetricDefinition => {
  const base = createDefinition(key);
  const raw = config || {};
  const requestedMode = textValue(raw.mode, base.mode) as MetricMode;
  const mode = allowedModes(key).includes(requestedMode) ? requestedMode : base.mode;
  return {
    ...base,
    mode,
    oid: textValue(raw.oid, legacyOid),
    used_oid: textValue(raw.used_oid),
    total_oid: textValue(raw.total_oid),
    free_oid: textValue(raw.free_oid),
    capacity_oid: textValue(raw.capacity_oid),
    counter_bits:
      textValue(raw.counter_bits) === '32' || textValue(raw.counter_bits) === '64'
        ? (textValue(raw.counter_bits) as CounterBits)
        : '',
    counter_unit: textValue(raw.counter_unit, 'bits') === 'octets' ? 'octets' : 'bits',
    status_ok_values: textValue(raw.status_ok_values, textValue(raw.normal_values, base.status_ok_values)),
    status_warning_values: textValue(raw.status_warning_values, textValue(raw.warning_values)),
    status_fail_values: textValue(raw.status_fail_values, textValue(raw.failure_values, base.status_fail_values)),
    unit: textValue(raw.unit, mode === 'status_code' ? 'bool' : base.unit),
    aggregation: ['average', 'first', 'max', 'min', 'sum'].includes(textValue(raw.aggregation))
      ? (textValue(raw.aggregation) as any)
      : 'average',
    selector: textValue(raw.selector),
    scale: textValue(raw.scale, '1'),
    offset: textValue(raw.offset, '0'),
  };
};

const profileDefinitions = (profile: MetricOidProfile) => {
  const definitions = { ...(profile.metric_definitions || {}) };
  if (!definitions.cpu && (profile.cpu_config || profile.cpu_oid)) {
    definitions.cpu = profile.cpu_config || { mode: 'direct_percent', oid: profile.cpu_oid };
  }
  if (!definitions.memory && (profile.memory_config || profile.memory_oid)) {
    definitions.memory = profile.memory_config || { mode: 'direct_percent', oid: profile.memory_oid };
  }
  return definitions;
};

const interfaceConfigFromProfile = (profile?: MetricOidProfile): InterfaceOidConfig => {
  const raw = (profile?.interface_config || {}) as Record<string, unknown>;
  const mode = textValue(raw.counter_mode, 'auto');
  return {
    ...DEFAULT_INTERFACE_CONFIG,
    ...raw,
    enabled: raw.enabled === true || textValue(raw.enabled).toLowerCase() === 'true',
    counter_mode: mode === '32' || mode === '64' ? mode : 'auto',
  } as InterfaceOidConfig;
};

const rowsFromProfile = (profile: MetricOidProfile): MetricRow[] => {
  const definitions = profileDefinitions(profile);
  const configuredKeys = Object.keys(definitions);
  const keys = configuredKeys.length ? configuredKeys : DEFAULT_METRIC_KEYS;
  return Array.from(new Set(keys)).map(key => ({
    key,
    definition: definitionFromProfile(
      key,
      definitions[key],
      key === 'cpu' ? profile.cpu_oid : key === 'memory' ? profile.memory_oid : '',
    ),
  }));
};

const MetricOidProfilesModal: React.FC<Props> = ({
  open,
  onClose,
  onChanged,
  language,
  showToast,
  embedded = false,
}) => {
  const zh = language === 'zh';
  const [profiles, setProfiles] = useState<MetricOidProfile[]>([]);
  const [presets, setPresets] = useState<ModelPresetItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [initialLiveInspectorOpen, setInitialLiveInspectorOpen] = useState(false);
  const [initialInspectorTab, setInitialInspectorTab] = useState<InspectorTab>('snmpwalk');
  const [autoRunHardwareTest, setAutoRunHardwareTest] = useState(false);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);

  // Editor State
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [form, setForm] = useState<ProfileForm>({
    vendor: '',
    model: '',
    metrics: createDefaultRows(),
    interfaceConfig: { ...DEFAULT_INTERFACE_CONFIG },
  });
  const [candidateDevices, setCandidateDevices] = useState<CandidateDevice[]>([]);
  const [lastTestDetails, setLastTestDetails] = useState<{
    hardware?: Record<string, any>;
    interface?: InterfaceTestResult;
  } | null>(null);

  // Sub-Modals
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerTarget, setPickerTarget] = useState<{ metricKey: string; field: string } | null>(null);
  const [mibModalOpen, setMibModalOpen] = useState(false);
  const [presetModalOpen, setPresetModalOpen] = useState(false);
  const [autoMatchResult, setAutoMatchResult] = useState<{
    matched_series?: string;
    confidence?: number;
    preset?: ModelPresetItem;
  } | null>(null);

  // Auto-match on vendor/model input for new forms
  useEffect(() => {
    if (!editorOpen || (!form.vendor.trim() && !form.model.trim())) {
      setAutoMatchResult(null);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const params = new URLSearchParams();
        if (form.vendor.trim()) params.set('vendor', form.vendor.trim());
        if (form.model.trim()) params.set('model', form.model.trim());
        const res = await apiRequest<{ success: boolean; matched: boolean; data: any }>(
          `/api/platform-registry/mibs/auto-match?${params.toString()}`,
        );
        if (res.matched && res.data?.preset) {
          setAutoMatchResult(res.data);
        } else {
          setAutoMatchResult(null);
        }
      } catch {
        setAutoMatchResult(null);
      }
    }, 350);
    return () => clearTimeout(timer);
  }, [form.vendor, form.model, editorOpen]);

  // Load presets from backend
  const loadPresets = async () => {
    try {
      const res = await apiRequest<{ success: boolean; data: ModelPresetItem[] }>(
        '/api/platform-registry/mibs/presets/models',
      );
      if (Array.isArray(res.data)) {
        setPresets(res.data);
      }
    } catch {
      // ignore
    }
  };

  // Load profiles from backend
  const loadProfiles = async (): Promise<MetricOidProfile[]> => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (search.trim()) params.set('search', search.trim());
      const response = await apiRequest<MetricProfileListResponse>(
        '/api/platform-registry/snmp-metric-profiles?' + params.toString(),
      );
      const items = Array.isArray(response.data) ? response.data : [];
      setProfiles(items);
      setTotal(Number(response.total) || 0);
      if (Number.isFinite(response.page) && response.page >= 1 && response.page !== page) {
        setPage(response.page);
      }
      return items;
    } catch (error) {
      showToast(
        error instanceof Error ? error.message : zh ? '型号指标模板加载失败' : 'Failed to load metric profiles',
        'error',
      );
      return [];
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      void loadProfiles();
      void loadPresets();
    }
  }, [open, page, pageSize, search]);

  const resetForm = () => {
    setEditingId(null);
    setInitialLiveInspectorOpen(false);
    setInitialInspectorTab('snmpwalk');
    setAutoRunHardwareTest(false);
    setForm({
      vendor: '',
      model: '',
      metrics: createDefaultRows(),
      interfaceConfig: { ...DEFAULT_INTERFACE_CONFIG },
    });
    setCandidateDevices([]);
    setLastTestDetails(null);
    setAutoMatchResult(null);
  };

  const openCreate = () => {
    resetForm();
    setInitialLiveInspectorOpen(true);
    setInitialInspectorTab('snmpwalk');
    setEditorOpen(true);
  };

  const startEdit = async (
    profile: MetricOidProfile,
    options: { openLiveInspector?: boolean; initialTab?: InspectorTab; autoRunHardwareTest?: boolean } = {},
  ) => {
    setEditingId(profile.profile_id);
    setInitialLiveInspectorOpen(Boolean(options.openLiveInspector));
    setInitialInspectorTab(options.initialTab || 'snmpwalk');
    setAutoRunHardwareTest(Boolean(options.autoRunHardwareTest));
    const rows = rowsFromProfile(profile);
    setForm({
      vendor: profile.vendor,
      model: profile.model,
      metrics: rows,
      interfaceConfig: interfaceConfigFromProfile(profile),
    });
    setCandidateDevices([]);
    setLastTestDetails(null);
    setEditorOpen(true);

    // Fetch candidate devices for live WALK inspector
    if (profile.profile_id) {
      try {
        const mappingRes = await apiRequest<{ success: boolean; data: MetricProfileMapping }>(
          `/api/platform-registry/snmp-metric-profiles/${profile.profile_id}/mapping-validation`,
        );
        if (Array.isArray(mappingRes.data?.devices)) {
          setCandidateDevices(mappingRes.data.devices);
        }
      } catch {
        setCandidateDevices([]);
      }
    } else {
      setCandidateDevices([]);
    }
  };

  const handleClonePreset = (
    preset: ModelPresetItem,
    options: {
      openLiveInspector?: boolean;
      initialTab?: InspectorTab;
      autoRunHardwareTest?: boolean;
      candidateDevices?: CandidateDevice[];
    } = {},
  ) => {
    if (preset.testable === false || Object.keys(preset.metric_definitions || {}).length === 0) {
      showToast(
        zh
          ? `【${preset.vendor} ${preset.model}】目前只有 MD 文档范围，需先核验具体 OID`
          : `[${preset.vendor} ${preset.model}] is documentation-only; verify concrete OIDs first`,
        'info',
      );
      return;
    }
    const rows: MetricRow[] = [];
    Object.entries(preset.metric_definitions || {}).forEach(([key, def]: [string, any]) => {
      rows.push({
        key,
        definition: definitionFromProfile(key, def, def.oid || ''),
      });
    });

    setEditingId(null);
    setInitialLiveInspectorOpen(Boolean(options.openLiveInspector));
    setInitialInspectorTab(options.initialTab || 'snmpwalk');
    setAutoRunHardwareTest(Boolean(options.autoRunHardwareTest));
    setForm({
      vendor: preset.vendor,
      model: preset.model,
      metrics: rows.length ? rows : createDefaultRows(),
      interfaceConfig: preset.interface_config
        ? ({ ...DEFAULT_INTERFACE_CONFIG, ...preset.interface_config } as InterfaceOidConfig)
        : { ...DEFAULT_INTERFACE_CONFIG },
    });
    setCandidateDevices(options.candidateDevices || []);
    setLastTestDetails(null);
    setEditorOpen(true);
    showToast(
      zh
        ? `已载入官方预置【${preset.vendor} ${preset.model}】，可调整型号名称或参数后点击保存`
        : `Loaded preset [${preset.vendor} ${preset.model}], edit model or parameters and save`,
      'info',
    );
  };

  const handleApplyPreset = (preset: ModelPresetItem) => {
    if (preset.testable === false || Object.keys(preset.metric_definitions || {}).length === 0) {
      showToast(
        zh
          ? `【${preset.vendor} ${preset.model}】目前只有 MD 文档范围，需先核验具体 OID`
          : `[${preset.vendor} ${preset.model}] is documentation-only; verify concrete OIDs first`,
        'info',
      );
      return;
    }
    const rows: MetricRow[] = [];
    Object.entries(preset.metric_definitions || {}).forEach(([key, def]: [string, any]) => {
      rows.push({
        key,
        definition: definitionFromProfile(key, def, def.oid || ''),
      });
    });

    setInitialInspectorTab('snmpwalk');
    setAutoRunHardwareTest(false);
    setForm(prev => ({
      vendor: preset.vendor || prev.vendor,
      model: preset.model || prev.model,
      metrics: rows.length ? rows : createDefaultRows(),
      interfaceConfig: preset.interface_config
        ? ({ ...DEFAULT_INTERFACE_CONFIG, ...preset.interface_config } as InterfaceOidConfig)
        : { ...DEFAULT_INTERFACE_CONFIG },
    }));
    setEditorOpen(true);
    setPresetModalOpen(false);
    showToast(
      zh ? `已套用预置模板：${preset.vendor} ${preset.model}` : `Applied preset: ${preset.vendor} ${preset.model}`,
      'success',
    );
  };

  const openOidPicker = (metricKey: string, field: string) => {
    setPickerTarget({ metricKey, field });
    setPickerOpen(true);
  };

  const handleOidSelected = (node: MibNodeItem) => {
    if (!pickerTarget) return;
    const { metricKey, field } = pickerTarget;

    if (metricKey === '__interface') {
      setForm(prev => ({
        ...prev,
        vendor: prev.vendor.trim() || (node.vendor && node.vendor !== 'Standard' ? node.vendor : ''),
        interfaceConfig: {
          ...prev.interfaceConfig,
          [field]: node.oid,
        },
      }));
      showToast(zh ? `已填入接口 OID: ${node.oid}` : `Interface OID updated: ${node.oid}`, 'success');
      return;
    }

    setForm(prev => ({
      ...prev,
      vendor: prev.vendor.trim() || (node.vendor && node.vendor !== 'Standard' ? node.vendor : ''),
      metrics: prev.metrics.map(row => {
        if (row.key !== metricKey) return row;
        const patch: Partial<MetricDefinition> = { [field]: node.oid };
        if (node.recommended_mode && (allowedModes(row.key) as string[]).includes(node.recommended_mode)) {
          patch.mode = node.recommended_mode as MetricMode;
        }
        if (node.recommended_counter_bits) {
          patch.counter_bits = String(node.recommended_counter_bits) as CounterBits;
        }
        return {
          ...row,
          definition: {
            ...row.definition,
            ...patch,
          },
        };
      }),
    }));
    showToast(zh ? `已填入 ${metricKey} OID: ${node.oid}` : `${metricKey} OID updated: ${node.oid}`, 'success');
  };

  const handleMibNodeMappedToTemplate = (node: MibNodeItem, metricKey: string) => {
    const targetKey = catalogEntry(metricKey) ? metricKey : 'cpu';
    const targetField = targetKey === 'storage' ? 'used_oid' : 'oid';
    const nextMetrics = form.metrics.some(row => row.key === targetKey)
      ? form.metrics.map(row => {
          if (row.key !== targetKey) return row;
          const patch: Partial<MetricDefinition> = { [targetField]: node.oid };
          if (node.recommended_mode && (allowedModes(row.key) as string[]).includes(node.recommended_mode)) {
            patch.mode = node.recommended_mode as MetricMode;
          }
          if (node.recommended_counter_bits) {
            patch.counter_bits = String(node.recommended_counter_bits) as CounterBits;
          }
          return { ...row, definition: { ...row.definition, ...patch } };
        })
      : [
          ...form.metrics,
          {
            key: targetKey,
            definition: { ...createDefinition(targetKey), [targetField]: node.oid },
          },
        ];

    setForm(prev => ({
      ...prev,
      vendor: prev.vendor.trim() || node.vendor,
      metrics: nextMetrics,
    }));
    setMibModalOpen(false);
    setEditorOpen(true);
    showToast(
      zh
        ? `已将 ${node.node_name} 映射到${metricLabel(targetKey, true)}，请完善精确型号后保存`
        : `${node.node_name} mapped to ${metricLabel(targetKey, false)}; complete model and save`,
      'success',
    );
  };

  const saveProfile = async () => {
    if (!form.vendor.trim() || !form.model.trim()) {
      showToast(zh ? '请先选择厂商并填写精确型号' : 'Select a vendor and enter the exact model', 'error');
      return;
    }
    const metricDefinitions: Record<string, Record<string, unknown>> = {};
    for (const row of form.metrics) {
      const payload = toPayload(row.definition);
      if (Object.keys(payload).length) metricDefinitions[row.key] = payload;
    }
    if (!Object.keys(metricDefinitions).length && !form.interfaceConfig.enabled) {
      showToast(
        zh ? '请至少配置一项硬件指标或启用接口模板' : 'Configure a hardware metric or enable interface template',
        'error',
      );
      return;
    }

    const invalidCounter = form.metrics.find(
      row =>
        row.definition.mode === 'counter_rate_percent' &&
        hasDefinition(row.definition) &&
        !row.definition.counter_bits,
    );
    if (invalidCounter) {
      showToast(
        zh
          ? `${metricLabel(invalidCounter.key, true)} 计数器必须明确选择 32 位或 64 位`
          : `${metricLabel(invalidCounter.key, false)} counter width must be 32 or 64 bits`,
        'error',
      );
      return;
    }

    const invalidStatus = form.metrics.find(
      row =>
        row.definition.mode === 'status_code' &&
        hasDefinition(row.definition) &&
        !row.definition.status_ok_values.trim(),
    );
    if (invalidStatus) {
      showToast(
        zh
          ? `${metricLabel(invalidStatus.key, true)} 必须配置至少一个正常状态码`
          : `${metricLabel(invalidStatus.key, false)} requires at least one normal status code`,
        'error',
      );
      return;
    }

    const invalidNumber = form.metrics.find(row => {
      if (!hasDefinition(row.definition)) return false;
      return (
        !Number.isFinite(Number(row.definition.scale || 1)) ||
        !Number.isFinite(Number(row.definition.offset || 0))
      );
    });
    if (invalidNumber) {
      showToast(
        zh
          ? `${metricLabel(invalidNumber.key, true)} 的缩放或偏移必须是数字`
          : `${metricLabel(invalidNumber.key, false)} scale/offset must be numeric`,
        'error',
      );
      return;
    }

    const cpuConfig = metricDefinitions.cpu || {};
    const memoryConfig = metricDefinitions.memory || {};
    const interfacePayload = form.interfaceConfig.enabled ? { ...form.interfaceConfig } : {};
    setSaving(true);
    try {
      const isEdit = Boolean(editingId);
      const endpoint = isEdit
        ? '/api/platform-registry/snmp-metric-profiles/' + editingId
        : '/api/platform-registry/snmp-metric-profiles';
      const saved = await apiRequest<{ success: boolean; data?: { id?: string; profile_id?: string } }>(
        endpoint,
        {
          method: isEdit ? 'PUT' : 'POST',
          body: JSON.stringify({
            vendor: form.vendor.trim(),
            model: form.model.trim(),
            metric_definitions: metricDefinitions,
            cpu_config: cpuConfig,
            memory_config: memoryConfig,
            cpu_oid: String(cpuConfig.oid || ''),
            memory_oid: String(memoryConfig.oid || ''),
            interface_config: interfacePayload,
          }),
        },
      );
      const savedProfileId = String(saved.data?.profile_id || saved.data?.id || editingId || '');
      await loadProfiles();
      setEditorOpen(false);
      resetForm();
      showToast(zh ? '型号指标模板保存成功' : 'Profile saved successfully', 'success');
      onChanged?.();

      // Non-blocking mapping & validation test
      if (savedProfileId) {
        void (async () => {
          try {
            const mappingResponse = await apiRequest<{ success: boolean; data: MetricProfileMapping }>(
              '/api/platform-registry/snmp-metric-profiles/' + savedProfileId + '/mapping-validation',
            );
            const mapping = mappingResponse.data;
            if (mapping.sample_device_id) {
              void testProfile({ profile_id: savedProfileId, sample_device_id: mapping.sample_device_id });
            }
          } catch {
            // Background validation ignore
          }
        })();
      }
    } catch (error) {
      showToast(
        error instanceof Error ? error.message : zh ? '保存失败' : 'Save failed',
        'error',
      );
    } finally {
      setSaving(false);
    }
  };

  const deleteProfile = async () => {
    if (!editingId) return;
    if (
      !window.confirm(
        zh
          ? '删除后该型号将回退到系统内置厂商默认采集逻辑，确定删除吗？'
          : 'Delete profile and fall back to built-in vendor default?',
      )
    )
      return;
    setSaving(true);
    try {
      await apiRequest('/api/platform-registry/snmp-metric-profiles/' + editingId, { method: 'DELETE' });
      showToast(zh ? '指标模板已删除' : 'Profile deleted', 'success');
      await loadProfiles();
      onChanged?.();
      setEditorOpen(false);
      resetForm();
    } catch (error) {
      showToast(error instanceof Error ? error.message : zh ? '删除失败' : 'Delete failed', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteFromRow = async (profile: MetricOidProfile) => {
    if (!profile.profile_id) return;
    if (
      !window.confirm(
        zh
          ? `确定要删除型号模板【${profile.vendor} ${profile.model}】并回退到系统内置默认采集规则吗？`
          : `Delete profile [${profile.vendor} ${profile.model}] and fall back to default?`,
      )
    ) {
      return;
    }
    setLoading(true);
    try {
      await apiRequest('/api/platform-registry/snmp-metric-profiles/' + profile.profile_id, {
        method: 'DELETE',
      });
      showToast(
        zh ? `已删除型号模板【${profile.model}】` : `Deleted profile [${profile.model}]`,
        'success',
      );
      await loadProfiles();
      onChanged?.();
    } catch (error) {
      showToast(error instanceof Error ? error.message : zh ? '删除失败' : 'Delete failed', 'error');
    } finally {
      setLoading(false);
    }
  };

  const testProfile = async (profile: Pick<MetricOidProfile, 'profile_id' | 'sample_device_id'>) => {
    if (!profile.profile_id || !profile.sample_device_id) {
      showToast(zh ? '该型号没有可验证的样例设备' : 'No sample device available', 'error');
      return;
    }
    setTestingId(profile.profile_id);
    try {
      const endpoint = '/api/platform-registry/snmp-metric-profiles/' + profile.profile_id + '/test';
      const response = await apiRequest<{
        success: boolean;
        data: {
          passed: boolean;
          hardware_passed?: boolean | null;
          interface_passed?: boolean | null;
          message?: string;
          sample_hostname?: string;
          metrics?: Record<string, any>;
          interface?: InterfaceTestResult;
        };
      }>(endpoint, {
        method: 'POST',
        body: JSON.stringify({ device_id: profile.sample_device_id }),
      });
      const result = response.data;
      setLastTestDetails({ hardware: result.metrics, interface: result.interface });
      const message = result.passed
        ? zh
          ? '在线验证通过：' + (result.sample_hostname || '样例设备')
          : 'Verification passed: ' + (result.sample_hostname || 'sample device')
        : zh
          ? '验证失败：' + (result.message || '请检查接口 OID、位宽与 SNMP 认证')
          : 'Verification failed: ' + (result.message || 'Check OIDs, counter width, and SNMP view');
      showToast(message, result.passed ? 'success' : 'error');
      await loadProfiles();
      onChanged?.();
    } catch (error) {
      showToast(error instanceof Error ? error.message : zh ? '验证请求失败' : 'Verification request failed', 'error');
    } finally {
      setTestingId(null);
    }
  };

  const validateMapping = async (profile: MetricOidProfile) => {
    if (!profile.profile_id) return;
    try {
      const endpoint =
        '/api/platform-registry/snmp-metric-profiles/' + profile.profile_id + '/mapping-validation';
      const response = await apiRequest<{ success: boolean; data: MetricProfileMapping }>(endpoint);
      const mapping = response.data;
      const message = zh
        ? `映射范围：匹配 ${mapping.matched_device_count} 台 · 生效 ${mapping.profile_applied_device_count} 台 · 阻断 ${mapping.blocked_device_count} 台 · 指标 ${(mapping.metric_keys || []).map(k => metricLabel(k, true)).join('、') || '无'}`
        : `Mapping: ${mapping.matched_device_count} matched · ${mapping.profile_applied_device_count} active · ${mapping.blocked_device_count} blocked`;
      showToast(
        message,
        mapping.collector_status === 'active' ||
          mapping.collector_status === 'builtin_only' ||
          mapping.collector_status === 'no_matching_device'
          ? 'info'
          : 'error',
      );
    } catch (error) {
      showToast(error instanceof Error ? error.message : zh ? '映射校验失败' : 'Mapping validation failed', 'error');
    }
  };

  if (!open) return null;

  return (
    <div
      className={
        embedded
          ? 'h-full min-h-0 w-full'
          : 'fixed inset-0 z-[120] flex items-center justify-center bg-black/45 p-4 backdrop-blur-sm'
      }
      onMouseDown={embedded ? undefined : onClose}
    >
      <div
        className={
          embedded
            ? 'flex h-full min-h-0 w-full flex-col overflow-hidden rounded-2xl border border-black/8 bg-[var(--card-bg)] dark:border-white/10'
            : 'flex max-h-[92vh] w-full max-w-[1500px] flex-col overflow-hidden rounded-2xl border border-black/8 bg-[var(--card-bg)] shadow-2xl dark:border-white/10'
        }
        onMouseDown={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-black/6 px-5 py-4 dark:border-white/8">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-black/80 dark:text-white/85">
              <Cpu size={18} className="text-[#009ec4]" />
              {zh ? 'SNMP 型号指标模板与 MIB 知识库' : 'SNMP Model Metric Profiles & MIB Repository'}
            </div>
            <p className="mt-1 text-[11px] text-black/45 dark:text-white/45">
              {zh
                ? '按厂商与产品族聚合展示完整适配型号；第二列仅呈现采集指标，末列提供 SNMP Walk 与关联设备入口。'
                : 'Group supported models by vendor and product family; keep metrics, SNMP Walk, and linked devices visible.'}
            </p>
          </div>
          {!embedded && (
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg p-1.5 text-black/40 hover:bg-black/5 dark:text-white/45 dark:hover:bg-white/8"
            >
              <X size={17} />
            </button>
          )}
        </div>

        {/* Body content: List */}
        <div className="flex min-h-0 flex-1 overflow-hidden p-4 sm:p-5">
          <MetricProfileList
            profiles={profiles}
            presets={presets}
            loading={loading}
            total={total}
            page={page}
            pageSize={pageSize}
            search={search}
            language={language}
            onSearchChange={setSearch}
            onPageChange={setPage}
            onPageSizeChange={size => {
              setPageSize(size);
              setPage(1);
            }}
            onRefresh={() => {
              void loadProfiles();
              void loadPresets();
            }}
            onOpenCreate={openCreate}
            onOpenPresets={() => setPresetModalOpen(true)}
            onOpenMibs={() => setMibModalOpen(true)}
            onEdit={startEdit}
            onDeleteProfile={handleDeleteFromRow}
            onOpenSnmpWalk={(item, target) => {
              if ('profile_id' in item) {
                void startEdit(item, { openLiveInspector: true, initialTab: 'snmpwalk' });
              } else {
                handleClonePreset(item, {
                  openLiveInspector: true,
                  initialTab: 'snmpwalk',
                  candidateDevices: target ? [target] : [],
                });
              }
            }}
            onOpenCollectionResult={(item, target) => {
              if ('profile_id' in item) {
                void startEdit(item, {
                  openLiveInspector: true,
                  initialTab: 'validate',
                  autoRunHardwareTest: true,
                });
              } else {
                handleClonePreset(item, {
                  openLiveInspector: true,
                  initialTab: 'validate',
                  autoRunHardwareTest: Boolean(target),
                  candidateDevices: target ? [target] : [],
                });
              }
            }}
            onValidateMapping={validateMapping}
          />
        </div>
      </div>

      {/* Editor Modal */}
      {editorOpen && (
        <MetricProfileEditor
          editingId={editingId}
          form={form}
          saving={saving}
          language={language}
          candidateDevices={candidateDevices}
          initialLiveInspectorOpen={initialLiveInspectorOpen}
          initialInspectorTab={initialInspectorTab}
          autoRunHardwareTest={autoRunHardwareTest}
          autoMatchResult={autoMatchResult}
          lastTestDetails={lastTestDetails}
          onChangeForm={setForm}
          onSave={saveProfile}
          onDelete={deleteProfile}
          onClose={() => {
            if (!saving) setEditorOpen(false);
          }}
          onOpenOidPicker={openOidPicker}
          onApplyPreset={handleApplyPreset}
          showToast={showToast}
        />
      )}

      {/* Sub-Modals */}
      <OidPickerModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onSelect={handleOidSelected}
        targetMetricName={pickerTarget?.metricKey}
        initialVendor={form.vendor}
        language={language}
      />

      <MibUploadModal
        open={mibModalOpen}
        onClose={() => setMibModalOpen(false)}
        language={language}
        showToast={showToast}
        onMapNodeToTemplate={handleMibNodeMappedToTemplate}
      />

      <PresetProfilesModal
        open={presetModalOpen}
        onClose={() => setPresetModalOpen(false)}
        onApplyPreset={handleApplyPreset}
        language={language}
        showToast={showToast}
      />
    </div>
  );
};

export default MetricOidProfilesModal;
