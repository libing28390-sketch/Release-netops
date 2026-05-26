import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
  ClipboardList, X, Plus, Search, RefreshCw, CheckCircle2,
  XCircle, Shield, ChevronDown, Save, AlertTriangle, Info,
  ClipboardCheck, Paperclip, User, UserCheck
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import DateTimePicker from '../../../components/DateTimePicker';
import type { User as UserOption, SessionUser, ConfigTemplate } from '../../../types';
import type { ChangeOrder, ScenarioTemplate, ScenarioVariable, PlatformMeta, ScenarioPhasePreview } from '../types';
import { ORDER_TYPE_META, PRIORITY_META, RISK_META, EMPTY_TEMPLATE_PREVIEW } from '../constants';
import {
  riskLabel, variableLabel, getVariableHelpText, fmtTime, inferVariableMeta
} from '../helpers';

interface Props {
  language: string;
  currentUser: SessionUser;
  users: UserOption[];
  platforms: Record<string, PlatformMeta>;
  editingOrder: ChangeOrder | null;
  form: any;
  setForm: React.Dispatch<React.SetStateAction<any>>;
  saving: boolean;
  handleSave: () => void;
  handleSaveDraft: () => void;
  closeEditor: (forceClose?: boolean) => void;
  commandMode: 'manual' | 'template';
  setCommandMode: (mode: 'manual' | 'template') => void;
  selectedScenarioId: string;
  setSelectedScenarioId: React.Dispatch<React.SetStateAction<string>>;
  selectedScenarioPlatform: string;
  setSelectedScenarioPlatform: React.Dispatch<React.SetStateAction<string>>;
  templateVariables: Record<string, string>;
  setTemplateVariables: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  scenarioOptions: ScenarioTemplate[];
  findMatchingPlatform: (devicePlatform: string, platforms: string[] | Record<string, any>) => string | undefined;
  toConfigTemplateScenarioId: (id: string) => string;
  fromConfigTemplateScenarioId: (id: string) => string;
  isConfigTemplateScenarioId: (id: string) => boolean;
  showToast: (msg: string, type?: 'success' | 'error') => void;
  authHeaders: (withJson?: boolean) => Record<string, string>;
}

const FEATURE_CONTROL_SHEET = import.meta.env.VITE_FEATURE_CONTROL_SHEET === '0' ? false : true;

export const ChangeOrderEditor: React.FC<Props> = ({
  language,
  currentUser,
  users,
  platforms,
  editingOrder,
  form,
  setForm,
  saving,
  handleSave,
  handleSaveDraft,
  closeEditor,
  commandMode,
  setCommandMode,
  selectedScenarioId,
  setSelectedScenarioId,
  selectedScenarioPlatform,
  setSelectedScenarioPlatform,
  templateVariables,
  setTemplateVariables,
  scenarioOptions,
  findMatchingPlatform,
  toConfigTemplateScenarioId,
  fromConfigTemplateScenarioId,
  isConfigTemplateScenarioId,
  showToast,
  authHeaders,
}) => {
  const zh = language === 'zh';

  // ── Local UI States ──
  const [commandInput, setCommandInput] = useState('');
  const [deviceKeyword, setDeviceKeyword] = useState('');
  const [deviceOptions, setDeviceOptions] = useState<any[]>([]);
  const [deviceLoading, setDeviceLoading] = useState(false);
  const [showDevicePicker, setShowDevicePicker] = useState(false);
  const [selectedInventoryDevices, setSelectedInventoryDevices] = useState<any[]>([]);
  const [showControlSheet, setShowControlSheet] = useState(false);
  const [scenarioSearch, setScenarioSearch] = useState('');
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // ── Local Precheck / Preview states ──
  const [templatePreview, setTemplatePreview] = useState<ScenarioPhasePreview | null>(null);
  const [templatePreviewLoading, setTemplatePreviewLoading] = useState(false);
  const [templatePreviewError, setTemplatePreviewError] = useState('');
  const [precheckErrors, setPrecheckErrors] = useState<string[]>([]);
  const [precheckSuccess, setPrecheckSuccess] = useState(false);
  const [precheckLoading, setPrecheckLoading] = useState(false);

  // ── Click outside to close scenario dropdown ──
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // ── Selected Scenario & Platform resolution ──
  const selectedScenario = useMemo(
    () => scenarioOptions.find((item) => item.id === selectedScenarioId) || null,
    [scenarioOptions, selectedScenarioId],
  );

  const selectedScenarioPlatforms = useMemo(() => {
    if (!selectedScenario) return [] as string[];
    const allPlatforms = selectedScenario.supported_platforms?.length
      ? selectedScenario.supported_platforms
      : Object.keys(selectedScenario.platform_phases || {});
    
    // Filter by target devices if any have platforms
    const devicePlatforms = [...new Set((form.target_devices || []).map((d: any) => d.platform).filter(Boolean))] as string[];
    if (devicePlatforms.length > 0) {
      const filtered = allPlatforms.filter(p => 
        devicePlatforms.some(dp => findMatchingPlatform(dp, [p]))
      );
      if (filtered.length > 0) return filtered;
    }
    
    return allPlatforms;
  }, [selectedScenario, form.target_devices, findMatchingPlatform]);

  const selectedScenarioVariables = useMemo(() => {
    if (!selectedScenario) return [];
    
    if (selectedScenario.source_kind !== 'config_template') {
      return (selectedScenario.variables || []).filter((item) => item?.key);
    }
    
    const targetVendor = platforms[selectedScenarioPlatform]?.vendor;
    const matchedTemplate = (selectedScenario.templates || []).find(tpl => tpl.vendor === targetVendor) || 
                            (selectedScenario.templates || []).find(tpl => tpl.vendor?.toLowerCase() === targetVendor?.toLowerCase()) ||
                            (selectedScenario.templates || [])[0];
                            
    if (!matchedTemplate) return [];
    
    const content = matchedTemplate.content || '';
    const varMatches = [...content.matchAll(/\{\{\s*([\w.-]+)(?:\s*\|\s*[^}]+)?\s*\}\}/g)];
    const uniqueKeys = [...new Set(varMatches.map(m => m[1]))];
    
    return uniqueKeys.map(key => {
      const existing = (selectedScenario.variables || []).find(v => v.key === key);
      if (existing) return existing;
      const meta = inferVariableMeta(key);
      return {
        key,
        label: key,
        label_zh: key,
        ...meta,
      };
    });
  }, [selectedScenario, selectedScenarioPlatform, platforms]);

  const resolvedTemplateId = useMemo(() => {
    if (!selectedScenarioId) return '';
    if (!isConfigTemplateScenarioId(selectedScenarioId)) {
      return selectedScenarioId;
    }
    const baseId = fromConfigTemplateScenarioId(selectedScenarioId);
    if (!selectedScenario || !selectedScenario.templates || selectedScenario.templates.length === 0) {
      return baseId;
    }
    const targetVendor = platforms[selectedScenarioPlatform]?.vendor;
    if (targetVendor) {
      const matched = selectedScenario.templates.find(tpl => tpl.vendor === targetVendor);
      if (matched) return matched.id;
    }
    const matchedCaseInsensitive = selectedScenario.templates.find(tpl => 
      tpl.vendor?.toLowerCase() === targetVendor?.toLowerCase()
    );
    if (matchedCaseInsensitive) return matchedCaseInsensitive.id;
    return selectedScenario.templates[0].id;
  }, [selectedScenarioId, selectedScenario, selectedScenarioPlatform, platforms, fromConfigTemplateScenarioId, isConfigTemplateScenarioId]);

  const filteredScenarioOptions = useMemo(() => {
    const query = scenarioSearch.trim().toLowerCase();
    const devicePlatforms = [...new Set((form.target_devices || []).map((d: any) => d.platform).filter(Boolean))] as string[];
    let filtered = scenarioOptions;
    if (devicePlatforms.length > 0) {
      filtered = filtered.filter(item => {
        const supported = item.supported_platforms || [];
        return devicePlatforms.every(dp => !!findMatchingPlatform(dp, supported));
      });
    }

    if (!query) return filtered;
    return filtered.filter(
      (item) =>
        item.name.toLowerCase().includes(query) ||
        (item.name_zh && item.name_zh.toLowerCase().includes(query)) ||
        (item.category && item.category.toLowerCase().includes(query))
    );
  }, [scenarioOptions, scenarioSearch, form.target_devices, findMatchingPlatform]);

  const templateMissingRequired = useMemo(() => selectedScenarioVariables
    .filter((item) => item.required && !String(templateVariables[item.key] ?? '').trim())
    .map((item) => variableLabel(item, language)), [selectedScenarioVariables, templateVariables, language]);

  // ── Template logic effects ──
  useEffect(() => {
    if (commandMode !== 'template') return;
    if (!selectedScenario) {
      setTemplatePreview(null);
      setTemplatePreviewError('');
      return;
    }
    setSelectedScenarioPlatform((current) => {
      if (current && selectedScenarioPlatforms.includes(current)) return current;
      return selectedScenario.default_platform || selectedScenarioPlatforms[0] || '';
    });
    setTemplateVariables((current) => {
      const next: Record<string, string> = {};
      selectedScenarioVariables.forEach((item) => {
        next[item.key] = String(current[item.key] ?? '');
      });
      return next;
    });
  }, [commandMode, selectedScenario, selectedScenarioPlatforms, selectedScenarioVariables, setSelectedScenarioPlatform, setTemplateVariables]);

  useEffect(() => {
    if (commandMode !== 'template' || !selectedScenario) return;
    const devicePlatforms = [...new Set((form.target_devices || []).map((d: any) => d.platform).filter(Boolean))] as string[];
    if (selectedScenarioPlatforms.length === 1 && selectedScenarioPlatform !== selectedScenarioPlatforms[0]) {
      setSelectedScenarioPlatform(selectedScenarioPlatforms[0]);
    } else if (devicePlatforms.length > 0 && !selectedScenarioPlatform) {
      const matched = selectedScenarioPlatforms.find(p => 
        devicePlatforms.some(dp => findMatchingPlatform(dp, [p]))
      );
      if (matched) setSelectedScenarioPlatform(matched);
    } else if (!selectedScenarioPlatform) {
      const defaultPlatform = selectedScenario.default_platform || selectedScenarioPlatforms[0];
      if (defaultPlatform) setSelectedScenarioPlatform(defaultPlatform);
    }
  }, [selectedScenarioId, commandMode, selectedScenario, selectedScenarioPlatform, selectedScenarioPlatforms, form.target_devices, findMatchingPlatform, setSelectedScenarioPlatform]);

  // Auto-detect scenario from device platform
  useEffect(() => {
    if (commandMode !== 'template' || selectedScenarioId) return;
    const deviceWithPlatform = (form.target_devices || []).find((dev: any) => dev.platform);
    if (!deviceWithPlatform?.platform) return;

    const matchedScenario = scenarioOptions.find((scenario) => {
      const supportedPlatforms = scenario.supported_platforms?.length
        ? scenario.supported_platforms
        : Object.keys(scenario.platform_phases || {});
      return supportedPlatforms.some((p) => findMatchingPlatform(deviceWithPlatform.platform || '', [p]));
    });

    if (matchedScenario) {
      setSelectedScenarioId(matchedScenario.id);
      const platformsList = matchedScenario.supported_platforms?.length
        ? matchedScenario.supported_platforms
        : Object.keys(matchedScenario.platform_phases || {});
      const matchedPlatform = findMatchingPlatform(deviceWithPlatform.platform || '', platformsList);
      if (matchedPlatform) {
        setSelectedScenarioPlatform(matchedPlatform);
      }
    }
  }, [commandMode, selectedScenarioId, form.target_devices, scenarioOptions, setSelectedScenarioId, setSelectedScenarioPlatform, findMatchingPlatform]);

  // ── Render Template Local Preview ──
  const renderTemplateText = (templateText: string, vars: Record<string, string>) => {
    let text = templateText;
    Object.entries(vars).forEach(([key, value]) => {
      text = text.replace(new RegExp(`{{\\s*${key}\\s*}}`, 'g'), String(value));
    });
    text = text.replace(/\{\%.*?\%\}/g, '');
    text = text.replace(/\{\{.*?\}\}/g, '');
    return text.trim();
  };

  const renderPhaseCommands = (phaseTemplates: string[] = [], vars: Record<string, string>) => {
    const commands: string[] = [];
    phaseTemplates.forEach((tmpl) => {
      const rendered = renderTemplateText(tmpl, vars);
      rendered.split('\n').forEach((line) => {
        const trimmed = line.trimEnd();
        if (trimmed) {
          commands.push(trimmed);
        }
      });
    });
    return commands;
  };

  const getLocalTemplatePreview = (platformOverride?: string) => {
    const platformToUse = platformOverride || selectedScenarioPlatform;
    if (!selectedScenario || !platformToUse) return null;
    const phases = selectedScenario.platform_phases?.[platformToUse] || {};
    return {
      pre_check: renderPhaseCommands(phases.pre_check || [], templateVariables),
      execute: renderPhaseCommands(phases.execute || [], templateVariables),
      post_check: renderPhaseCommands(phases.post_check || [], templateVariables),
      rollback: renderPhaseCommands(phases.rollback || [], templateVariables),
    };
  };

  const effectivePreview = useMemo(() => {
    if (templatePreviewError) return null;
    if (templatePreview) return templatePreview;
    const platformToUse = selectedScenarioPlatform || selectedScenarioPlatforms[0] || '';
    return getLocalTemplatePreview(platformToUse);
  }, [templatePreview, templatePreviewError, selectedScenarioPlatform, selectedScenarioPlatforms, selectedScenario, templateVariables]);

  const fetchTemplatePreview = async (platformArg?: string, scenarioArg?: ScenarioTemplate | null) => {
    const scenario = scenarioArg !== undefined ? scenarioArg : selectedScenario;
    const scenarioId = scenario?.id || selectedScenarioId;
    const scenarioPlatforms = scenario
      ? (scenario.supported_platforms?.length ? scenario.supported_platforms : Object.keys(scenario.platform_phases || {}))
      : selectedScenarioPlatforms;
    const effectiveScenarioPlatform = platformArg || selectedScenarioPlatform || scenarioPlatforms[0] || '';
    if (commandMode !== 'template' || !scenarioId || !effectiveScenarioPlatform) {
      setTemplatePreview(null);
      return;
    }
    setTemplatePreviewLoading(true);
    setTemplatePreviewError('');
    try {
      const targetVendor = platforms[effectiveScenarioPlatform]?.vendor;
      let resolvedScenarioId = scenarioId;
      if (isConfigTemplateScenarioId(scenarioId)) {
        const baseId = fromConfigTemplateScenarioId(scenarioId);
        if (scenario && scenario.templates && scenario.templates.length > 0) {
          const targetTpl = scenario.templates.find(tpl => tpl.vendor === targetVendor) || 
                            scenario.templates.find(tpl => tpl.vendor?.toLowerCase() === targetVendor?.toLowerCase()) || 
                            scenario.templates[0];
          resolvedScenarioId = targetTpl.id;
        } else {
          resolvedScenarioId = baseId;
        }
      }

      const resp = await fetch('/api/change-orders/validate', {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify({
          scenario_id: resolvedScenarioId,
          source_kind: scenario?.source_kind || 'scenario',
          platform: effectiveScenarioPlatform,
          variables: templateVariables,
          target_devices: form.target_devices,
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error(String(data.detail || resp.statusText || 'Preview failed'));
      }
      if (data.success) {
        if (data.valid) {
          const preview = {
            pre_check: Array.isArray(data.preview?.pre_check) ? data.preview.pre_check : [],
            execute: Array.isArray(data.preview?.execute) ? data.preview.execute : [],
            post_check: Array.isArray(data.preview?.post_check) ? data.preview.post_check : [],
            rollback: Array.isArray(data.preview?.rollback) ? data.preview.rollback : [],
          };
          setTemplatePreview(preview);
          setTemplatePreviewError('');
        } else {
          setTemplatePreview(null);
          setTemplatePreviewError(data.errors?.join(' \n ') || (zh ? '模板参数校验未通过' : 'Template validation failed'));
        }
      } else {
        throw new Error(data.detail || data.message || 'Preview failed');
      }
    } catch (error) {
      setTemplatePreview(null);
      setTemplatePreviewError(error instanceof Error ? error.message : (zh ? '模板预览失败' : 'Template preview failed'));
    } finally {
      setTemplatePreviewLoading(false);
    }
  };

  useEffect(() => {
    if (commandMode !== 'template' || !selectedScenarioId) {
      setTemplatePreview(null);
      setTemplatePreviewError('');
      return;
    }
    const timer = setTimeout(() => {
      fetchTemplatePreview();
    }, 300);
    return () => clearTimeout(timer);
  }, [commandMode, selectedScenarioId, selectedScenarioPlatform, templateVariables]);

  useEffect(() => {
    setPrecheckErrors([]);
    setPrecheckSuccess(false);
  }, [selectedScenarioId, selectedScenarioPlatform, templateVariables]);

  // ── Pre-check run ──
  const runPrecheck = async () => {
    const effectiveScenarioPlatform = selectedScenarioPlatform || selectedScenarioPlatforms[0] || '';
    if (!selectedScenarioId) {
      showToast(zh ? '请先选择配置模板' : 'Please select a config template', 'error');
      return;
    }
    if (!effectiveScenarioPlatform) {
      showToast(zh ? '无法确定目标平台' : 'Cannot determine target platform', 'error');
      return;
    }
    setPrecheckLoading(true);
    setPrecheckErrors([]);
    setPrecheckSuccess(false);
    try {
      const payload = {
        scenario_id: resolvedTemplateId,
        source_kind: selectedScenario?.source_kind || 'scenario',
        platform: effectiveScenarioPlatform,
        variables: templateVariables,
        target_devices: form.target_devices,
      };
      const resp = await fetch('/api/change-orders/validate', {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify(payload),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error(String(data.detail || resp.statusText || 'Validation request failed'));
      }
      if (data.success) {
        if (data.valid) {
          setPrecheckSuccess(true);
          if (data.preview) {
            setTemplatePreview(data.preview);
          }
          showToast(zh ? '预检查通过，参数格式正确' : 'Precheck passed, parameters are valid');
        } else {
          setPrecheckErrors(data.errors || []);
          showToast(zh ? '预检查失败，请核对参数' : 'Precheck failed, please verify parameters', 'error');
        }
      } else {
        setPrecheckErrors([data.detail || data.message || 'Validation failed']);
        showToast(zh ? '预检查失败' : 'Precheck failed', 'error');
      }
    } catch (e: any) {
      setPrecheckErrors([e.message || 'Validation request failed']);
      showToast(zh ? '请求预检查失败' : 'Precheck request failed', 'error');
    } finally {
      setPrecheckLoading(false);
    }
  };

  // ── Device Picker Search ──
  const fetchDeviceOptions = async (keyword: string) => {
    if (!showDevicePicker) return;
    setDeviceLoading(true);
    try {
      const params = new URLSearchParams({ mode: 'light' });
      if (keyword.trim()) params.set('search', keyword.trim());
      const resp = await fetch(`/api/devices?${params.toString()}`, { headers: authHeaders() });
      const data = await resp.json();
      const rows = Array.isArray(data) ? data : (data?.data || []);
      const normalized = (rows || [])
        .map((d: any) => ({
          id: String(d.id || ''),
          hostname: String(d.hostname || ''),
          ip_address: String(d.ip_address || ''),
          platform: String(d.platform || ''),
          asset_tag: String(d.asset_tag || ''),
        }))
        .filter((d: any) => d.hostname || d.ip_address)
        .slice(0, 12);
      setDeviceOptions(normalized);
    } catch {
      setDeviceOptions([]);
    } finally {
      setDeviceLoading(false);
    }
  };

  useEffect(() => {
    if (!showDevicePicker) return;
    const timer = setTimeout(() => { fetchDeviceOptions(deviceKeyword); }, 250);
    return () => clearTimeout(timer);
  }, [deviceKeyword, showDevicePicker]);

  const addDeviceFromInventory = (dev: any) => {
    const next = { hostname: dev.hostname || '', ip_address: dev.ip_address || '', platform: dev.platform || '' };
    setForm((f: any) => {
      const exists = f.target_devices.some(
        (x: any) => (x.ip_address && next.ip_address && x.ip_address === next.ip_address)
          || (x.hostname && next.hostname && x.hostname === next.hostname)
      );
      if (exists) return f;
      return { ...f, target_devices: [...f.target_devices, next] };
    });
  };

  const confirmSelectedDevice = () => {
    if (selectedInventoryDevices.length === 0) {
      if (selectedInventoryDevice) {
        addDeviceFromInventory(selectedInventoryDevice);
      } else {
        return;
      }
    } else {
      selectedInventoryDevices.forEach(dev => {
        addDeviceFromInventory(dev);
      });
    }

    const firstDev = selectedInventoryDevices[0] || selectedInventoryDevice;
    if (commandMode === 'template' && selectedScenario && firstDev?.platform) {
      const platformsList = selectedScenario.supported_platforms?.length 
        ? selectedScenario.supported_platforms 
        : Object.keys(selectedScenario.platform_phases || {});
      const matchedPlatform = findMatchingPlatform(firstDev.platform, platformsList);
      if (matchedPlatform) {
        setSelectedScenarioPlatform(matchedPlatform);
      }
    }

    setSelectedInventoryDevice(null);
    setSelectedInventoryDevices([]);
    setShowDevicePicker(false);
    setDeviceKeyword('');
    setDeviceOptions([]);
  };

  // ── Commands & Variables helpers ──
  const addCommand = () => {
    if (!commandInput.trim()) return;
    setForm((f: any) => ({ ...f, commands: [...f.commands, commandInput.trim()] }));
    setCommandInput('');
  };

  const assignTemplateVariable = (key: string, value: string) => {
    setTemplateVariables((current) => ({ ...current, [key]: value }));
  };

  const platformLabel = (platformKey: string) => {
    if (!platformKey) return zh ? '未指定平台' : 'Unknown platform';
    const meta = platforms[platformKey] || {};
    const baseLabel = meta.name || platformKey;
    if (meta.icon && meta.vendor) return `${meta.icon} ${meta.vendor} · ${baseLabel}`;
    if (meta.icon) return `${meta.icon} ${baseLabel}`;
    if (meta.vendor) return `${meta.vendor} · ${baseLabel}`;
    return baseLabel;
  };

  const [selectedInventoryDevice, setSelectedInventoryDevice] = useState<any | null>(null);

  return (
    <motion.div
      key="change-order-editor-modal"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 10 }}
      className="order-first w-full mb-6"
    >
      <motion.div
        initial={{ scale: 0.98, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.98, opacity: 0 }}
        transition={{ type: 'spring', stiffness: 380, damping: 30 }}
        className="bg-white rounded-3xl border border-black/5 shadow-sm overflow-hidden flex flex-col"
      >
        {/* Modal header */}
        <div className="px-6 py-5 border-b border-black/5 bg-gradient-to-r from-[#00bceb]/[0.04] to-transparent flex items-center justify-between">
          <h3 className="text-lg font-semibold flex items-center gap-2.5">
            <span className="p-2 rounded-xl bg-[#00bceb]/10 ring-1 ring-[#00bceb]/15">
              <ClipboardList size={16} className="text-[#00bceb]" />
            </span>
            {editingOrder ? (zh ? '编辑工单' : 'Edit Order') : (zh ? '新建变更工单' : 'New Change Order')}
          </h3>
          <button title={zh ? '关闭编辑器' : 'Close editor'} onClick={() => closeEditor()} className="p-2 rounded-lg text-black/30 hover:text-black/60 hover:bg-black/5 transition-all">
            <X size={18} />
          </button>
        </div>

        {/* Modal body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {/* Title */}
          <div>
            <label className="block text-xs font-semibold text-black/50 mb-1.5">{zh ? '工单标题' : 'Title'} <span className="text-rose-500">*</span></label>
            <input
              value={form.title}
              onChange={e => setForm((f: any) => ({ ...f, title: e.target.value }))}
              placeholder={zh ? '例如: 核心交换机VLAN调整' : 'e.g.: Core switch VLAN adjustment'}
              className="w-full px-4 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 focus:ring-2 focus:ring-[#00bceb]/10 transition-all"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-semibold text-black/50 mb-1.5">{zh ? '描述' : 'Description'}</label>
            <textarea
              value={form.description}
              onChange={e => setForm((f: any) => ({ ...f, description: e.target.value }))}
              placeholder={zh ? '详细描述变更内容、影响范围...' : 'Describe the change, impact scope...'}
              rows={3}
              className="w-full px-4 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 focus:ring-2 focus:ring-[#00bceb]/10 transition-all resize-none"
            />
          </div>

          {/* Type + Priority + Risk — 3 columns */}
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-semibold text-black/50 mb-1.5">{zh ? '变更类型' : 'Type'} <span className="text-rose-500">*</span></label>
              <select
                title={zh ? '变更类型' : 'Change order type'}
                value={form.order_type}
                onChange={e => setForm((f: any) => ({ ...f, order_type: e.target.value }))}
                className="w-full px-3 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 bg-white"
              >
                {Object.entries(ORDER_TYPE_META).map(([k, v]) => (
                  <option key={k} value={k}>{v.label[zh ? 'zh' : 'en']}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold text-black/50 mb-1.5">{zh ? '优先级' : 'Priority'} <span className="text-rose-500">*</span></label>
              <select
                title={zh ? '优先级' : 'Priority'}
                value={form.priority}
                onChange={e => setForm((f: any) => ({ ...f, priority: e.target.value }))}
                className="w-full px-3 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 bg-white"
              >
                {Object.entries(PRIORITY_META).map(([k, v]) => (
                  <option key={k} value={k}>{v.label[zh ? 'zh' : 'en']}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold text-black/50 mb-1.5">{zh ? '风险等级' : 'Risk Level'} <span className="text-rose-500">*</span></label>
              <select
                title={zh ? '风险等级' : 'Risk level'}
                value={form.risk_level}
                onChange={e => setForm((f: any) => ({ ...f, risk_level: e.target.value }))}
                className="w-full px-3 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 bg-white"
              >
                {Object.entries(RISK_META).map(([k, v]) => (
                  <option key={k} value={k}>{v.label[zh ? 'zh' : 'en']}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Schedule */}
          <div className="grid grid-cols-2 gap-4">
            <DateTimePicker
              label={zh ? '计划开始时间' : 'Scheduled Start'}
              value={form.scheduled_start}
              onChange={v => {
                if (v && form.scheduled_end) {
                  if (v >= form.scheduled_end) {
                    showToast(zh ? '计划开始时间必须早于结束时间' : 'Start time must be earlier than end time', 'error');
                  } else {
                    const startMs = new Date(v.replace(' ', 'T')).getTime();
                    const endMs = new Date(form.scheduled_end.replace(' ', 'T')).getTime();
                    if (endMs - startMs > 14 * 24 * 60 * 60 * 1000) {
                      showToast(zh ? '计划周期不能超过 2 周' : 'Duration cannot exceed 2 weeks', 'error');
                    }
                  }
                }
                setForm((f: any) => ({ ...f, scheduled_start: v }));
              }}
              language={language}
              required
            />
            <DateTimePicker
              label={zh ? '计划结束时间' : 'Scheduled End'}
              value={form.scheduled_end}
              onChange={v => {
                if (v && form.scheduled_start) {
                  if (form.scheduled_start >= v) {
                    showToast(zh ? '计划结束时间必须晚于开始时间' : 'End time must be later than start time', 'error');
                  } else {
                    const startMs = new Date(form.scheduled_start.replace(' ', 'T')).getTime();
                    const endMs = new Date(v.replace(' ', 'T')).getTime();
                    if (endMs - startMs > 14 * 24 * 60 * 60 * 1000) {
                      showToast(zh ? '计划周期不能超过 2 周' : 'Duration cannot exceed 2 weeks', 'error');
                    }
                  }
                }
                setForm((f: any) => ({ ...f, scheduled_end: v }));
              }}
              language={language}
              required
            />
          </div>

          {/* Device login exempt */}
          <div className="mt-4 rounded-2xl border border-black/8 bg-black/[0.015] p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs font-semibold text-black/70">{zh ? '设备登录免授权' : 'Device Login Auth Exempt'}</p>
                <p className="text-[11px] text-black/40 mt-1">
                  {zh ? '开启后变更执行时可跳过设备登录时的额外授权检查，与工单审批流程无关。' : 'Enable to exempt device login authorization during execution; this does not skip the change order approval workflow.'}
                </p>
              </div>
              <label className="inline-flex items-center gap-2 rounded-full border border-black/10 bg-white px-3 py-2 text-sm cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={form.authorization_exempt}
                  onChange={(e) => setForm((f: any) => ({
                    ...f,
                    authorization_exempt: e.target.checked,
                  }))}
                  className="h-4 w-4 rounded border border-black/10 text-[#06b6d4] focus:ring-[#06b6d4]"
                />
                <span>{form.authorization_exempt ? (zh ? '已启用' : 'Enabled') : (zh ? '未启用' : 'Disabled')}</span>
              </label>
            </div>
          </div>

          {/* Target Devices */}
          <div className="mt-4">
            <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
              <label className="block text-xs font-semibold text-black/50">{zh ? '目标设备' : 'Target Devices'} <span className="text-rose-500">*</span></label>
              <button
                type="button"
                onClick={() => setShowDevicePicker(true)}
                className="rounded-xl bg-[#06b6d4] px-3 py-2 text-xs font-semibold text-white hover:bg-[#0891b2] transition-all"
              >
                {zh ? '从设备库选择' : 'Pick from inventory'}
              </button>
            </div>
            {form.target_devices.length > 0 && (
              <div className="mt-2 overflow-x-auto rounded-3xl border border-black/10 bg-slate-50">
                <table className="min-w-full text-sm text-left">
                  <thead>
                    <tr className="text-xs text-black/50 uppercase tracking-[0.04em]">
                      <th className="px-3 py-3">{zh ? 'IP地址' : 'IP Address'}</th>
                      <th className="px-3 py-3">{zh ? '设备名称' : 'Device Name'}</th>
                      <th className="px-3 py-3">{zh ? '用户名' : 'Username'}</th>
                      <th className="px-3 py-3">{zh ? '开始/结束' : 'Start / End'}</th>
                      <th className="px-3 py-3">{zh ? '执行人' : 'Executor'}</th>
                      <th className="px-3 py-3">{zh ? '操作' : 'Actions'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {form.target_devices.map((dev: any, i: number) => (
                      <tr key={i} className="border-t border-black/10">
                        <td className="px-3 py-3 text-black/80">{dev.ip_address || '—'}</td>
                        <td className="px-3 py-3 text-black/80">{dev.hostname || '—'}</td>
                        <td className="px-3 py-3 text-black/80">{dev.username || currentUser.username || '—'}</td>
                        <td className="px-3 py-3 text-black/80">{fmtTime(form.scheduled_start)} / {fmtTime(form.scheduled_end)}</td>
                        <td className="px-3 py-3 text-black/80">{currentUser.username || '—'}</td>
                        <td className="px-3 py-3">
                          <button
                            title={zh ? '移除目标设备' : 'Remove target device'}
                            onClick={() => setForm((f: any) => ({ ...f, target_devices: f.target_devices.filter((_: any, j: number) => j !== i) }))}
                            className="text-cyan-400 hover:text-cyan-700"
                          >
                            <X size={14} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Device Picker Modal/Inline Section */}
          {showDevicePicker && (
            <div className="mt-4 rounded-3xl border border-black/10 bg-white p-5 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
                <div>
                  <p className="text-sm font-semibold text-black/75">{zh ? '选择目标设备' : 'Select target devices'}</p>
                  <p className="text-[11px] text-black/40 mt-1">
                    {zh ? '搜索设备库（支持主机名/IP/管理IP/资产标签），选择设备后点击确认添加。' : 'Search inventory by hostname, IP, management IP or asset tag. Select a device and confirm to add.'}
                  </p>
                </div>
                <button type="button" title={zh ? '关闭设备选择器' : 'Close device picker'} onClick={() => { setShowDevicePicker(false); setDeviceKeyword(''); setSelectedInventoryDevice(null); }} className="text-black/50 hover:text-black">
                  <X size={18} />
                </button>
              </div>
              <input
                title={zh ? '搜索设备清单' : 'Search inventory devices'}
                value={deviceKeyword}
                onChange={e => setDeviceKeyword(e.target.value)}
                placeholder={zh ? '搜索主机名 / IP / 管理IP / 资产标签' : 'Search hostname / IP / management IP / asset tag'}
                className="w-full px-3 py-2 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 bg-white text-black"
              />

              <div className="flex justify-between items-center mt-3">
                <p className="text-xs font-semibold text-black/50">{zh ? '搜索结果' : 'Search Results'}</p>
                {deviceOptions.length > 0 && (
                  <button
                    type="button"
                    onClick={() => {
                      const allSelected = deviceOptions.every(dev => selectedInventoryDevices.some(d => d.id === dev.id));
                      if (allSelected) {
                        const idsToRemove = deviceOptions.map(d => d.id);
                        setSelectedInventoryDevices(selectedInventoryDevices.filter(d => !idsToRemove.includes(d.id)));
                      } else {
                        const newDevices = [...selectedInventoryDevices];
                        deviceOptions.forEach(dev => {
                          if (!newDevices.some(d => d.id === dev.id)) {
                            newDevices.push(dev);
                          }
                        });
                        setSelectedInventoryDevices(newDevices);
                      }
                    }}
                    className="text-xs font-semibold text-[#00bceb] hover:text-[#0096bd] transition-colors"
                  >
                    {deviceOptions.every(dev => selectedInventoryDevices.some(d => d.id === dev.id))
                      ? (zh ? '取消全选当前结果' : 'Deselect All Current') 
                      : (zh ? '全选当前结果' : 'Select All Current')}
                  </button>
                )}
              </div>

              <div className="mt-2 grid gap-4 xl:grid-cols-[1fr_250px]">
                <div className="max-h-72 overflow-y-auto border border-black/10 rounded-3xl bg-slate-50">
                  {deviceLoading ? (
                    <div className="px-3 py-3 text-sm text-black/50">{zh ? '搜索中...' : 'Searching...'}</div>
                  ) : deviceOptions.length === 0 ? (
                    <div className="px-3 py-3 text-sm text-black/40">{zh ? '未找到匹配设备，请修改关键词或直接输入目标设备。' : 'No devices found, change search term or add manually.'}</div>
                  ) : (
                    deviceOptions.map((dev) => {
                      const isChecked = selectedInventoryDevices.some(d => d.id === dev.id);
                      return (
                        <button
                          type="button"
                          key={`${dev.id}-${dev.ip_address}`}
                          onClick={() => {
                            if (isChecked) {
                              setSelectedInventoryDevices(selectedInventoryDevices.filter(d => d.id !== dev.id));
                            } else {
                              setSelectedInventoryDevices([...selectedInventoryDevices, dev]);
                            }
                          }}
                          className={`w-full px-4 py-3 text-left text-sm text-black/80 hover:bg-[#00bceb]/8 border-b last:border-b-0 border-black/10 transition-all ${isChecked ? 'bg-[#00bceb]/15' : ''}`}
                        >
                          <div className="flex items-center gap-3">
                            <input
                              type="checkbox"
                              checked={isChecked}
                              readOnly
                              className="w-4 h-4 rounded text-[#06b6d4] focus:ring-[#06b6d4] border-black/20 shrink-0"
                            />
                            <div>
                              <div className="font-semibold text-sm text-black/85">{dev.hostname || (zh ? '未命名设备' : 'Unnamed')}</div>
                              <div className="text-[11px] text-black/45 mt-0.5">
                                {dev.asset_tag ? `${dev.asset_tag} · ` : ''}{dev.ip_address || '—'}
                              </div>
                            </div>
                          </div>
                        </button>
                      );
                    })
                  )}
                </div>

                <div className="rounded-3xl border border-black/10 bg-slate-50 p-4 flex flex-col justify-between">
                  <div>
                    <p className="text-xs font-semibold text-black/50 mb-2">{zh ? '已勾选设备' : 'Selected devices'}</p>
                    {selectedInventoryDevices.length > 0 ? (
                      <div className="space-y-2 max-h-52 overflow-y-auto pr-1">
                        {selectedInventoryDevices.map((dev) => (
                          <div key={dev.id} className="flex justify-between items-center rounded-xl border border-black/5 bg-white p-2.5">
                            <div>
                              <div className="font-medium text-xs text-black/80">{dev.hostname || (zh ? '未命名' : 'Unnamed')}</div>
                              <div className="text-[10px] text-black/40 mt-0.5">{dev.ip_address || '—'}</div>
                            </div>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                setSelectedInventoryDevices(selectedInventoryDevices.filter(d => d.id !== dev.id));
                              }}
                              className="p-1 hover:bg-black/5 rounded-lg transition-colors text-black/30 hover:text-rose-500"
                            >
                              <X size={14} />
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="rounded-2xl border border-dashed border-black/10 bg-white/70 p-4 text-[11px] text-black/45">
                        {zh ? '请勾选左侧列表中的一个或多个设备以确认添加到工单。' : 'Check one or more devices to add to the order.'}
                      </div>
                    )}
                  </div>
                  {selectedInventoryDevices.length > 0 && (
                    <div className="mt-3">
                      <button
                        type="button"
                        onClick={confirmSelectedDevice}
                        className="w-full rounded-xl bg-[#06b6d4] px-3 py-2 text-sm font-semibold text-white hover:bg-[#0891b2] transition-all shadow-md shadow-[#06b6d4]/20"
                      >
                        {zh ? `确认添加 (${selectedInventoryDevices.length})` : `Add Selected (${selectedInventoryDevices.length})`}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Commands block */}
          <div className="rounded-2xl border border-black/8 bg-black/[0.015] p-4">
            <div className="flex items-center justify-between gap-3 mb-3">
              <div>
                <label className="block text-xs font-semibold text-black/50">{zh ? '命令来源' : 'Command Source'}</label>
                <p className="mt-1 text-[11px] text-black/40">{zh ? '可继续使用手工输入，也可以切换为可参数化的变更模板。' : 'Keep manual commands or switch to a parameterized scenario template.'}</p>
              </div>
              <div className="inline-flex rounded-xl bg-white p-1 ring-1 ring-black/8">
                <button
                  type="button"
                  onClick={() => setCommandMode('manual')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${commandMode === 'manual' ? 'bg-[#00bceb] text-white shadow-sm' : 'text-black/55 hover:bg-black/[0.04]'}`}
                >
                  {zh ? '手工命令' : 'Manual'}
                </button>
                <button
                  type="button"
                  onClick={() => setCommandMode('template')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${commandMode === 'template' ? 'bg-[#00bceb] text-white shadow-sm' : 'text-black/55 hover:bg-black/[0.04]'}`}
                >
                  {zh ? '模板场景' : 'Template'}
                </button>
              </div>
            </div>

            {commandMode === 'template' ? (
              <div className="space-y-4">
                <div className="grid grid-cols-1 gap-4">
                  <div>
                    <label className="block text-xs font-semibold text-black/50 mb-1.5">{zh ? '变更模板场景' : 'Scenario Template'}</label>
                    <div ref={dropdownRef} className="relative w-full">
                      <div
                        className="w-full px-3 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 bg-white flex items-center justify-between cursor-pointer select-none"
                        onClick={() => {
                          setIsDropdownOpen(!isDropdownOpen);
                          if (!isDropdownOpen) {
                            setScenarioSearch('');
                          }
                        }}
                      >
                        <span className="text-black/85 truncate">
                          {selectedScenario
                            ? `${selectedScenario.icon ? `${selectedScenario.icon} ` : ''}${zh ? (selectedScenario.name_zh || selectedScenario.name) : selectedScenario.name}`
                            : (zh ? '请选择一个配置模板' : 'Select a config template')}
                        </span>
                        <ChevronDown className="w-4 h-4 text-black/45 shrink-0 transition-transform duration-200" style={{ transform: isDropdownOpen ? 'rotate(180deg)' : 'none' }} />
                      </div>

                      {isDropdownOpen && (
                        <div className="absolute z-50 w-full mt-1 bg-white border border-black/10 rounded-xl shadow-lg max-h-60 overflow-hidden flex flex-col">
                          {/* Search Input */}
                          <div className="p-2 border-b border-black/5 flex items-center gap-2 bg-black/[0.01]">
                            <Search className="w-3.5 h-3.5 text-black/40 shrink-0" />
                            <input
                              type="text"
                              value={scenarioSearch}
                              onChange={(e) => setScenarioSearch(e.target.value)}
                              placeholder={zh ? '搜索模板场景...' : 'Search templates...'}
                              className="w-full text-xs outline-none bg-transparent py-1 border-none focus:ring-0 text-black/80"
                              onClick={(e) => e.stopPropagation()}
                              autoFocus
                            />
                            {scenarioSearch && (
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setScenarioSearch('');
                                }}
                                className="text-black/40 hover:text-black/60"
                              >
                                <X className="w-3.5 h-3.5" />
                              </button>
                            )}
                          </div>

                          {/* Options List */}
                          <div className="overflow-y-auto flex-1 max-h-48 py-1">
                            {filteredScenarioOptions.length > 0 ? (
                              filteredScenarioOptions.map((scenario) => {
                                const isSelected = scenario.id === selectedScenarioId;
                                return (
                                  <div
                                    key={scenario.id}
                                    onClick={() => {
                                      setSelectedScenarioId(scenario.id);
                                      setIsDropdownOpen(false);
                                      setScenarioSearch('');
                                    }}
                                    className={`px-3 py-2 text-xs flex items-center justify-between cursor-pointer select-none transition-colors ${
                                      isSelected
                                        ? 'bg-[#00bceb]/10 text-[#00bceb] font-semibold'
                                        : 'text-black/80 hover:bg-black/[0.03]'
                                    }`}
                                  >
                                    <div className="truncate flex items-center gap-1.5">
                                      <span className="shrink-0">{scenario.icon || '📄'}</span>
                                      <div className="truncate">
                                        <span className="block truncate">{zh ? (scenario.name_zh || scenario.name) : scenario.name}</span>
                                        {scenario.category && (
                                          <span className="block text-[10px] text-black/40 font-normal truncate mt-0.5">{scenario.category}</span>
                                        )}
                                      </div>
                                    </div>
                                    {isSelected && <CheckCircle2 className="w-3.5 h-3.5 text-[#00bceb] shrink-0" />}
                                  </div>
                                );
                              })
                            ) : (
                              <div className="px-3 py-4 text-xs text-black/40 text-center select-none">
                                {zh ? '无匹配的模板场景' : 'No templates match'}
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                  
                  {selectedScenario && selectedScenarioPlatforms.length > 1 && (
                    <div>
                      <label className="block text-xs font-semibold text-black/50 mb-1.5">{zh ? '适配平台' : 'Target Platform'}</label>
                      <div className="flex flex-wrap gap-2">
                        {selectedScenarioPlatforms.map((p) => (
                          <button
                            key={p}
                            type="button"
                            onClick={() => setSelectedScenarioPlatform(p)}
                            className={`px-3 py-1.5 rounded-xl text-xs font-medium transition-all ${selectedScenarioPlatform === p ? 'bg-[#00bceb] text-white shadow-sm' : 'bg-white text-black/55 ring-1 ring-black/8 hover:bg-black/[0.02]'}`}
                          >
                            {platformLabel(p)}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {selectedScenario && (
                  <div className="rounded-2xl border border-[#00bceb]/15 bg-[#00bceb]/[0.04] px-4 py-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-black/80">{zh ? (selectedScenario.name_zh || selectedScenario.name) : selectedScenario.name}</p>
                        <p className="mt-1 text-xs text-black/45">{zh ? (selectedScenario.description_zh || selectedScenario.description || '') : (selectedScenario.description || '')}</p>
                      </div>
                      <span className={`shrink-0 rounded-full px-2.5 py-1 text-[10px] font-semibold ${RISK_META[selectedScenario.risk || form.risk_level]?.color || 'text-slate-600'} bg-white ring-1 ring-black/8`}>
                        {riskLabel(selectedScenario.risk || form.risk_level, language)}
                      </span>
                    </div>
                  </div>
                )}

                {selectedScenario && (
                  <div className="space-y-4">
                    {selectedScenarioVariables.length > 0 ? (
                      <div className="grid grid-cols-2 gap-3">
                        {selectedScenarioVariables.map((variable) => {
                          const hint = variable.platform_hints?.[selectedScenarioPlatform] || variable.placeholder || '';
                          const commonClass = 'w-full px-3 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 bg-white text-black';
                          return (
                            <div key={variable.key} className={variable.type === 'textarea' ? 'col-span-2' : ''}>
                              <label className="block text-xs font-semibold text-black/50 mb-1.5">
                                {variableLabel(variable, language)}
                                {variable.required && <span className="text-rose-500 ml-1">*</span>}
                              </label>
                              {variable.type === 'textarea' ? (
                                <textarea
                                  title={variableLabel(variable, language)}
                                  value={templateVariables[variable.key] || ''}
                                  onChange={(e) => assignTemplateVariable(variable.key, e.target.value)}
                                  placeholder={hint}
                                  rows={3}
                                  className={`${commonClass} resize-none font-mono text-xs`}
                                />
                              ) : variable.type === 'select' ? (
                                <select
                                  title={variableLabel(variable, language)}
                                  value={templateVariables[variable.key] || ''}
                                  onChange={(e) => assignTemplateVariable(variable.key, e.target.value)}
                                  className={`${commonClass} bg-white`}
                                >
                                  <option value="">{zh ? '请选择' : 'Select'}</option>
                                  {(variable.options || []).map((option) => (
                                    <option key={option} value={option}>{option}</option>
                                  ))}
                                </select>
                              ) : (
                                <input
                                  type={variable.type === 'number' ? 'number' : 'text'}
                                  title={variableLabel(variable, language)}
                                  value={templateVariables[variable.key] || ''}
                                  onChange={(e) => assignTemplateVariable(variable.key, e.target.value)}
                                  placeholder={hint}
                                  className={commonClass}
                                />
                              )}
                              {(() => {
                                const helpText = getVariableHelpText(variable.key, selectedScenarioPlatform, zh);
                                if (helpText) {
                                  return (
                                    <p className="mt-1 text-[11px] text-black/40 font-medium leading-normal">
                                      {helpText}
                                    </p>
                                  );
                                }
                                return null;
                              })()}
                            </div>
                          );
                        })}
                      </div>
                    ) : selectedScenario.source_kind === 'config_template' && (
                      <div className="px-4 py-3 bg-blue-50/50 border border-blue-100 rounded-xl text-xs text-blue-600 flex items-start gap-2">
                        <AlertTriangle className="w-3.5 h-3.5 mt-0.5" />
                        <div>
                          <p className="font-medium mb-1">{zh ? '未检测到变量' : 'No variables detected'}</p>
                          <p className="opacity-80 leading-relaxed">
                            {zh 
                              ? '该模板目前为静态配置。如需添加交互入参，请在模板中使用 {{ 变量名 }} 语法。' 
                              : 'This template is currently static. Use {{ variable_name }} syntax in the template to add dynamic parameters.'}
                          </p>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {templateMissingRequired.length > 0 && (
                  <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    className="rounded-xl bg-gradient-to-r from-amber-500/5 to-orange-500/5 border border-amber-500/20 shadow-sm shadow-amber-500/5 p-3.5 text-xs text-amber-800 flex items-start gap-3 backdrop-blur-sm"
                  >
                    <div className="p-1.5 rounded-lg bg-amber-500/10 text-amber-600 shrink-0 mt-0.5">
                      <AlertTriangle size={14} className="animate-pulse" />
                    </div>
                    <div className="flex-1 space-y-1.5">
                      <p className="font-semibold text-amber-900 leading-none">
                        {zh ? '待补充必填变量' : 'Missing Required Variables'}
                      </p>
                      <p className="text-amber-700/80 leading-relaxed text-[11px]">
                        {zh ? '请在上方表单中填写以下必填变量的值，否则无法进行下一步操作：' : 'Please fill in values for the following required variables above to proceed:'}
                      </p>
                      <div className="flex flex-wrap gap-1.5 pt-1">
                        {templateMissingRequired.map((varName, idx) => (
                          <span 
                            key={idx} 
                            className="inline-flex items-center px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-800 border border-amber-500/20 font-medium font-mono text-[10px]"
                          >
                            {varName}
                          </span>
                        ))}
                      </div>
                    </div>
                  </motion.div>
                )}

                {templatePreviewError && (
                  <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="rounded-xl bg-gradient-to-r from-rose-500/5 to-pink-500/5 border border-rose-500/20 shadow-sm shadow-rose-500/5 p-3.5 text-xs text-rose-800 flex items-start gap-3 backdrop-blur-sm"
                  >
                    <div className="p-1.5 rounded-lg bg-rose-500/10 text-rose-600 shrink-0 mt-0.5">
                      <XCircle size={14} />
                    </div>
                    <div className="flex-1 space-y-1.5">
                      <p className="font-semibold text-rose-900 leading-none">
                        {zh ? '模板渲染失败' : 'Template Rendering Failed'}
                      </p>
                      <pre className="p-2.5 rounded-lg bg-rose-500/5 border border-rose-500/10 text-rose-700 font-mono text-[10px] whitespace-pre-wrap break-all leading-normal mt-1">
                        {templatePreviewError}
                      </pre>
                    </div>
                  </motion.div>
                )}

                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={runPrecheck}
                    disabled={precheckLoading || !selectedScenarioId}
                    className="px-4 py-2 bg-gradient-to-r from-blue-500 to-cyan-500 text-white rounded-xl text-xs font-semibold hover:from-blue-600 hover:to-cyan-600 transition-all shadow-md shadow-blue-500/10 flex items-center gap-1.5 disabled:opacity-50"
                  >
                    {precheckLoading ? <RefreshCw size={12} className="animate-spin" /> : <Shield size={12} />}
                    {zh ? '执行预检查' : 'Run Pre-check'}
                  </button>
                </div>

                {precheckErrors.length > 0 && (
                  <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="rounded-xl bg-gradient-to-r from-rose-500/5 to-pink-500/5 border border-rose-500/20 shadow-sm shadow-rose-500/5 p-3.5 text-xs text-rose-800 space-y-2.5 backdrop-blur-sm"
                  >
                    <div className="flex items-start gap-3">
                      <div className="p-1.5 rounded-lg bg-rose-500/10 text-rose-600 shrink-0">
                        <XCircle size={14} />
                      </div>
                      <div className="flex-1 pt-0.5">
                        <p className="font-semibold text-rose-900 leading-none">
                          {zh ? '参数校验或模板错误' : 'Parameter Validation or Template Errors'}
                        </p>
                        <p className="text-rose-700/80 text-[11px] mt-1">
                          {zh ? '预检查未通过，请检查并修正以下问题：' : 'Pre-check failed. Please check and correct the following issues:'}
                        </p>
                      </div>
                    </div>
                    <ul className="space-y-1.5 pl-9">
                      {precheckErrors.map((err, i) => (
                        <li key={i} className="flex items-start gap-2 text-rose-700 leading-relaxed font-mono text-[11px]">
                          <span className="w-1.5 h-1.5 rounded-full bg-rose-500/40 shrink-0 mt-1.5" />
                          <span className="break-all">{err}</span>
                        </li>
                      ))}
                    </ul>
                  </motion.div>
                )}

                {precheckSuccess && (
                  <motion.div
                    initial={{ opacity: 0, scale: 0.98 }}
                    animate={{ opacity: 1, scale: 1 }}
                    className="rounded-xl bg-gradient-to-r from-emerald-500/5 to-teal-500/5 border border-emerald-500/20 shadow-sm shadow-emerald-500/5 p-3.5 text-xs text-emerald-800 flex items-start gap-3 backdrop-blur-sm"
                  >
                    <div className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-600 shrink-0 mt-0.5">
                      <CheckCircle2 size={14} />
                    </div>
                    <div className="flex-1 space-y-1">
                      <p className="font-semibold text-emerald-900 leading-none">
                        {zh ? '预检查成功' : 'Pre-check Successful'}
                      </p>
                      <p className="text-emerald-700/90 leading-relaxed text-[11px] mt-1">
                        {zh ? '所有参数校验均已通过，且已成功生成对应的可执行命令。' : 'All parameters have passed validation, and execution commands were generated successfully.'}
                      </p>
                    </div>
                  </motion.div>
                )}

                <div className="grid grid-cols-2 gap-3">
                  {([
                    { key: 'pre_check', title: zh ? '实施前检查' : 'Pre-check', tone: 'text-cyan-300' },
                    { key: 'execute', title: zh ? '执行命令' : 'Execute', tone: 'text-emerald-300' },
                    { key: 'post_check', title: zh ? '实施后检查' : 'Post-check', tone: 'text-amber-300' },
                    { key: 'rollback', title: zh ? '回退命令' : 'Rollback', tone: 'text-rose-300' },
                  ] as Array<{ key: keyof ScenarioPhasePreview; title: string; tone: string }>).map((section) => {
                    const commands = effectivePreview?.[section.key] || [];
                    return (
                      <div key={section.key} className="rounded-2xl border border-black/8 bg-white p-3">
                        <div className="flex items-center justify-between gap-2 mb-2">
                          <p className="text-[10px] font-semibold uppercase tracking-wider text-black/35">{section.title}</p>
                          {templatePreviewLoading && section.key === 'execute' && <RefreshCw size={12} className="animate-spin text-black/30" />}
                        </div>
                        <div className={`rounded-xl bg-slate-900 p-3 font-mono text-xs whitespace-pre-wrap break-all ${section.tone} max-h-40 overflow-y-auto`}>
                          {commands.length > 0 ? commands.map((cmd, index) => <div key={`${section.key}-${index}`}>{index + 1}. {cmd}</div>) : <div className="text-slate-500">{zh ? '暂无内容' : 'No commands'}</div>}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-black/50 mb-1.5">{zh ? '执行命令' : 'Commands'} <span className="text-rose-500">*</span></label>
                  <div className="flex gap-2">
                    <input
                      value={commandInput}
                      onChange={e => setCommandInput(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addCommand(); } }}
                      placeholder={zh ? '输入命令后按 Enter 添加' : 'Type command and press Enter'}
                      className="flex-1 px-3 py-2 text-sm font-mono border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 bg-white text-black"
                    />
                    <button type="button" title={zh ? '添加命令' : 'Add command'} onClick={addCommand} className="px-3 py-2 rounded-xl bg-[#00bceb]/10 text-[#00bceb] text-sm font-medium hover:bg-[#00bceb]/18 transition-all">
                      <Plus size={15} />
                    </button>
                  </div>
                  {form.commands.length > 0 && (
                    <div className="mt-2 bg-slate-900 rounded-xl p-3 font-mono text-xs text-emerald-400 leading-relaxed max-h-28 overflow-y-auto">
                      {form.commands.map((cmd: string, i: number) => (
                        <div key={i} className="flex items-center group">
                          <span className="text-slate-500 select-none mr-2 w-4 text-right">{i + 1}</span>
                          <span className="flex-1">{cmd}</span>
                          <button
                            type="button"
                            title={zh ? '移除命令' : 'Remove command'}
                            onClick={() => setForm((f: any) => ({ ...f, commands: f.commands.filter((_: any, j: number) => j !== i) }))}
                            className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-rose-400 ml-2 transition-opacity"
                          >
                            <X size={11} />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div>
                  <label className="block text-xs font-semibold text-black/50 mb-1.5">{zh ? '回退方案' : 'Rollback Plan'} <span className="text-rose-500">*</span></label>
                  <textarea
                    value={form.rollback_plan}
                    onChange={e => setForm((f: any) => ({ ...f, rollback_plan: e.target.value }))}
                    placeholder={zh ? '描述失败时的回退步骤...' : 'Describe rollback steps in case of failure...'}
                    rows={2}
                    className="w-full px-4 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 focus:ring-2 focus:ring-[#00bceb]/10 transition-all resize-none"
                  />
                </div>
              </div>
            )}
          </div>

          {/* ── 变更控制表 (Control Sheet) ── */}
          {FEATURE_CONTROL_SHEET && (
            <div className="rounded-2xl border border-black/8 bg-black/[0.015] overflow-hidden">
              {/* Collapsible header */}
              <button
                type="button"
                onClick={() => setShowControlSheet(v => !v)}
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-black/[0.02] transition-colors"
              >
                <div className="flex items-center gap-2.5">
                  <ClipboardCheck size={15} className="text-[#00bceb]" />
                  <span className="text-xs font-semibold text-black/70">{zh ? '变更控制表' : 'Change Control Sheet'}</span>
                  <span className="text-[10px] text-black/35 font-medium px-1.5 py-0.5 bg-black/[0.04] rounded-md">
                    {zh ? '可选' : 'Optional'}
                  </span>
                </div>
                <ChevronDown size={14} className={`text-black/40 transition-transform ${showControlSheet ? 'rotate-180' : ''}`} />
              </button>

              {/* Collapsible body */}
              {showControlSheet && (
                <div className="px-4 pb-4 pt-1 space-y-4 border-t border-black/5">
                  {/* 1. change_time — time window picker */}
                  <div>
                    <label className="block text-xs font-semibold text-black/50 mb-1.5">
                      {zh ? '变更时间窗口' : 'Change Time Window'}
                    </label>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-[11px] text-black/40 mb-1">{zh ? '开始时间' : 'Start'}</label>
                        <input
                          type="datetime-local"
                          value={form.control_sheet.change_time_start}
                          onChange={e => setForm((f: any) => ({ ...f, control_sheet: { ...f.control_sheet, change_time_start: e.target.value } }))}
                          className="w-full px-3 py-2 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 focus:ring-2 focus:ring-[#00bceb]/10 transition-all bg-white text-black"
                        />
                      </div>
                      <div>
                        <label className="block text-[11px] text-black/40 mb-1">{zh ? '结束时间' : 'End'}</label>
                        <input
                          type="datetime-local"
                          value={form.control_sheet.change_time_end}
                          onChange={e => setForm((f: any) => ({ ...f, control_sheet: { ...f.control_sheet, change_time_end: e.target.value } }))}
                          className="w-full px-3 py-2 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 focus:ring-2 focus:ring-[#00bceb]/10 transition-all bg-white text-black"
                        />
                      </div>
                    </div>
                  </div>

                  {/* 2 & 3. implementer + co_reviewer — user pickers */}
                  <div className="grid grid-cols-2 gap-4">
                    {/* implementer */}
                    <div>
                      <label className="block text-xs font-semibold text-black/50 mb-1.5">
                        {zh ? '实施人' : 'Implementer'}
                      </label>
                      <select
                        title={zh ? '选择实施人' : 'Select implementer'}
                        value={form.control_sheet.implementer_id}
                        onChange={e => {
                          const u = users.find(u => String(u.id) === e.target.value);
                          setForm((f: any) => ({
                            ...f,
                            control_sheet: {
                              ...f.control_sheet,
                              implementer_id: e.target.value,
                              implementer_username: u?.username || '',
                            },
                          }));
                        }}
                        className="w-full px-3 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 bg-white text-black"
                      >
                        <option value="">{zh ? '请选择实施人' : 'Select implementer'}</option>
                        {users.filter(u => u.role !== 'Viewer').map(u => (
                          <option key={u.id} value={String(u.id)}>
                            {u.username}{u.group_name ? ` · ${u.group_name}` : ''}
                          </option>
                        ))}
                      </select>
                    </div>
                    {/* co_reviewer */}
                    <div>
                      <label className="block text-xs font-semibold text-black/50 mb-1.5">
                        {zh ? '协同审核人' : 'Co-Reviewer'}
                      </label>
                      <select
                        title={zh ? '选择协同审核人' : 'Select co-reviewer'}
                        value={form.control_sheet.co_reviewer_id}
                        onChange={e => {
                          const u = users.find(u => String(u.id) === e.target.value);
                          setForm((f: any) => ({
                            ...f,
                            control_sheet: {
                              ...f.control_sheet,
                              co_reviewer_id: e.target.value,
                              co_reviewer_username: u?.username || '',
                            },
                          }));
                        }}
                        className="w-full px-3 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 bg-white text-black"
                      >
                        <option value="">{zh ? '请选择协同审核人' : 'Select co-reviewer'}</option>
                        {users.filter(u => u.role !== 'Viewer').map(u => (
                          <option key={u.id} value={String(u.id)}>
                            {u.username}{u.group_name ? ` · ${u.group_name}` : ''}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {/* 4. device_ips — IP list */}
                  <div>
                    <label className="block text-xs font-semibold text-black/50 mb-1.5">
                      {zh ? '涉及设备 IP（每行或逗号分隔）' : 'Device IPs (one per line or comma-separated)'}
                    </label>
                    <textarea
                      value={form.control_sheet.device_ips}
                      onChange={e => setForm((f: any) => ({ ...f, control_sheet: { ...f.control_sheet, device_ips: e.target.value } }))}
                      placeholder={zh ? '10.0.0.1\n10.0.0.2\n或 10.0.0.1, 10.0.0.2' : '10.0.0.1\n10.0.0.2\nor 10.0.0.1, 10.0.0.2'}
                      rows={3}
                      className="w-full px-4 py-2.5 text-sm font-mono border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 focus:ring-2 focus:ring-[#00bceb]/10 transition-all resize-none"
                    />
                  </div>

                  {/* 5–8. Four multi-line text blocks */}
                  <div className="grid grid-cols-2 gap-4">
                    {/* pre_check */}
                    <div>
                      <label className="block text-xs font-semibold text-black/50 mb-1.5">
                        {zh ? '变更前检查' : 'Pre-Check'}
                      </label>
                      <textarea
                        value={form.control_sheet.pre_check}
                        onChange={e => setForm((f: any) => ({ ...f, control_sheet: { ...f.control_sheet, pre_check: e.target.value } }))}
                        placeholder={zh ? '描述变更前需要执行的检查步骤...' : 'Describe pre-change verification steps...'}
                        rows={4}
                        className="w-full px-4 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 focus:ring-2 focus:ring-[#00bceb]/10 transition-all resize-none"
                      />
                    </div>
                    {/* execution */}
                    <div>
                      <label className="block text-xs font-semibold text-black/50 mb-1.5">
                        {zh ? '实施步骤' : 'Execution Steps'}
                      </label>
                      <textarea
                        value={form.control_sheet.execution}
                        onChange={e => setForm((f: any) => ({ ...f, control_sheet: { ...f.control_sheet, execution: e.target.value } }))}
                        placeholder={zh ? '描述具体的实施操作步骤...' : 'Describe the execution steps in detail...'}
                        rows={4}
                        className="w-full px-4 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 focus:ring-2 focus:ring-[#00bceb]/10 transition-all resize-none"
                      />
                    </div>
                    {/* post_verify */}
                    <div>
                      <label className="block text-xs font-semibold text-black/50 mb-1.5">
                        {zh ? '变更后验证' : 'Post-Verify'}
                      </label>
                      <textarea
                        value={form.control_sheet.post_verify}
                        onChange={e => setForm((f: any) => ({ ...f, control_sheet: { ...f.control_sheet, post_verify: e.target.value } }))}
                        placeholder={zh ? '描述变更后的验证方法和预期结果...' : 'Describe post-change verification and expected results...'}
                        rows={4}
                        className="w-full px-4 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 focus:ring-2 focus:ring-[#00bceb]/10 transition-all resize-none"
                      />
                    </div>
                    {/* business_verify */}
                    <div>
                      <label className="block text-xs font-semibold text-black/50 mb-1.5">
                        {zh ? '业务验证' : 'Business Verify'}
                      </label>
                      <textarea
                        value={form.control_sheet.business_verify}
                        onChange={e => setForm((f: any) => ({ ...f, control_sheet: { ...f.control_sheet, business_verify: e.target.value } }))}
                        placeholder={zh ? '描述业务层面的验证方法和预期结果...' : 'Describe business-level verification and expected results...'}
                        rows={4}
                        className="w-full px-4 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 focus:ring-2 focus:ring-[#00bceb]/10 transition-all resize-none"
                      />
                    </div>
                  </div>

                  {/* 9. rollback_plan — multi-line text block */}
                  <div>
                    <label className="block text-xs font-semibold text-black/50 mb-1.5">
                      {zh ? '回退方案（控制表）' : 'Rollback Plan (Control Sheet)'}
                    </label>
                    <textarea
                      value={form.control_sheet.rollback_plan}
                      onChange={e => setForm((f: any) => ({ ...f, control_sheet: { ...f.control_sheet, rollback_plan: e.target.value } }))}
                      placeholder={zh ? '描述变更失败时的回退步骤和恢复方案...' : 'Describe rollback steps and recovery plan if the change fails...'}
                      rows={4}
                      className="w-full px-4 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 focus:ring-2 focus:ring-[#00bceb]/10 transition-all resize-none"
                    />
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Modal footer */}
        <div className="px-6 py-4 border-t border-black/5 bg-black/[0.01] flex flex-wrap items-center justify-end gap-3">
          <button type="button" onClick={() => closeEditor()} className="px-4 py-2.5 rounded-xl text-sm font-medium text-black/50 hover:bg-black/5 transition-all">
            {zh ? '取消' : 'Cancel'}
          </button>
          <button
            type="button"
            onClick={handleSaveDraft}
            disabled={saving || !form.title.trim()}
            className="px-4 py-2.5 rounded-xl bg-white text-black/70 border border-black/10 text-sm font-medium hover:bg-black/5 transition-all disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
          >
            <Save size={14} />
            {zh ? '保存草稿' : 'Save Draft'}
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || !form.title.trim() || (commandMode === 'template' && !selectedScenarioId)}
            className="px-5 py-2.5 bg-[#00bceb] text-white rounded-xl text-sm font-medium flex items-center gap-2 hover:bg-[#0096bd] transition-all shadow-lg shadow-[#00bceb]/20 disabled:opacity-40 disabled:cursor-not-allowed"
            title={commandMode === 'template' && !selectedScenarioId ? (zh ? '请先选择场景并填写必填变量' : 'Please select a scenario and fill in all required variables') : undefined}
          >
            {saving ? <RefreshCw size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
            {editingOrder ? (zh ? '提交' : 'Submit') : (zh ? '创建工单' : 'Create Order')}
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
};
