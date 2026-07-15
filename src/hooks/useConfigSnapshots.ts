import { useCallback, useEffect } from 'react';
import type { ConfigSnapshot, Device, SessionUser, User as UserType } from '../types';
import { getVendorFromPlatform } from '../types';
import type { Language } from '../i18n.tsx';
import { useConfigStore } from '../store/configStore';

const MOCK_IPS = ['127.0.0.1', '0.0.0.0', 'localhost'];
const NETWORK_PLATFORM_KEYWORDS = ['cisco', 'arista', 'rgos', 'ruijie', 'juniper', 'junos', 'huawei', 'vrp', 'h3c', 'comware'];

const isNetworkDevice = (platform?: string) => {
  const p = (platform || '').toLowerCase();
  return NETWORK_PLATFORM_KEYWORDS.some((kw) => p.includes(kw));
};

interface UseConfigSnapshotsArgs {
  devices: Device[];
  language: Language;
  t: (key: string) => string;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  currentUser: SessionUser;
  currentUserRecord?: UserType;
  copyTextWithFallback: (text: string) => Promise<boolean>;
  isAuthenticated: boolean;
  activeTab: string;
  configPage: string;
}

export const useConfigSnapshots = ({
  devices,
  language,
  t,
  showToast,
  currentUser,
  currentUserRecord,
  copyTextWithFallback,
  isAuthenticated,
  activeTab,
  configPage,
}: UseConfigSnapshotsArgs) => {
  const configSnapshotKeyword = useConfigStore((s) => s.configSnapshotKeyword);
  const setConfigSnapshotKeyword = useConfigStore((s) => s.setConfigSnapshotKeyword);
  const configCenterDevice = useConfigStore((s) => s.configCenterDevice);
  const setConfigSnapshots = useConfigStore((s) => s.setConfigSnapshots);
  const setConfigSnapshotsLoading = useConfigStore((s) => s.setConfigSnapshotsLoading);
  const configViewContent = useConfigStore((s) => s.configViewContent);
  const setConfigViewContent = useConfigStore((s) => s.setConfigViewContent);
  const setConfigViewSnapshot = useConfigStore((s) => s.setConfigViewSnapshot);
  const setIsTakingSnapshot = useConfigStore((s) => s.setIsTakingSnapshot);
  const setActiveBackupRunId = useConfigStore((s) => s.setActiveBackupRunId);
  const scheduleEnabled = useConfigStore((s) => s.scheduleEnabled);
  const setScheduleEnabled = useConfigStore((s) => s.setScheduleEnabled);
  const scheduleCron = useConfigStore((s) => s.scheduleCron);
  const setScheduleCron = useConfigStore((s) => s.setScheduleCron);
  const setScheduleLoading = useConfigStore((s) => s.setScheduleLoading);

  const loadConfigSnapshots = useCallback(async (
    deviceId?: string,
    options?: { requireFilter?: boolean; q?: string },
  ) => {
    const q = (options?.q ?? configSnapshotKeyword).trim();
    const requireFilter = options?.requireFilter ?? false;
    const hasAnyFilter = Boolean(deviceId || q);

    if (requireFilter && !hasAnyFilter) {
      setConfigSnapshots([]);
      setConfigSnapshotsLoading(false);
      return;
    }

    setConfigSnapshotsLoading(true);
    try {
      const params = new URLSearchParams();
      if (deviceId) params.set('device_id', deviceId);
      if (q) params.set('q', q);
      const qs = params.toString();
      const url = qs ? `/api/configs/snapshots?${qs}` : '/api/configs/snapshots';
      const resp = await fetch(url);
      if (resp.ok) {
        const data = (await resp.json()) as ConfigSnapshot[];
        setConfigSnapshots(data);
      }
    } catch {
      // network error
    } finally {
      setConfigSnapshotsLoading(false);
    }
  }, [configSnapshotKeyword, setConfigSnapshots, setConfigSnapshotsLoading]);

  const loadSnapshotContent = useCallback(async (snap: ConfigSnapshot): Promise<string> => {
    if (snap.content) return snap.content;
    try {
      const resp = await fetch(`/api/configs/snapshots/${snap.id}/content`);
      if (resp.ok) {
        const data = await resp.json();
        return data.content as string;
      }
    } catch {
      // ignore
    }
    return '';
  }, []);

  const loadScheduleConfig = useCallback(async () => {
    try {
      const resp = await fetch('/api/configs/schedule');
      if (resp.ok) {
        const cfg = await resp.json();
        setScheduleEnabled(cfg.enabled ?? true);
        setScheduleCron(cfg.cron || '0 2 * * *');
      }
    } catch {
      // ignore
    }
  }, [setScheduleEnabled, setScheduleCron]);

  // Load schedule config once on auth
  useEffect(() => {
    if (isAuthenticated) {
      loadScheduleConfig();
    }
  }, [isAuthenticated, loadScheduleConfig]);

  // Trigger snapshot load when entering relevant config tab.
  useEffect(() => {
    if (activeTab !== 'config') return;
    if (configPage === 'backup' || configPage === 'diff') {
      loadConfigSnapshots(configCenterDevice?.id, { requireFilter: true });
    } else if (configPage === 'search') {
      loadConfigSnapshots(configCenterDevice?.id);
    }
  }, [activeTab, configPage, configCenterDevice?.id, loadConfigSnapshots]);

  const takeConfigSnapshot = useCallback(async (
    device: Device,
    trigger: ConfigSnapshot['trigger'] = 'manual',
  ): Promise<ConfigSnapshot | null> => {
    if (MOCK_IPS.includes(device.ip_address || '')) {
      showToast(
        language === 'zh'
          ? `${device.hostname} (${device.ip_address}) 为模拟设备，无法备份真实配置`
          : `${device.hostname} (${device.ip_address}) is a mock device, cannot backup real config`,
        'error',
      );
      return null;
    }

    if (!isNetworkDevice(device.platform)) {
      showToast(
        language === 'zh'
          ? `${device.hostname} 不是网络设备，跳过配置备份`
          : `${device.hostname} is not a network device, backup skipped`,
        'error',
      );
      return null;
    }

    setIsTakingSnapshot(true);
    try {
      let configContent = '';
      let fetchSuccess = false;
      try {
        const _p = (device.platform || '').toLowerCase();
        const _cmd = _p.includes('cisco') || _p.includes('arista') || _p.includes('rgos') || _p.includes('ruijie')
          ? 'show running-config'
          : _p.includes('juniper') || _p.includes('junos')
            ? 'show configuration'
            : 'display current-configuration';
        const _token = localStorage.getItem('netops_token');
        const execResp = await fetch('/api/execute', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...(_token ? { Authorization: `Bearer ${_token}` } : {}) },
          body: JSON.stringify({
            device_id: device.id,
            command: _cmd,
            isConfig: false,
            // `show running-config` requires privileged exec mode; force admin.
            auth_role: 'admin',
            author: currentUser.username || 'admin',
            actor_id: currentUser.id,
            actor_role: currentUser.role || currentUserRecord?.role || 'Administrator',
          }),
        });
        if (execResp.ok) {
          const execData = await execResp.json();
          const output = execData.output || '';
          const lower = output.toLowerCase();
          const isErrorOutput =
            !output.trim()
            || output.startsWith('[Mock ')
            || output.startsWith('% ')
            || lower.includes('% invalid input')
            || lower.includes('% permission denied')
            || lower.includes('% authorization failed')
            || lower.includes('command not found');
          if (!isErrorOutput) {
            configContent = output;
            fetchSuccess = true;
          }
        }
      } catch {
        // device unreachable
      }

      if (!fetchSuccess || !configContent.trim()) {
        showToast(
          language === 'zh'
            ? `${device.hostname} 配置获取失败（请检查特权账号或设备权限）`
            : `Failed to fetch config from ${device.hostname} (check admin credentials)`,
          'error',
        );
        return null;
      }

      const saveResp = await fetch('/api/configs/snapshots', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          device_id: device.id,
          hostname: device.hostname,
          vendor: device.vendor || getVendorFromPlatform(device.platform),
          content: configContent,
          trigger,
          author: currentUser.username || 'admin',
          actor_id: currentUser.id,
          actor_role: currentUser.role || currentUserRecord?.role || 'Administrator',
        }),
      });
      if (saveResp.ok) {
        const snap = (await saveResp.json()) as ConfigSnapshot;
        snap.content = configContent;
        setConfigSnapshots((prev) => [snap, ...prev]);
        showToast(`${t('snapshotSaved')} ${device.hostname}`, 'success');
        return snap;
      }
      showToast('Failed to persist snapshot', 'error');
    } catch {
      showToast('Snapshot failed', 'error');
    } finally {
      setIsTakingSnapshot(false);
    }
    return null;
  }, [
    setIsTakingSnapshot,
    setConfigSnapshots,
    showToast,
    language,
    t,
    currentUser,
    currentUserRecord,
  ]);

  const saveScheduleConfig = useCallback(async () => {
    setScheduleLoading(true);
    try {
      const resp = await fetch('/api/configs/schedule', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: scheduleEnabled, cron: scheduleCron }),
      });
      if (resp.ok) showToast(t('scheduleUpdated'), 'success');
      else {
        const err = await resp.json().catch(() => ({}));
        showToast(err.detail || 'Invalid schedule', 'error');
      }
    } catch {
      // ignore
    } finally {
      setScheduleLoading(false);
    }
  }, [scheduleEnabled, scheduleCron, setScheduleLoading, showToast, t]);

  const handleSearchConfigSnapshots = useCallback(async (query = configSnapshotKeyword) => {
    await loadConfigSnapshots(configCenterDevice?.id, { requireFilter: true, q: query });
  }, [configSnapshotKeyword, configCenterDevice?.id, loadConfigSnapshots]);

  const handleClearConfigSnapshotSearch = useCallback(async () => {
    setConfigSnapshotKeyword('');
    await loadConfigSnapshots(configCenterDevice?.id, { requireFilter: true, q: '' });
  }, [configCenterDevice?.id, loadConfigSnapshots, setConfigSnapshotKeyword]);

  const handleRunBackupAllOnline = useCallback(async () => {
    const online = devices.filter(
      (device) =>
        device.status === 'online'
        && !MOCK_IPS.includes(device.ip_address || '')
        && isNetworkDevice(device.platform),
    );
    if (online.length === 0) {
      showToast(
        language === 'zh'
          ? '没有可备份的在线网络设备（Linux / 服务器不支持配置备份）'
          : 'No online network devices to backup (servers not supported)',
        'error',
      );
      return;
    }

    setIsTakingSnapshot(true);
    try {
      const token = localStorage.getItem('netops_token');
      const resp = await fetch('/api/configs/run-now', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        showToast(
          (language === 'zh' ? '触发备份失败' : 'Failed to trigger backup')
            + (err?.detail ? `: ${err.detail}` : ` (HTTP ${resp.status})`),
          'error',
        );
        return;
      }
      const { run_id } = await resp.json();
      setActiveBackupRunId(run_id || null);
      showToast(`${t('backupStarted')} (${online.length} ${t('devicesOnline')})`, 'info');

      if (run_id) {
        const pollInterval = window.setInterval(async () => {
          try {
            const pr = await fetch(`/api/configs/run-now/${run_id}/progress`, {
              headers: token ? { Authorization: `Bearer ${token}` } : {},
            });
            if (!pr.ok) {
              window.clearInterval(pollInterval);
              return;
            }
            const progress = await pr.json();
            try {
              await loadConfigSnapshots(configCenterDevice?.id, { requireFilter: true });
            } catch {
              // ignore
            }
            if (progress.finished) {
              window.clearInterval(pollInterval);
              setTimeout(() => {
                setActiveBackupRunId(null);
              }, 3000);
              const { success, failed } = progress;
              showToast(
                language === 'zh'
                  ? `备份完成：${success} 成功${failed > 0 ? `，${failed} 失败` : ''}`
                  : `Backup complete: ${success} succeeded${failed > 0 ? `, ${failed} failed` : ''}`,
                failed > 0 ? 'error' : 'success',
              );
            }
          } catch {
            window.clearInterval(pollInterval);
          }
        }, 2000);
      }
    } catch (err) {
      showToast(
        (language === 'zh' ? '网络错误' : 'Network error')
          + `: ${err instanceof Error ? err.message : String(err)}`,
        'error',
      );
    } finally {
      setIsTakingSnapshot(false);
    }
  }, [
    devices,
    language,
    t,
    showToast,
    setIsTakingSnapshot,
    setActiveBackupRunId,
    loadConfigSnapshots,
    configCenterDevice?.id,
  ]);

  const handleBackupSingleDevice = useCallback(async (deviceId: string) => {
    const device = devices.find((d) => d.id === deviceId);
    if (!device) return;
    await takeConfigSnapshot(device, 'manual');
  }, [devices, takeConfigSnapshot]);

  const handleCopyConfigContent = useCallback(async () => {
    const copied = await copyTextWithFallback(configViewContent);
    showToast(copied ? t('configCopied') : (language === 'zh' ? '复制失败' : 'Copy failed'), copied ? 'success' : 'error');
  }, [configViewContent, copyTextWithFallback, language, showToast, t]);

  const handleFetchLiveConfig = useCallback(async () => {
    if (!configCenterDevice) return;
    const snapshot = await takeConfigSnapshot(configCenterDevice);
    if (snapshot) {
      setConfigViewSnapshot(snapshot);
      setConfigViewContent(snapshot.content || '');
    }
  }, [configCenterDevice, takeConfigSnapshot, setConfigViewSnapshot, setConfigViewContent]);

  const handleOpenConfigSnapshot = useCallback(async (snapshot: ConfigSnapshot) => {
    const content = await loadSnapshotContent(snapshot);
    setConfigViewSnapshot({ ...snapshot, content });
    setConfigViewContent(content);
  }, [loadSnapshotContent, setConfigViewSnapshot, setConfigViewContent]);

  const handleCopyConfigSnapshot = useCallback(async (snapshot: ConfigSnapshot) => {
    const content = await loadSnapshotContent(snapshot);
    const copied = await copyTextWithFallback(content);
    showToast(copied ? t('configCopied') : (language === 'zh' ? '复制失败' : 'Copy failed'), copied ? 'success' : 'error');
  }, [loadSnapshotContent, copyTextWithFallback, language, showToast, t]);

  const handleRunScheduledBackupNow = useCallback(async () => {
    const online = devices.filter((device) => device.status === 'online');
    showToast(`${t('backupStarted')} (${online.length} ${t('devicesOnline')})`, 'info');
    for (const device of online) {
      await takeConfigSnapshot(device, 'scheduled');
    }
    showToast(t('backupComplete'), 'success');
    await loadConfigSnapshots();
  }, [devices, showToast, t, takeConfigSnapshot, loadConfigSnapshots]);

  return {
    loadConfigSnapshots,
    loadSnapshotContent,
    saveScheduleConfig,
    handleSearchConfigSnapshots,
    handleClearConfigSnapshotSearch,
    handleRunBackupAllOnline,
    handleBackupSingleDevice,
    handleCopyConfigContent,
    handleFetchLiveConfig,
    handleOpenConfigSnapshot,
    handleCopyConfigSnapshot,
    handleRunScheduledBackupNow,
  };
};
