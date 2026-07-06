import { useCallback, useState } from 'react';
import type { Device, DeviceConnectionCheckSummary } from '../types';
import type { Language } from '../i18n.tsx';
import { buildConnectionTestMessage, buildConnectionCheckStatus } from '../utils/connectionHelpers';

export interface ConnectionTestStage {
  stage: string;
  ok: boolean;
  summary: string;
  detail: string;
  latency_ms?: number | null;
}

export interface ConnectionTestResult {
  success: boolean;
  message: string;
  output?: string;
  rawError?: string;
  errorCode?: string;
  checkMode?: string;
  stages?: ConnectionTestStage[];
}

interface UseDeviceConnectionAndSnmpArgs {
  language: Language;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  selectedDevice: Device | null;
  setDevices: React.Dispatch<React.SetStateAction<Device[]>>;
  fetchDevicesData: () => Promise<void> | void;
}

export const useDeviceConnectionAndSnmp = ({
  language,
  showToast,
  selectedDevice,
  setDevices,
  fetchDevicesData,
}: UseDeviceConnectionAndSnmpArgs) => {
  const [isTestingConnection, setIsTestingConnection] = useState(false);
  const [connectionTestDevice, setConnectionTestDevice] = useState<Device | null>(null);
  const [connectionTestMode, setConnectionTestMode] = useState<'quick' | 'deep'>('quick');
  const [connectionTestingDeviceId, setConnectionTestingDeviceId] = useState<string | null>(null);
  const [deviceConnectionChecks, setDeviceConnectionChecks] = useState<Record<string, DeviceConnectionCheckSummary>>({});

  const [snmpTestingId, setSnmpTestingId] = useState<string | null>(null);
  const [snmpSyncingId, setSnmpSyncingId] = useState<string | null>(null);
  const [snmpTestResult, setSnmpTestResult] = useState<any>(null);
  const [showSnmpTestResult, setShowSnmpTestResult] = useState(false);

  const [showTestResult, setShowTestResult] = useState(false);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);

  const handleTestConnection = useCallback(async (
    deviceToTest: Device | null = selectedDevice,
    mode: 'quick' | 'deep' = 'quick',
  ) => {
    if (!deviceToTest) return;
    setIsTestingConnection(true);
    setTestResult(null);
    setConnectionTestDevice(deviceToTest);
    setConnectionTestMode(mode);
    setConnectionTestingDeviceId(deviceToTest.id);
    setShowTestResult(true);
    try {
      const response = await fetch('/api/devices/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          device_id: deviceToTest.id,
          hostname: deviceToTest.hostname,
          ip_address: deviceToTest.ip_address,
          username: deviceToTest.username,
          password: deviceToTest.password,
          method: deviceToTest.connection_method,
          platform: deviceToTest.platform,
          check_mode: mode,
        }),
      });
      const data = await response.json();
      if (response.ok) {
        const stages = Array.isArray(data.stages) ? data.stages : [];
        const summary: DeviceConnectionCheckSummary = {
          status: buildConnectionCheckStatus(true, mode, undefined, stages),
          mode,
          checked_at: new Date().toISOString(),
        };
        setDeviceConnectionChecks((prev) => ({ ...prev, [deviceToTest.id]: summary }));
        setTestResult({ success: true, message: data.message, output: data.output, checkMode: data.check_mode, stages });
      } else {
        const stages = Array.isArray(data.stages) ? data.stages : [];
        const summary: DeviceConnectionCheckSummary = {
          status: buildConnectionCheckStatus(false, mode, data.error_code, stages),
          mode,
          checked_at: new Date().toISOString(),
          error_code: data.error_code,
        };
        setDeviceConnectionChecks((prev) => ({ ...prev, [deviceToTest.id]: summary }));
        setTestResult({
          success: false,
          message: buildConnectionTestMessage(data.detail || data.error, data.error_code),
          output: data.output,
          rawError: data.raw_error,
          errorCode: data.error_code,
          checkMode: data.check_mode,
          stages,
        });
      }
    } catch (error: any) {
      setDeviceConnectionChecks((prev) => ({
        ...prev,
        [deviceToTest.id]: {
          status: 'fail',
          mode,
          checked_at: new Date().toISOString(),
        },
      }));
      setTestResult({ success: false, message: error.message || 'Network error' });
    } finally {
      setIsTestingConnection(false);
      setConnectionTestingDeviceId(null);
    }
  }, [selectedDevice]);

  const handleSnmpTest = useCallback(async (deviceId: string) => {
    setSnmpTestingId(deviceId);
    setSnmpTestResult(null);
    setShowSnmpTestResult(true);
    try {
      const resp = await fetch(`/api/devices/${deviceId}/snmp-test`, { method: 'POST' });
      const data = await resp.json();
      setSnmpTestResult(data);
      if (data.success) {
        if (data.sys_name) {
          setDevices((prev) => prev.map((d) => (d.id !== deviceId ? d : { ...d, hostname: d.hostname || data.sys_name })));
        }
        setTimeout(() => fetchDevicesData(), 5000);
      }
    } catch (err: any) {
      setSnmpTestResult({ success: false, error: err.message || 'Network error' });
    } finally {
      setSnmpTestingId(null);
    }
  }, [setDevices, fetchDevicesData]);

  const handleSnmpSyncNow = useCallback(async (deviceId: string) => {
    setSnmpSyncingId(deviceId);
    try {
      const resp = await fetch(`/api/devices/${deviceId}/snmp-test`, { method: 'POST' });
      const data = await resp.json();
      if (!resp.ok || !data.success) {
        showToast(language === 'zh' ? 'SNMP 立即同步失败' : 'SNMP sync failed', 'error');
        return;
      }
      await fetchDevicesData();
      showToast(language === 'zh' ? 'SNMP 信息已更新' : 'SNMP data refreshed', 'success');
    } catch {
      showToast(language === 'zh' ? 'SNMP 立即同步失败' : 'SNMP sync failed', 'error');
    } finally {
      setSnmpSyncingId(null);
    }
  }, [language, showToast, fetchDevicesData]);

  return {
    isTestingConnection,
    connectionTestDevice,
    connectionTestMode,
    connectionTestingDeviceId,
    deviceConnectionChecks,
    snmpTestingId,
    snmpSyncingId,
    snmpTestResult,
    setSnmpTestResult,
    showSnmpTestResult,
    setShowSnmpTestResult,
    showTestResult,
    setShowTestResult,
    testResult,
    handleTestConnection,
    handleSnmpTest,
    handleSnmpSyncNow,
  };
};
