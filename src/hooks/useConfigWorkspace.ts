import * as XLSX from 'xlsx';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ConfigTemplate, Device, SessionUser } from '../types';
import { getVendorFromPlatform } from '../types';
import type { Language } from '../i18n.tsx';
import { apiRequest } from '../api/http';

interface GlobalVar {
  id?: string;
  key: string;
  value: string;
}

interface TemplateValidationResult {
  valid: boolean;
  syntax_valid: boolean;
  render_valid: boolean;
  rendered: string;
  issues: Array<{ message: string }>;
  warnings: Array<{ message: string }>;
  risk_level: 'none' | 'high' | 'critical';
  risk_items: Array<{ line: number; command: string; message: string }>;
}

interface UseConfigWorkspaceArgs {
  devices: Device[];
  language: Language;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  currentUser: SessionUser;
  extractVars: (input: string) => string[];
}

export const useConfigWorkspace = ({
  devices,
  language,
  showToast,
  currentUser,
  extractVars,
}: UseConfigWorkspaceArgs) => {
  const [globalVars, setGlobalVars] = useState<GlobalVar[]>([]);
  const [configTemplates, setConfigTemplates] = useState<ConfigTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>('');
  const [editorContent, setEditorContent] = useState<string>('');
  const [configWorkspaceView, setConfigWorkspaceView] = useState<'source' | 'rendered' | 'checks'>('source');
  const [configScopePlatform, setConfigScopePlatform] = useState<string>('all');
  const [configScopeRole, setConfigScopeRole] = useState<string>('all');
  const [configScopeSite, setConfigScopeSite] = useState<string>('all');
  const [serverValidation, setServerValidation] = useState<TemplateValidationResult | null>(null);

  // Reset per-template scope state when switching templates.
  useEffect(() => {
    setConfigWorkspaceView('source');
    setConfigScopePlatform('all');
    setConfigScopeRole('all');
    setConfigScopeSite('all');
  }, [selectedTemplateId]);

  // Sync editor content with the selected template.
  useEffect(() => {
    if (!selectedTemplateId) {
      setEditorContent('');
      return;
    }
    const template = configTemplates.find((item) => item.id === selectedTemplateId);
    if (template) {
      setEditorContent(template.content || '');
    }
  }, [selectedTemplateId, configTemplates]);

  useEffect(() => {
    setServerValidation(null);
  }, [editorContent, globalVars, selectedTemplateId]);

  const selectedConfigTemplate = useMemo(
    () => configTemplates.find((template) => template.id === selectedTemplateId) || null,
    [configTemplates, selectedTemplateId],
  );

  const configVariableKeys = useMemo(() => extractVars(editorContent), [editorContent, extractVars]);
  const configDefaultedVariableKeys = useMemo(() => {
    const keys = new Set<string>();
    const pattern = /\{\{\s*([\w.-]+)\s*\|\s*(?:default|d)\s*\(/g;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(editorContent)) !== null) {
      keys.add(match[1]);
    }
    return keys;
  }, [editorContent]);

  const configVariableMap = useMemo(
    () => globalVars.reduce((acc, item) => {
      acc[item.key] = String(item.value ?? '');
      return acc;
    }, {} as Record<string, string>),
    [globalVars],
  );

  const configMissingVariables = useMemo(
    () => configVariableKeys.filter(
      (key) => !configDefaultedVariableKeys.has(key) && !String(configVariableMap[key] ?? '').trim(),
    ),
    [configDefaultedVariableKeys, configVariableKeys, configVariableMap],
  );

  const configRenderedPreview = useMemo(() => (
    serverValidation?.render_valid
      ? serverValidation.rendered
      : editorContent.replace(/\{\{\s*([\w.-]+)(?:\s*\|\s*[^}]+)?\s*\}\}/g, (match, key: string) => configVariableMap[key] ?? match)
  ), [editorContent, configVariableMap, serverValidation]);

  const configVendorScopedDevices = useMemo(() => {
    const vendor = (selectedConfigTemplate?.vendor || '').trim();
    if (!vendor || vendor.toLowerCase() === 'custom') return devices;
    return devices.filter(
      (device) => (device.vendor || getVendorFromPlatform(device.platform)).toLowerCase() === vendor.toLowerCase(),
    );
  }, [devices, selectedConfigTemplate]);

  const configPlatformOptions = useMemo(
    () => Array.from(new Set(configVendorScopedDevices.map((device) => device.platform).filter(Boolean))).sort(),
    [configVendorScopedDevices],
  );

  const configRoleOptions = useMemo(
    () => Array.from(new Set(configVendorScopedDevices.map((device) => device.role).filter(Boolean))).sort(),
    [configVendorScopedDevices],
  );

  const configSiteOptions = useMemo(
    () => Array.from(new Set(configVendorScopedDevices.map((device) => device.site).filter(Boolean))).sort(),
    [configVendorScopedDevices],
  );

  const configScopedDevices = useMemo(() => configVendorScopedDevices.filter((device) => {
    if (configScopePlatform !== 'all' && device.platform !== configScopePlatform) return false;
    if (configScopeRole !== 'all' && device.role !== configScopeRole) return false;
    if (configScopeSite !== 'all' && device.site !== configScopeSite) return false;
    return true;
  }), [configVendorScopedDevices, configScopePlatform, configScopeRole, configScopeSite]);

  const configScopedOnlineCount = useMemo(
    () => configScopedDevices.filter((device) => device.status === 'online').length,
    [configScopedDevices],
  );

  const configValidationIssues = useMemo(() => {
    const issues: string[] = [];
    if (!selectedConfigTemplate) {
      issues.push(language === 'zh' ? '尚未选择模板资产' : 'No template asset selected');
    }
    if (!editorContent.trim()) {
      issues.push(language === 'zh' ? '模板内容为空' : 'Template content is empty');
    }
    if (configMissingVariables.length > 0) {
      issues.push(
        language === 'zh'
          ? `仍有未赋值变量: ${configMissingVariables.join('、')}`
          : `Missing variable values: ${configMissingVariables.join(', ')}`,
      );
    }
    if (configScopedDevices.length === 0) {
      issues.push(language === 'zh' ? '当前发布范围内没有匹配设备' : 'No devices match the current release scope');
    }
    serverValidation?.issues.forEach((issue) => issues.push(issue.message));
    return issues;
  }, [selectedConfigTemplate, editorContent, configMissingVariables, configScopedDevices, language, serverValidation]);

  const configValidationWarnings = useMemo(() => {
    const warnings: string[] = [];
    const offlineCount = configScopedDevices.filter((device) => device.status !== 'online').length;
    if (offlineCount > 0) {
      warnings.push(
        language === 'zh'
          ? `${offlineCount} 台目标设备当前不在线，建议先做连接性确认`
          : `${offlineCount} target devices are not online; verify reachability before release`,
      );
    }
    if (configScopedDevices.length > 20) {
      warnings.push(
        language === 'zh'
          ? '当前发布范围较大，建议先小范围灰度'
          : 'Release scope is large; consider a staged rollout first',
      );
    }
    serverValidation?.warnings.forEach((warning) => warnings.push(warning.message));
    serverValidation?.risk_items.slice(0, 5).forEach((risk) => {
      warnings.push(
        language === 'zh'
          ? `第 ${risk.line} 行：${risk.message}（${risk.command}）`
          : `Line ${risk.line}: ${risk.message} (${risk.command})`,
      );
    });
    return warnings;
  }, [configScopedDevices, language, serverValidation]);

  const configReadinessScore = useMemo(() => {
    let score = 100;
    if (!editorContent.trim()) score -= 45;
    score -= Math.min(30, configMissingVariables.length * 15);
    if (configScopedDevices.length === 0) score -= 30;
    score -= Math.min(20, configScopedDevices.filter((device) => device.status !== 'online').length * 5);
    return Math.max(0, score);
  }, [editorContent, configMissingVariables, configScopedDevices]);

  const refreshConfigWorkspace = useCallback(async () => {
    const [templatesPayload, nextGlobalVars] = await Promise.all([
      apiRequest<{ items: ConfigTemplate[] }>('/api/config-templates?page=1&page_size=200&sort=updated'),
      apiRequest<GlobalVar[]>('/api/vars'),
    ]);

    const nextTemplates = templatesPayload.items || [];
    setConfigTemplates(nextTemplates);
    setGlobalVars(nextGlobalVars);

    const nextSelectedId = nextTemplates.some((template) => template.id === selectedTemplateId)
      ? selectedTemplateId
      : (nextTemplates[0]?.id || '');

    setSelectedTemplateId(nextSelectedId);
    setEditorContent(nextTemplates.find((template) => template.id === nextSelectedId)?.content || '');
  }, [selectedTemplateId]);

  const handleImportVars = useCallback(async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    try {
      const data = await file.arrayBuffer();
      const workbook = XLSX.read(data, { type: 'array' });
      const worksheet = workbook.Sheets[workbook.SheetNames[0]];
      const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(worksheet, { defval: '' });
      const importedVars = rows
        .map((row) => ({
          key: String(row.key ?? row.Key ?? row.name ?? row.Name ?? '').trim(),
          value: String(row.value ?? row.Value ?? row.val ?? '').trim(),
        }))
        .filter((item) => item.key);

      if (importedVars.length === 0) {
        showToast(language === 'zh' ? '文件中没有可导入的变量' : 'No importable variables found in the file', 'info');
        return;
      }

      const existingByKey = new Map<string, GlobalVar>(globalVars.map((item) => [item.key, item]));
      for (const item of importedVars) {
        const existing = existingByKey.get(item.key);
        const response = await fetch(existing?.id ? `/api/vars/${existing.id}` : '/api/vars', {
          method: existing?.id ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ...item,
            actor_username: currentUser.username || 'admin',
            actor_role: currentUser.role || 'Administrator',
          }),
        });

        if (!response.ok) {
          const error = await response.json().catch(() => ({}));
          throw new Error(error.detail || response.statusText);
        }
      }

      await refreshConfigWorkspace();
      showToast(
        language === 'zh' ? `已导入 ${importedVars.length} 个变量` : `Imported ${importedVars.length} variables`,
        'success',
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      showToast(language === 'zh' ? `导入变量失败: ${message}` : `Failed to import variables: ${message}`, 'error');
    } finally {
      event.target.value = '';
    }
  }, [globalVars, refreshConfigWorkspace, currentUser, language, showToast]);

  const handleNewTemplate = useCallback(() => {
    const templateId = `draft-${Date.now()}`;
    const now = new Date().toISOString().slice(0, 16).replace('T', ' ');
    const nextTemplate: ConfigTemplate = {
      id: templateId,
      name: language === 'zh' ? '未命名模板' : 'Untitled Template',
      type: 'Jinja2',
      category: 'custom',
      vendor: 'Custom',
      content: '',
      lastUsed: now,
    };

    setConfigTemplates((prev) => [nextTemplate, ...prev]);
    setSelectedTemplateId(templateId);
    setEditorContent('');
  }, [language]);

  const handleAddVar = useCallback(async () => {
    const key = window.prompt(language === 'zh' ? '输入变量名' : 'Enter variable name', '');
    if (!key || !key.trim()) return;
    const value = window.prompt(language === 'zh' ? '输入变量值' : 'Enter variable value', '');
    if (value === null) return;

    try {
      const response = await fetch('/api/vars', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          key: key.trim(),
          value,
          actor_username: currentUser.username || 'admin',
          actor_role: currentUser.role || 'Administrator',
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || response.statusText);
      }
      setGlobalVars((prev) => [...prev, data]);
      showToast(language === 'zh' ? '已新增全局变量' : 'Global variable added', 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      showToast(language === 'zh' ? `新增变量失败: ${message}` : `Failed to add variable: ${message}`, 'error');
    }
  }, [currentUser, language, showToast]);

  const handleDeleteVar = useCallback(async (id: string) => {
    try {
      const response = await fetch(`/api/vars/${id}`, { method: 'DELETE' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || response.statusText);
      }
      setGlobalVars((prev) => prev.filter((item) => item.id !== id));
      showToast(language === 'zh' ? '已删除全局变量' : 'Global variable deleted', 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      showToast(language === 'zh' ? `删除变量失败: ${message}` : `Failed to delete variable: ${message}`, 'error');
    }
  }, [language, showToast]);

  const handleDiscardChanges = useCallback(async () => {
    try {
      await refreshConfigWorkspace();
      setConfigWorkspaceView('source');
      showToast(language === 'zh' ? '已恢复到最近保存版本' : 'Reverted to the latest saved version', 'success');
    } catch {
      showToast(language === 'zh' ? '恢复模板失败' : 'Failed to restore template', 'error');
    }
  }, [refreshConfigWorkspace, language, showToast]);

  const handleValidateTemplateWorkspace = useCallback(async () => {
    setConfigWorkspaceView('checks');
    if (!selectedConfigTemplate || !editorContent.trim()) {
      const issue = !selectedConfigTemplate
        ? (language === 'zh' ? '尚未选择模板资产' : 'No template asset selected')
        : (language === 'zh' ? '模板内容为空' : 'Template content is empty');
      showToast(issue, 'error');
      return;
    }
    try {
      const response = await apiRequest<{ success: boolean; data: TemplateValidationResult }>(
        '/api/config-templates/validate',
        {
          method: 'POST',
          body: JSON.stringify({
            content: editorContent,
            variables: configVariableMap,
            vendor: selectedConfigTemplate.vendor || '',
            platform: configScopePlatform === 'all' ? (configPlatformOptions.length === 1 ? configPlatformOptions[0] : '') : configScopePlatform,
            software_version: selectedConfigTemplate.software_version || '',
            rollback: selectedConfigTemplate.rollback || '',
          }),
        },
      );
      setServerValidation(response.data);
      if (!response.data.valid) {
        showToast(response.data.issues[0]?.message || (language === 'zh' ? '模板校验失败' : 'Validation failed'), 'error');
      } else if (response.data.risk_level !== 'none') {
        showToast(
          language === 'zh'
            ? `语法与渲染通过，但检测到 ${response.data.risk_level === 'critical' ? '严重' : '高'}风险命令`
            : `Syntax and rendering passed with ${response.data.risk_level} risk commands`,
          'info',
        );
      } else {
        showToast(language === 'zh' ? '服务端语法、变量、渲染和风险检查通过' : 'Server preflight checks passed', 'success');
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : (language === 'zh' ? '模板校验失败' : 'Validation failed'), 'error');
    }
  }, [configPlatformOptions, configScopePlatform, configVariableMap, editorContent, language, selectedConfigTemplate, showToast]);

  const handleSaveTemplate = useCallback(async () => {
    if (!selectedConfigTemplate) {
      showToast(language === 'zh' ? '请先选择模板资产' : 'Select a template asset first', 'error');
      return;
    }

    const payload = {
      ...selectedConfigTemplate,
      content: editorContent,
      lastUsed: new Date().toISOString().slice(0, 16).replace('T', ' '),
    };

    try {
      const isDraft = selectedConfigTemplate.id.startsWith('draft-');
      await apiRequest(isDraft ? '/api/config-templates' : `/api/config-templates/${selectedConfigTemplate.id}`, {
        method: isDraft ? 'POST' : 'PUT',
        body: JSON.stringify(payload),
      });
      await refreshConfigWorkspace();
      showToast(language === 'zh' ? '模板已保存' : 'Template saved', 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      showToast(language === 'zh' ? `保存模板失败: ${message}` : `Failed to save template: ${message}`, 'error');
    }
  }, [selectedConfigTemplate, editorContent, refreshConfigWorkspace, language, showToast]);

  return {
    // raw state setters used by external loaders (fetchSharedData)
    globalVars,
    setGlobalVars,
    configTemplates,
    setConfigTemplates,
    selectedTemplateId,
    setSelectedTemplateId,
    editorContent,
    setEditorContent,
    // workspace UI state
    configWorkspaceView,
    setConfigWorkspaceView,
    configScopePlatform,
    setConfigScopePlatform,
    configScopeRole,
    setConfigScopeRole,
    configScopeSite,
    setConfigScopeSite,
    // derived
    selectedConfigTemplate,
    configVariableKeys,
    configVariableMap,
    configMissingVariables,
    configRenderedPreview,
    configPlatformOptions,
    configRoleOptions,
    configSiteOptions,
    configScopedDevices,
    configScopedOnlineCount,
    configValidationIssues,
    configValidationWarnings,
    configReadinessScore,
    // actions
    refreshConfigWorkspace,
    handleImportVars,
    handleNewTemplate,
    handleAddVar,
    handleDeleteVar,
    handleDiscardChanges,
    handleValidateTemplateWorkspace,
    handleSaveTemplate,
  };
};
