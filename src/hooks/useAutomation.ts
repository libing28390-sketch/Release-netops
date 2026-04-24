import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import * as XLSX from 'xlsx';
import type { Job, ScheduledTask, Script, ConfigTemplate, SessionUser, Device } from '../types';

interface UseAutomationProps {
  currentUser: SessionUser;
  language: string;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  navigate: (path: string) => void;
  setSelectedDevice: (device: any) => void;
  devices: any[];
  selectedDevice: any;
  activeTab: string;
  automationPage: string;
}

export const useAutomation = ({ 
  currentUser, language, showToast, navigate, 
  setSelectedDevice,
  devices, selectedDevice,
  activeTab, automationPage
}: UseAutomationProps) => {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [scheduledTasks, setScheduledTasks] = useState<ScheduledTask[]>([]);
  const [scenarios, setScenarios] = useState<any[]>([]);
  const [platforms, setPlatforms] = useState<Record<string, any>>({});
  const [playbookExecutions, setPlaybookExecutions] = useState<any[]>([]);
  
  const [scripts, setScripts] = useState<Script[]>([]);
  const [selectedScript, setSelectedScript] = useState<Script | null>(null);
  const [selectedAutomationTemplate, setSelectedAutomationTemplate] = useState<ConfigTemplate | null>(null);
  const [editedScriptContent, setEditedScriptContent] = useState<string>('');
  
  const [customCommand, setCustomCommand] = useState('');
  const [customCommandMode, setCustomCommandMode] = useState<'query' | 'config'>('query');
  const [configReason, setConfigReason] = useState('');
  
  // Config approval flow
  const [approverUsername, setApproverUsername] = useState('');
  const [approvalCode, setApprovalCode] = useState('');
  const [approvalToken, setApprovalToken] = useState('');
  const [approvalStatus, setApprovalStatus] = useState<'idle' | 'sending' | 'sent' | 'verified' | 'error'>('idle');
  const [approvalError, setApprovalError] = useState('');
  const [approvalCountdown, setApprovalCountdown] = useState(0);
  const [scriptParams, setScriptParams] = useState<Record<string, string>>({});

  // Command favorites
  const [commandFavorites, setCommandFavorites] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem('cmdFavorites') || '[]'); } catch { return []; }
  });
  const [showFavorites, setShowFavorites] = useState(false);
  
  // Script variable substitution
  const [scriptVars, setScriptVars] = useState<Record<string, string>>({});

  // Batch execution
  const [batchMode, setBatchMode] = useState(false);
  const [batchDeviceIds, setBatchDeviceIds] = useState<string[]>([]);
  const [batchResults, setBatchResults] = useState<{deviceId: string; hostname: string; status: 'pending'|'running'|'success'|'failed'; output?: string}[]>([]);
  const [isBatchRunning, setIsBatchRunning] = useState(false);
  
  // Dry-run mode
  const [dryRun, setDryRun] = useState(false);

  // Quick Query
  const [quickQueryOutput, setQuickQueryOutput] = useState<string>('');
  const [quickQueryRunning, setQuickQueryRunning] = useState(false);
  const [quickQueryLabel, setQuickQueryLabel] = useState('');
  const [quickQueryStructured, setQuickQueryStructured] = useState<any | null>(null);
  const [quickQueryView, setQuickQueryView] = useState<'terminal' | 'table'>('terminal');
  const [quickQueryMaximized, setQuickQueryMaximized] = useState(false);
  const [quickQueryCommands, setQuickQueryCommands] = useState<string[]>([]);

  // Execution states
  const [selectedScenario, setSelectedScenario] = useState<any>(null);
  const [playbookVars, setPlaybookVars] = useState<Record<string, string>>({});
  const [playbookDeviceIds, setPlaybookDeviceIds] = useState<string[]>([]);
  const [playbookPlatform, setPlaybookPlatform] = useState<string>('cisco_ios');
  const [playbookDryRun, setPlaybookDryRun] = useState(true);
  const [playbookConcurrency, setPlaybookConcurrency] = useState(1);
  const [playbookPreview, setPlaybookPreview] = useState<any>(null);
  
  // Quick execution states
  const [quickPlaybookScenario, setQuickPlaybookScenario] = useState<any>(null);
  const [quickPlaybookVars, setQuickPlaybookVars] = useState<Record<string, string>>({});
  const [quickPlaybookPlatform, setQuickPlaybookPlatform] = useState<string>('cisco_ios');
  const [quickPlaybookDryRun, setQuickPlaybookDryRun] = useState(true);
  const [quickPlaybookConcurrency, setQuickPlaybookConcurrency] = useState(1);
  const [quickPlaybookPreview, setQuickPlaybookPreview] = useState<any>(null);
  const [quickRiskConfirmed, setQuickRiskConfirmed] = useState(false);
  const [isQuickPlaybookRunning, setIsQuickPlaybookRunning] = useState(false);
  const [quickExecutionResult, setQuickExecutionResult] = useState<any>(null);
  
  // Real-time feedback
  const [wsMessages, setWsMessages] = useState<any[]>([]);
  const [deviceStatusMap, setDeviceStatusMap] = useState<Record<string, any>>({});
  const [wsCompleteMsg, setWsCompleteMsg] = useState<any>(null);
  const [activeExecutionId, setActiveExecutionId] = useState<string | null>(null);
  const [executionStatus, setExecutionStatus] = useState<string>('idle');
  const [automationSearch, setAutomationSearch] = useState('');
  const [scenarioSearch, setScenarioSearch] = useState('');
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [showCustomCommandModal, setShowCustomCommandModal] = useState(false);
  const [showCmdPreviewModal, setShowCmdPreviewModal] = useState(false);
  const [isAutomationTaskRunning, setIsAutomationTaskRunning] = useState(false); // Used as a loading state in runTask
  const [showDiff, setShowDiff] = useState(false); // Needed for runTask closure
  const [currentDiff, setCurrentDiff] = useState({ before: '', after: '' });

  const customCommandVars = useMemo(() => {
    const matches = [...customCommand.matchAll(/\{\{\s*([\w.-]+)\s*\}\}/g)];
    return [...new Set(matches.map(m => m[1]))];
  }, [customCommand]);
  
  const wsRef = useRef<WebSocket | null>(null);

  const extractVars = useCallback((text: string): string[] => {
    if (!text) return [];
    const matches = [...text.matchAll(/\{\{\s*([\w.-]+)\s*\}\}/g)];
    return [...new Set(matches.map((m) => m[1]))];
  }, []);

  const splitLines = useCallback((text: string): string[] => {
    return (text || '').split('\n').map(l => l.trim()).filter(Boolean);
  }, []);

  const applyScriptVars = useCallback((text: string) => {
    return text.replace(/\{\{\s*([\w.-]+)\s*\}\}/g, (_, key) => scriptVars[key] ?? `{{${key}}}`);
  }, [scriptVars]);

  const formatQuickQueryRawOutput = useCallback((payload: any) => {
    const category = Array.isArray(payload?.categories) ? payload.categories[0] : null;
    if (!category) return language === 'zh' ? '没有返回可展示的数据。' : 'No displayable data returned.';
    if (category?.error) return `Error: ${category.error}`;
    const rawOutputs = Array.isArray(category?.raw_outputs) ? category.raw_outputs : [];
    if (rawOutputs.length > 0) {
      const lines: string[] = [];
      for (const item of rawOutputs) {
        lines.push(`[${item.command}]`);
        lines.push(String(item.output || ''));
        lines.push('');
      }
      return lines.join('\n').trim();
    }
    return language === 'zh' ? '命令已执行，但没有返回原始回显。' : 'Command executed, but no raw output was returned.';
  }, [language]);

  const getQuickQueryCommands = useCallback((payload: any, fallbackCommands?: string): string[] => {
    const category = Array.isArray(payload?.categories) ? payload.categories[0] : null;
    const payloadCommands = Array.isArray(category?.commands)
      ? category.commands.map((command: any) => String(command || '').trim()).filter(Boolean)
      : [];
    if (payloadCommands.length > 0) return payloadCommands;
    return String(fallbackCommands || '').split('\n').map((command) => command.trim()).filter(Boolean);
  }, []);

  const handleToggleBatchMode = useCallback(() => {
    setBatchMode((current) => !current);
    setBatchDeviceIds([]);
  }, []);

  const handleToggleBatchDevice = useCallback((deviceId: string) => {
    setBatchDeviceIds((current) => (current.includes(deviceId) ? current.filter((id) => id !== deviceId) : [...current, deviceId]));
  }, []);

  const handleResetQuickQuery = useCallback(() => {
    setQuickQueryOutput('');
    setQuickQueryLabel('');
    setQuickQueryStructured(null);
    setQuickQueryView('terminal');
    setQuickQueryMaximized(false);
    setQuickQueryCommands([]);
  }, []);

  const handleSelectAutomationDevice = useCallback((device: Device) => {
    if (selectedDevice?.id !== device.id) {
      handleResetQuickQuery();
    }
    setSelectedDevice(device);
  }, [selectedDevice, setSelectedDevice, handleResetQuickQuery]);

  const handleClearQuickScenario = useCallback(() => {
    setQuickPlaybookScenario(null);
    setQuickPlaybookPreview(null);
    setQuickPlaybookVars({});
    setQuickRiskConfirmed(false);
  }, []);

  const handleResetQuickExecutionState = useCallback(() => {
    setWsMessages([]);
    setDeviceStatusMap({});
    setWsCompleteMsg(null);
    setQuickExecutionResult(null);
    setExecutionStatus('idle');
    setQuickPlaybookScenario(null);
  }, []);

  const quickQueryTable = useMemo(() => {
    const category = Array.isArray(quickQueryStructured?.categories) ? quickQueryStructured.categories[0] : null;
    const records: Record<string, any>[] = Array.isArray(category?.records) ? category.records : [];
    const columnSet = new Set<string>();
    records.forEach((item: any) => {
      Object.keys(item || {}).forEach((key) => columnSet.add(key));
    });
    const columns: string[] = Array.from(columnSet.values());
    return { category, records, columns };
  }, [quickQueryStructured]);

  const handleSelectPlaybookScenario = useCallback((scenario: any) => {
    setSelectedScenario(scenario);
    setPlaybookVars({});
    setPlaybookPreview(null);
    setPlaybookPlatform(scenario.default_platform || scenario.supported_platforms?.[0] || 'cisco_ios');
  }, []);

  const handlePlaybookPlatformChange = useCallback((platform: string) => {
    setPlaybookPlatform(platform);
    setPlaybookPreview(null);
  }, []);

  const handlePlaybookVariableChange = useCallback((key: string, value: string) => {
    setPlaybookVars((current) => ({ ...current, [key]: value }));
  }, []);

  const handleTogglePlaybookDevice = useCallback((deviceId: string) => {
    setPlaybookDeviceIds((current) => (current.includes(deviceId) ? current.filter((id) => id !== deviceId) : [...current, deviceId]));
  }, []);

  const filteredScenarios = useMemo(() => {
    const q = scenarioSearch.trim().toLowerCase();
    if (!q) return scenarios;

    return scenarios.filter((sc: any) => {
      const textParts: string[] = [
        sc.id,
        sc.name,
        sc.name_zh,
        sc.description,
        sc.description_zh,
        sc.category,
        sc.risk,
      ].filter(Boolean);

      (sc.variables || []).forEach((v: any) => {
        textParts.push(v.key || '', v.label || '', v.placeholder || '');
      });

      Object.values(sc.platform_phases || {}).forEach((phase: any) => {
        ['pre_check', 'execute', 'post_check', 'rollback'].forEach((key) => {
          (phase?.[key] || []).forEach((cmd: string) => textParts.push(cmd));
        });
      });

      const blob = textParts.join(' ').toLowerCase();
      return blob.includes(q);
    });
  }, [scenarios, scenarioSearch]);

  const quickTargetDevices = useMemo(() => {
    if (batchMode) {
      const selectedIds = new Set(batchDeviceIds);
      return devices.filter((d) => selectedIds.has(d.id));
    }
    return selectedDevice ? [selectedDevice] : [];
  }, [batchMode, batchDeviceIds, devices, selectedDevice]);

  const quickDetectedPlatforms = useMemo(() => {
    return Array.from(new Set(quickTargetDevices.map((d) => d.platform).filter(Boolean)));
  }, [quickTargetDevices]);

  const quickHasMixedPlatforms = quickDetectedPlatforms.length > 1;
  const quickDetectedPlatform = quickDetectedPlatforms.length === 1 ? quickDetectedPlatforms[0] : '';
  const quickScenarioSupportsDetectedPlatform = useMemo(() => {
    return !!(
      quickPlaybookScenario &&
      quickDetectedPlatform &&
      (quickPlaybookScenario.supported_platforms || []).includes(quickDetectedPlatform)
    );
  }, [quickPlaybookScenario, quickDetectedPlatform]);

  const quickAutoPlatform = quickDetectedPlatform
    || quickPlaybookScenario?.default_platform
    || quickPlaybookScenario?.supported_platforms?.[0]
    || 'cisco_ios';

  const quickPlatformMismatch = !!(
    quickPlaybookScenario &&
    quickDetectedPlatform &&
    !quickScenarioSupportsDetectedPlatform
  );

  const hasQuickTargets = quickTargetDevices.length > 0;

  const quickMissingRequiredFields = useMemo(() => {
    if (!quickPlaybookScenario) return [];
    return (quickPlaybookScenario.variables || [])
      .filter((v: any) => v.required && !String(quickPlaybookVars[v.key] ?? '').trim())
      .map((v: any) => v.label || v.key);
  }, [quickPlaybookScenario, quickPlaybookVars]);

  useEffect(() => {
    if (!quickPlaybookScenario) return;
    if (quickPlaybookPlatform !== quickAutoPlatform) {
      setQuickPlaybookPlatform(quickAutoPlatform);
    }
  }, [quickPlaybookScenario, quickAutoPlatform, quickPlaybookPlatform]);

  const loadScenarios = useCallback(async () => {
    try {
      const [scenResp, platResp] = await Promise.all([
        fetch('/api/playbooks/scenarios'),
        fetch('/api/playbooks/platforms'),
      ]);
      if (scenResp.ok) setScenarios(await scenResp.json());
      if (platResp.ok) setPlatforms(await platResp.json());
    } catch (error) {
      console.error('Failed to load scenarios:', error);
    }
  }, []);

  const loadPlaybookHistory = useCallback(async (page = 1, statusFilter = 'all', scenarioFilter = '') => {
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: '20',
        status: statusFilter,
        scenario: scenarioFilter,
      });
      const resp = await fetch(`/api/playbooks?${params}`);
      if (resp.ok) {
        const d = await resp.json();
        setPlaybookExecutions((d.items || []).map((e: any) => ({ ...e, _type: 'playbook' })));
        return d.total || 0;
      }
    } catch (error) {
      console.error('Failed to load playbook history:', error);
    }
    return 0;
  }, []);

  const loadJobs = useCallback(async () => {
    try {
      const resp = await fetch('/api/jobs');
      if (resp.ok) {
        setJobs(await resp.json());
      }
    } catch (error) {
      console.error('Failed to load jobs:', error);
    }
  }, []);

  const runPlaybook = useCallback(async (params: {
    scenarioId: string;
    platform: string;
    deviceIds: string[];
    variables: Record<string, string>;
    dryRun: boolean;
    concurrency: number;
    changeTicket?: string;
  }) => {
    setWsMessages([]);
    setDeviceStatusMap({});
    setWsCompleteMsg(null);
    setExecutionStatus('starting');
    
    try {
      const resp = await fetch('/api/playbooks/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenario_id: params.scenarioId,
          platform: params.platform,
          device_ids: params.deviceIds,
          variables: params.variables,
          dry_run: params.dryRun,
          concurrency: params.concurrency,
          change_ticket: params.changeTicket,
          author: currentUser.username || 'admin',
          actor_id: currentUser.id,
          actor_role: currentUser.role || 'Administrator',
        }),
      });

      const data = await resp.json();
      if (!resp.ok) {
        showToast(`Execution failed: ${data.detail || resp.statusText}`, 'error');
        setExecutionStatus('idle');
        return null;
      }

      setActiveExecutionId(data.execution_id);
      setExecutionStatus('running');
      
      const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const wsUrl = `${wsProtocol}://${window.location.host}/api/ws/playbook/${data.execution_id}`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          setWsMessages(prev => [...prev, msg]);
          if (msg.type === 'device_start') {
            setDeviceStatusMap(prev => ({ ...prev, [msg.device_id]: { hostname: msg.hostname || String(msg.device_id), status: 'running', phases: {} } }));
          } else if (msg.type === 'complete') {
            setWsCompleteMsg(msg);
            setExecutionStatus(msg.status);
            ws.close();
            loadPlaybookHistory();
          }
        } catch { /* ignore */ }
      };

      return data.execution_id;
    } catch (error) {
      showToast('Execution error', 'error');
      setExecutionStatus('idle');
      return null;
    }
  }, [currentUser, loadPlaybookHistory, showToast]);

  const runQuickPlaybook = useCallback(async (dryRun: boolean, changeTicket?: string) => {
    if (!quickPlaybookScenario) return;
    const deviceIds = batchMode ? batchDeviceIds : (selectedDevice ? [selectedDevice.id] : []);
    if (deviceIds.length === 0) {
      showToast(language === 'zh' ? '请先选择目标设备' : 'Select target devices first', 'error');
      return;
    }
    
    const ok = await runPlaybook({
      scenarioId: quickPlaybookScenario.id,
      platform: quickPlaybookPlatform,
      deviceIds,
      variables: quickPlaybookVars,
      dryRun,
      concurrency: quickPlaybookConcurrency,
      changeTicket
    });
    
    if (ok) {
      setQuickRiskConfirmed(false);
    }
  }, [quickPlaybookScenario, batchMode, batchDeviceIds, selectedDevice, quickPlaybookPlatform, quickPlaybookVars, quickPlaybookConcurrency, runPlaybook, showToast, language]);

  const openQuickPlaybookModal = useCallback((scenario: any) => {
    const platform = scenario.default_platform || scenario.supported_platforms?.[0] || 'cisco_ios';
    setQuickPlaybookScenario(scenario);
    setQuickPlaybookPlatform(platform);
    setQuickPlaybookVars({});
    setQuickPlaybookDryRun(true);
    setQuickPlaybookConcurrency(1);
    setQuickPlaybookPreview(null);
    setQuickRiskConfirmed(false);
    setQuickExecutionResult(null);
  }, []);

  const loadQuickPlaybookPreview = useCallback(async (scenario: any, platform: string, variables: Record<string, string>) => {
    if (!scenario?.id || !platform) {
      setQuickPlaybookPreview(null);
      return;
    }
    try {
      const resp = await fetch('/api/playbooks/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario_id: scenario.id, platform, variables }),
      });
      if (!resp.ok) {
        setQuickPlaybookPreview(null);
        return;
      }
      setQuickPlaybookPreview(await resp.json());
    } catch {
      setQuickPlaybookPreview(null);
    }
  }, []);
  
  useEffect(() => {
    if (!quickPlaybookScenario) return;
    const timer = setTimeout(() => {
      loadQuickPlaybookPreview(quickPlaybookScenario, quickPlaybookPlatform, quickPlaybookVars);
    }, 220);
    return () => clearTimeout(timer);
  }, [quickPlaybookScenario, quickPlaybookPlatform, quickPlaybookVars, loadQuickPlaybookPreview]);

  const previewPlaybook = useCallback(async (scenario: any, platform: string, variables: Record<string, string>) => {
    if (!scenario) {
      showToast(language === 'zh' ? '请先选择场景' : 'Please select a scenario first', 'error');
      return;
    }
    try {
      const resp = await fetch('/api/playbooks/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario_id: scenario.id, platform, variables }),
      });
      if (resp.ok) {
        setPlaybookPreview(await resp.json());
        showToast(language === 'zh' ? '命令预览已生成' : 'Command preview generated', 'success');
      } else {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        showToast(`Preview failed: ${err.detail || 'Unknown error'}`, 'error');
      }
    } catch {
      showToast(language === 'zh' ? '预览请求失败，请检查网络连接' : 'Preview request failed. Please check your network.', 'error');
    }
  }, [language, showToast]);

  useEffect(() => {
    if (activeTab === 'automation') {
      if (automationPage === 'playbooks') { 
        navigate('/automation/execute'); 
        return; 
      }
      loadScenarios();
      if (automationPage === 'execute' || automationPage === 'scenarios' || automationPage === 'history') {
        loadPlaybookHistory();
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, automationPage]);

  const resetAutomationSubmenuState = useCallback((page: string) => {
    if (page === 'execute') {
      setAutomationSearch('');
      setBatchMode(false);
      setBatchDeviceIds([]);
      setSelectedDevice(null);
      setQuickPlaybookScenario(null);
      setQuickPlaybookVars({});
      setQuickPlaybookPlatform('cisco_ios');
      setQuickPlaybookDryRun(true);
      setQuickPlaybookConcurrency(1);
      setQuickPlaybookPreview(null);
      setQuickRiskConfirmed(false);
      setQuickExecutionResult(null);
      setWsMessages([]);
      setDeviceStatusMap({});
      setWsCompleteMsg(null);
      return;
    }

    if (page === 'playbooks') {
      setSelectedScenario(null);
      setPlaybookVars({});
      setPlaybookDeviceIds([]);
      setPlaybookDryRun(true);
      setPlaybookConcurrency(1);
      setPlaybookPreview(null);
      return;
    }

    if (page === 'scenarios') {
      setScenarioSearch('');
    }
  }, [setAutomationSearch, setBatchMode, setBatchDeviceIds, setSelectedDevice, setQuickPlaybookScenario, setQuickPlaybookVars, setQuickPlaybookPlatform, setQuickPlaybookDryRun, setQuickPlaybookConcurrency, setQuickPlaybookPreview, setQuickRiskConfirmed, setQuickExecutionResult, setWsMessages, setDeviceStatusMap, setWsCompleteMsg, setSelectedScenario, setPlaybookVars, setPlaybookDeviceIds, setPlaybookDryRun, setPlaybookConcurrency, setPlaybookPreview, setScenarioSearch]);

  const executePlaybook = useCallback(async (dryRunOverride?: boolean) => {
    if (!selectedScenario) {
      showToast(language === 'zh' ? '请先选择场景' : 'Please select a scenario first', 'error');
      return;
    }
    if (playbookDeviceIds.length === 0) {
      showToast(language === 'zh' ? '请先选择目标设备' : 'Please select target devices first', 'error');
      return;
    }
    const missingRequired = (selectedScenario.variables || [])
      .filter((v: any) => v.required && !String(playbookVars[v.key] ?? '').trim())
      .map((v: any) => v.label || v.key);
    if (missingRequired.length > 0) {
      showToast(
        language === 'zh'
          ? `缺少必填字段: ${missingRequired.join(', ')}`
          : `Missing required fields: ${missingRequired.join(', ')}`,
        'error'
      );
      return;
    }
    const effectiveDryRun = dryRunOverride !== undefined ? dryRunOverride : playbookDryRun;
    setPlaybookDryRun(effectiveDryRun);
    setExecutionStatus('starting');
    setWsMessages([]);
    setDeviceStatusMap({});
    setWsCompleteMsg(null);
    try {
      const resp = await fetch('/api/playbooks/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenario_id: selectedScenario.id,
          platform: playbookPlatform,
          device_ids: playbookDeviceIds,
          variables: playbookVars,
          dry_run: effectiveDryRun,
          concurrency: playbookConcurrency,
          author: currentUser.username || 'admin',
          actor_id: currentUser.id,
          actor_role: currentUser.role || 'Administrator',
        }),
      });
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        showToast(`执行失败: ${errData.detail || resp.statusText}`, 'error');
        setExecutionStatus('idle');
        return;
      }
      if (resp.ok) {
        const { execution_id } = await resp.json();
        setActiveExecutionId(execution_id);
        setExecutionStatus('running');
        showToast(effectiveDryRun ? (language === 'zh' ? 'Dry-Run 已启动' : 'Dry-Run started') : (language === 'zh' ? '执行已启动' : 'Execution started'), 'success');
        
        const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const wsUrl = `${wsProtocol}://${window.location.host}/api/ws/playbook/${execution_id}`;
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;
        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data);
            setWsMessages(prev => [...prev, msg]);
            if (msg.type === 'device_start') {
              setDeviceStatusMap(prev => ({ ...prev, [msg.device_id]: { hostname: msg.hostname || String(msg.device_id), status: 'running', phases: {} } }));
            } else if (msg.type === 'complete') {
              setWsCompleteMsg(msg);
              setExecutionStatus(msg.status);
              ws.close();
              loadPlaybookHistory();
            }
          } catch { /* ignore */ }
        };
        navigate('/automation/history');
      }
    } catch (e: any) {
      showToast(`Execution error: ${e.message || 'Network error'}`, 'error');
      setExecutionStatus('idle');
    }
  }, [selectedScenario, playbookDeviceIds, playbookVars, playbookDryRun, playbookPlatform, playbookConcurrency, currentUser, language, showToast, navigate, loadPlaybookHistory]);

  const rollback = useCallback((jobId: string) => {
    setJobs(prev => prev.map(j => j.id === jobId ? { ...j, status: 'rolled_back' } : j));
  }, []);

  const runTask = useCallback(async (taskName: string) => {
    if (!selectedDevice) return false;
    setShowDiff(false);
    setIsAutomationTaskRunning(true);
    try {
      let commandPayload = undefined;
      if (taskName === 'Compliance Audit') commandPayload = 'show version';
      else if (taskName === 'VLAN Update') commandPayload = 'system-view\nvlan 100\ndescription Added by NetOps\nquit\ninterface Vlan-interface100\nip address 10.100.0.1 255.255.255.0\nquit';
      else if (taskName === 'Custom Command') commandPayload = customCommand;

      const response = await fetch('/api/execute', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(localStorage.getItem('netops_token') ? { 'Authorization': `Bearer ${localStorage.getItem('netops_token')}` } : {}),
        },
        body: JSON.stringify({
          device_id: selectedDevice.id,
          script_id: (taskName === 'VLAN Update' || taskName === 'Compliance Audit' || taskName === 'Custom Command') 
            ? undefined 
            : (selectedScript?.id || selectedAutomationTemplate?.id),
          command: (taskName === 'VLAN Update' || taskName === 'Compliance Audit' || taskName === 'Custom Command') ? commandPayload : editedScriptContent,
          isConfig: taskName === 'VLAN Update' ? true : taskName === 'Custom Command' ? customCommandMode === 'config' : (!!selectedScript || !!selectedAutomationTemplate),
          config_reason: (taskName === 'Custom Command' && customCommandMode === 'config') ? configReason : undefined,
          approval_token: (taskName === 'Custom Command' && customCommandMode === 'config') ? approvalToken : undefined,
          author: currentUser.username || 'admin',
          actor_id: currentUser.id,
          actor_role: currentUser.role || 'Administrator',
        })
      });
      const data = await response.json();
      if (response.ok) {
        showToast(`Task "${taskName}" completed on ${selectedDevice.hostname}`, 'success');
        if (taskName === 'Custom Command') setCustomCommand('');
        loadJobs();
        return true;
      } else {
        showToast(`Task failed: ${data.error || data.detail || 'Unknown error'}`, 'error');
        return false;
      }
    } catch (error) {
      showToast(`Execution error: ${error}`, 'error');
      return false;
    } finally {
      setIsAutomationTaskRunning(false);
    }
  }, [selectedDevice, customCommand, selectedScript, selectedAutomationTemplate, editedScriptContent, customCommandMode, configReason, approvalToken, currentUser, showToast, loadJobs]);

  const runParsedCustomCommand = useCallback(async (label: string, command: string) => {
    const device = selectedDevice || (batchMode && batchDeviceIds.length === 1 ? devices.find((item) => item.id === batchDeviceIds[0]) : null);
    if (!device) {
      showToast(language === 'zh' ? '请先选择一台设备' : 'Select a device first', 'error');
      return false;
    }
    const commandList = command.split('\n').map((item) => item.trim()).filter(Boolean);
    setQuickQueryLabel(label);
    setQuickQueryOutput('');
    setQuickQueryStructured(null);
    setQuickQueryView('terminal');
    setQuickQueryCommands(commandList);
    setQuickQueryRunning(true);
    try {
      const resp = await fetch(`/api/devices/${device.id}/parsed-command`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(localStorage.getItem('netops_token') ? { 'Authorization': `Bearer ${localStorage.getItem('netops_token')}` } : {}),
        },
        body: JSON.stringify({ command }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        showToast(data.detail || data.error || (language === 'zh' ? '执行失败' : 'Execution failed'), 'error');
        return false;
      }
      const firstCategory = Array.isArray(data?.categories) ? data.categories[0] : null;
      const hasStructuredRecords = Array.isArray(firstCategory?.records) && firstCategory.records.length > 0;
      setQuickQueryCommands(payload => payload.length > 0 ? payload : commandList); // Simple fallback
      setQuickQueryStructured(data);
      setQuickQueryOutput(language === 'zh' ? 'Data formatted' : 'Data formatted'); // Need helper
      setQuickQueryView(hasStructuredRecords ? 'table' : 'terminal');
      return true;
    } catch (error: any) {
      showToast(error?.message || String(error), 'error');
      return false;
    } finally {
      setQuickQueryRunning(false);
    }
  }, [selectedDevice, batchMode, batchDeviceIds, devices, showToast, language]);

  const runBatchTask = useCallback(async (taskName: string) => {
    const targets = devices.filter(d => batchDeviceIds.includes(d.id));
    if (targets.length === 0) return false;
    setIsBatchRunning(true);
    setBatchResults(targets.map(d => ({ deviceId: d.id, hostname: d.hostname, status: 'pending' })));
    let failedCount = 0;
    for (const device of targets) {
      setBatchResults(prev => prev.map(r => r.deviceId === device.id ? { ...r, status: 'running' } : r));
      try {
        let commandPayload = undefined;
        if (taskName === 'Custom Command') commandPayload = customCommand;
        else if (taskName === 'Compliance Audit') commandPayload = 'show version';
        else commandPayload = editedScriptContent;

        if (dryRun) {
          await new Promise(r => setTimeout(r, 500));
          setBatchResults(prev => prev.map(r => r.deviceId === device.id ? { ...r, status: 'success', output: `[DRY-RUN] Would execute on ${device.hostname}:\n${commandPayload}` } : r));
          continue;
        }
        const resp = await fetch('/api/execute', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...(localStorage.getItem('netops_token') ? { 'Authorization': `Bearer ${localStorage.getItem('netops_token')}` } : {}) },
          body: JSON.stringify({
            device_id: device.id,
            command: commandPayload,
            isConfig: taskName === 'Custom Command' ? customCommandMode === 'config' : taskName !== 'Compliance Audit',
            config_reason: (taskName === 'Custom Command' && customCommandMode === 'config') ? configReason : undefined,
            approval_token: (taskName === 'Custom Command' && customCommandMode === 'config') ? approvalToken : undefined,
            author: currentUser.username || 'admin',
            actor_id: currentUser.id,
            actor_role: currentUser.role || 'Administrator',
          })
        });
        const data = await resp.json();
        if (!resp.ok) failedCount += 1;
        setBatchResults(prev => prev.map(r => r.deviceId === device.id ? { ...r, status: resp.ok ? 'success' : 'failed', output: data.output || data.error } : r));
      } catch (e) {
        failedCount += 1;
        setBatchResults(prev => prev.map(r => r.deviceId === device.id ? { ...r, status: 'failed', output: String(e) } : r));
      }
    }
    loadJobs();
    setIsBatchRunning(false);
    if (failedCount > 0) {
      showToast(`Batch task "${taskName}" finished with ${failedCount} failure(s)`, 'error');
      return false;
    }
    showToast(`Batch task "${taskName}" completed on ${targets.length} devices`, 'success');
    return true;
  }, [devices, batchDeviceIds, customCommand, dryRun, customCommandMode, configReason, approvalToken, currentUser, showToast, loadJobs, editedScriptContent]);

  const saveFavorite = useCallback((cmd: string) => {
    if (!cmd.trim()) return;
    const updated = commandFavorites.includes(cmd) ? commandFavorites.filter(c => c !== cmd) : [cmd, ...commandFavorites].slice(0, 20);
    setCommandFavorites(updated);
    localStorage.setItem('cmdFavorites', JSON.stringify(updated));
  }, [commandFavorites]);

  const isFavorited = useCallback((cmd: string) => commandFavorites.includes(cmd), [commandFavorites]);

  const closeCustomCommandModal = useCallback(() => {
    setShowCustomCommandModal(false);
    setShowFavorites(false);
    setCustomCommand('');
    setConfigReason('');
    setApproverUsername('');
    setApprovalCode('');
    setApprovalToken('');
    setApprovalStatus('idle');
    setApprovalError('');
    setApprovalCountdown(0);
  }, []);

  const handleRequestApproval = useCallback(async () => {
    if (!approverUsername.trim() || configReason.trim().length < 2) return;
    setApprovalStatus('sending');
    setApprovalError('');
    try {
      const deviceName = batchMode ? `${batchDeviceIds.length} devices (batch)` : selectedDevice?.hostname || '';
      const resp = await fetch('/api/config-approval/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('netops_token') || ''}` },
        body: JSON.stringify({
          approver_username: approverUsername.trim(),
          config_reason: configReason.trim(),
          device_hostname: deviceName,
          command_preview: customCommand.trim(),
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        setApprovalStatus('error');
        setApprovalError(data.detail || 'Failed to send approval code');
        return;
      }
      setApprovalToken(data.approval_token);
      setApprovalStatus('sent');
      showToast(language === 'zh' ? '验证码已发送至审批人飞书' : 'Code sent to approver via Feishu', 'success');
      let sec = 60;
      setApprovalCountdown(sec);
      const timer = setInterval(() => {
        sec -= 1;
        setApprovalCountdown(sec);
        if (sec <= 0) clearInterval(timer);
      }, 1000);
    } catch {
      setApprovalStatus('error');
      setApprovalError(language === 'zh' ? '网络错误，请重试' : 'Network error, please retry');
    }
  }, [approverUsername, configReason, batchMode, batchDeviceIds, selectedDevice, customCommand, language, showToast]);

  const handleVerifyApproval = useCallback(async () => {
    if (approvalCode.length !== 6 || !approvalToken) return;
    try {
      const resp = await fetch('/api/config-approval/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('netops_token') || ''}` },
        body: JSON.stringify({ approval_token: approvalToken, code: approvalCode }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        setApprovalError(data.detail || 'Verification failed');
        return;
      }
      setApprovalStatus('verified');
      setApprovalError('');
      showToast(language === 'zh' ? '审批验证通过 ✓' : 'Approval verified ✓', 'success');
    } catch {
      setApprovalError(language === 'zh' ? '网络错误，请重试' : 'Network error, please retry');
    }
  }, [approvalCode, approvalToken, language, showToast]);

  const submitCustomCommand = useCallback(async () => {
    const resolvedCommand = applyScriptVars(customCommand).trim();
    if (!resolvedCommand) {
      showToast(language === 'zh' ? '请先输入命令内容' : 'Enter command content first', 'error');
      return;
    }
    const missingVars = customCommandVars.filter((key) => !String(scriptVars[key] ?? '').trim());
    if (missingVars.length > 0) {
      showToast(language === 'zh' ? `请先填写变量: ${missingVars.join('、')}` : `Fill variable values first: ${missingVars.join(', ')}`, 'error');
      return;
    }
    if (batchMode) {
      if (batchDeviceIds.length === 0) {
        showToast(language === 'zh' ? '请先选择目标设备' : 'Select target devices first', 'error');
        return;
      }
      const ok = await runBatchTask('Custom Command');
      if (ok) closeCustomCommandModal();
      return;
    }
    if (!selectedDevice) {
      showToast(language === 'zh' ? '请先选择目标设备' : 'Select a target device first', 'error');
      return;
    }
    if (customCommandMode === 'query') {
      const ok = await runParsedCustomCommand(language === 'zh' ? '自定义查询' : 'Custom Query', resolvedCommand);
      if (ok) closeCustomCommandModal();
      return;
    }
    const ok = await runTask('Custom Command');
    if (ok) closeCustomCommandModal();
  }, [applyScriptVars, customCommand, customCommandVars, scriptVars, batchMode, batchDeviceIds, runBatchTask, closeCustomCommandModal, selectedDevice, customCommandMode, runParsedCustomCommand, runTask, language, showToast]);

  const sanitizeExportName = useCallback((value: string, fallback: string) => {
    const normalized = String(value || fallback)
      .trim()
      .replace(/[<>:"/\\|?*\x00-\x1F]/g, '-')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '');
    return normalized || fallback;
  }, []);

  const getQuickQueryStructuredTable = useCallback((payload: any) => {
    const category = Array.isArray(payload?.categories) ? payload.categories[0] : null;
    const records: Record<string, any>[] = Array.isArray(category?.records) ? category.records : [];
    const columnSet = new Set<string>();
    records.forEach((item) => {
      Object.keys(item || {}).forEach((key) => columnSet.add(key));
    });
    const columns: string[] = Array.from(columnSet.values());
    return { category, records, columns };
  }, []);

  const exportQuickQueryTable = useCallback((commands: string[]) => {
    const category = Array.isArray(quickQueryStructured?.categories) ? quickQueryStructured.categories[0] : null;
    const records: Record<string, any>[] = Array.isArray(category?.records) ? category.records : [];
    const columnSet = new Set<string>();
    records.forEach((item: any) => {
      Object.keys(item || {}).forEach((key) => columnSet.add(key));
    });
    const columns: string[] = Array.from(columnSet.values());
    const table = { category, records, columns };

    if (!table.records.length) {
      showToast(language === 'zh' ? '当前没有可导出的表格记录' : 'No structured records to export', 'error');
      return;
    }

    const dataSheet = XLSX.utils.json_to_sheet(table.records, { header: table.columns });
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, dataSheet, 'Data');

    const metaRows = [
      { key: language === 'zh' ? '查询名称' : 'Query', value: quickQueryLabel },
      { key: language === 'zh' ? '设备' : 'Device', value: quickQueryStructured?.device?.hostname || '' },
      { key: language === 'zh' ? '平台' : 'Platform', value: quickQueryStructured?.device?.platform || '' },
      { key: language === 'zh' ? '采集时间' : 'Collected At', value: quickQueryStructured?.collected_at || '' },
      { key: language === 'zh' ? '解析器' : 'Parser', value: table.category?.parser || 'ntc-templates' },
      { key: language === 'zh' ? '记录数' : 'Records', value: String(table.records.length) },
      { key: language === 'zh' ? '实际执行命令' : 'Executed Commands', value: commands.join('\n') },
    ];
    const metaSheet = XLSX.utils.json_to_sheet(metaRows);
    XLSX.utils.book_append_sheet(workbook, metaSheet, 'Meta');

    const sanitize = (value: string, fallback: string) => {
      return String(value || fallback).trim().replace(/[<>:"/\\|?*\x00-\x1F]/g, '-').replace(/\s+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '') || fallback;
    };

    const deviceName = sanitize(quickQueryStructured?.device?.hostname || 'device', 'device');
    const queryName = sanitize(quickQueryLabel || 'quick-query', 'quick-query');
    const timestamp = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
    XLSX.writeFile(workbook, `${deviceName}_${queryName}_${timestamp}.xlsx`);
    showToast(language === 'zh' ? '已导出 Excel' : 'Excel exported', 'success');
  }, [quickQueryStructured, quickQueryLabel, language, showToast]);

  const runQuickQuery = useCallback(async (label: string, commands: string, operationalCategory?: string) => {
    const device = selectedDevice || (batchMode && batchDeviceIds.length === 1 ? devices.find(d => d.id === batchDeviceIds[0]) : null);
    if (!device) {
      showToast(language === 'zh' ? '请先选择一台设备' : 'Select a device first', 'error');
      return;
    }
    const fallbackCommands = commands.split('\n').map((command) => command.trim()).filter(Boolean);
    setQuickQueryLabel(label);
    setQuickQueryOutput('');
    setQuickQueryStructured(null);
    setQuickQueryView('terminal');
    setQuickQueryCommands(fallbackCommands);
    setQuickQueryRunning(true);
    try {
      if (operationalCategory) {
        const resp = await fetch(`/api/devices/${device.id}/operational-data`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...(localStorage.getItem('netops_token') ? { 'Authorization': `Bearer ${localStorage.getItem('netops_token')}` } : {}) },
          body: JSON.stringify({ categories: [operationalCategory] }),
        });
        const data = await resp.json();
        if (resp.ok) {
          const firstCategory = Array.isArray(data?.categories) ? data.categories[0] : null;
          const hasStructuredRecords = Array.isArray(firstCategory?.records) && firstCategory.records.length > 0;
          setQuickQueryCommands(payloadCommands => payloadCommands.length > 0 ? payloadCommands : fallbackCommands); // Simple
          setQuickQueryStructured(data);
          setQuickQueryOutput(formatQuickQueryRawOutput(data));
          setQuickQueryView(hasStructuredRecords ? 'table' : 'terminal');
        } else {
          setQuickQueryOutput(`Error: ${data.detail || data.error || 'Unknown error'}`);
        }
        return;
      }

      const resp = await fetch('/api/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(localStorage.getItem('netops_token') ? { 'Authorization': `Bearer ${localStorage.getItem('netops_token')}` } : {}) },
        body: JSON.stringify({
          device_id: device.id,
          command: commands,
          isConfig: false,
          save_history: false,
          author: currentUser.username || 'admin',
          actor_id: currentUser.id,
          actor_role: currentUser.role || 'Administrator',
        }),
      });
      const data = await resp.json();
      if (resp.ok) {
        setQuickQueryStructured(null);
        setQuickQueryOutput(data.output || 'No output');
      } else {
        setQuickQueryOutput(`Error: ${data.error || data.detail || 'Unknown error'}`);
      }
    } catch (e: any) {
      setQuickQueryOutput(`Error: ${e.message || e}`);
    } finally {
      setQuickQueryRunning(false);
    }
  }, [selectedDevice, batchMode, batchDeviceIds, devices, currentUser, language, showToast, formatQuickQueryRawOutput]);

  return {
    jobs, setJobs, scheduledTasks, setScheduledTasks, scenarios, platforms, playbookExecutions,
    selectedScenario, setSelectedScenario, playbookVars, setPlaybookVars, playbookDeviceIds, setPlaybookDeviceIds,
    playbookPlatform, setPlaybookPlatform, playbookDryRun, setPlaybookDryRun, playbookConcurrency, setPlaybookConcurrency,
    playbookPreview, setPlaybookPreview, quickPlaybookScenario, setQuickPlaybookScenario, quickPlaybookVars, setQuickPlaybookVars,
    quickPlaybookPlatform, setQuickPlaybookPlatform, quickPlaybookDryRun, setQuickPlaybookDryRun,
    quickPlaybookConcurrency, setQuickPlaybookConcurrency, scripts, setScripts, selectedScript, setSelectedScript,
    selectedAutomationTemplate, setSelectedAutomationTemplate, editedScriptContent, setEditedScriptContent,
    customCommand, setCustomCommand, customCommandMode, setCustomCommandMode, configReason, setConfigReason,
    approverUsername, setApproverUsername, approvalCode, setApprovalCode, approvalToken, setApprovalToken,
    approvalStatus, setApprovalStatus, approvalError, setApprovalError, approvalCountdown, setApprovalCountdown,
    scriptParams, setScriptParams, commandFavorites, setCommandFavorites, showFavorites, setShowFavorites,
    scriptVars, setScriptVars, batchMode, setBatchMode, batchDeviceIds, setBatchDeviceIds,
    batchResults, setBatchResults, isBatchRunning, setIsBatchRunning, dryRun, setDryRun,
    quickQueryOutput, setQuickQueryOutput, quickQueryRunning, setQuickQueryRunning, quickQueryLabel, setQuickQueryLabel,
    quickQueryStructured, setQuickQueryStructured, quickQueryView, setQuickQueryView, quickQueryMaximized, setQuickQueryMaximized,
    quickQueryCommands, setQuickQueryCommands, selectedJob, setSelectedJob, showCustomCommandModal, setShowCustomCommandModal,
    showCmdPreviewModal, setShowCmdPreviewModal, isAutomationTaskRunning, setIsAutomationTaskRunning, showDiff, setShowDiff,
    currentDiff, setCurrentDiff, customCommandVars, applyScriptVars, formatQuickQueryRawOutput, getQuickQueryCommands,
    runTask, runParsedCustomCommand, rollback, runBatchTask, saveFavorite, isFavorited, closeCustomCommandModal,
    handleRequestApproval, handleVerifyApproval, submitCustomCommand, handleSelectPlaybookScenario, handlePlaybookPlatformChange,
    handlePlaybookVariableChange, handleTogglePlaybookDevice, sanitizeExportName, getQuickQueryStructuredTable,
    exportQuickQueryTable, runQuickQuery, handleToggleBatchMode, handleToggleBatchDevice, handleResetQuickQuery,
    handleSelectAutomationDevice, handleClearQuickScenario, handleResetQuickExecutionState, quickPlaybookPreview,
    setQuickPlaybookPreview, quickRiskConfirmed, setQuickRiskConfirmed, isQuickPlaybookRunning, setIsQuickPlaybookRunning,
    quickExecutionResult, setQuickExecutionResult, wsMessages, setWsMessages, deviceStatusMap, setDeviceStatusMap,
    wsCompleteMsg, setWsCompleteMsg, activeExecutionId, setActiveExecutionId, quickQueryTable, executionStatus,
    setExecutionStatus, quickTargetDevices, quickDetectedPlatforms, quickHasMixedPlatforms, quickDetectedPlatform,
    quickScenarioSupportsDetectedPlatform, quickAutoPlatform, quickPlatformMismatch, hasQuickTargets,
    quickMissingRequiredFields, automationSearch, setAutomationSearch, scenarioSearch, setScenarioSearch,
    filteredScenarios, loadScenarios, loadPlaybookHistory, loadJobs, runPlaybook, openQuickPlaybookModal,
    loadQuickPlaybookPreview, previewPlaybook, resetAutomationSubmenuState, executePlaybook,
    runQuickPlaybook,
    extractVars, splitLines,
  };
};
