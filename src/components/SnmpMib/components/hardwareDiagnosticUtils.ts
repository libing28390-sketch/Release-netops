import type { SnmpHardwareDiscoveryTestResult } from './hardwareDiagnosticTypes';

const SENSITIVE_FIELD = /community|password|passwd|secret|token|authorization|credential|private[_-]?key/i;
const SENSITIVE_ASSIGNMENT = /(\b(?:snmp[_\s-]*community|api[_\s-]*token|community|password|passwd|token|secret|authorization|credential)\b\s*[:=]\s*)(?:"[^"]*"|'[^']*'|(?:Bearer|Basic)\s+[^\s,;]+|[^\s,;]+)/gi;

export const redactHardwareDiagnosticText = (value: string): string =>
  value.replace(SENSITIVE_ASSIGNMENT, '$1[REDACTED]');

const errorStates = new Set([
  'binding_conflict',
  'sync_failed',
  'credential_unavailable',
  'not_configured',
  'engine_unavailable',
  'unavailable',
]);

export const getHardwareDiscoveryToast = (
  result: SnmpHardwareDiscoveryTestResult,
  zh: boolean,
): { message: string; type: 'success' | 'error' | 'info' } => {
  const state = String(result.state || 'unknown').toLowerCase();
  const localSource = result.source === 'nexora_snmp';
  const sensorCount = Number.isFinite(result.sensor_count) ? result.sensor_count : 0;
  const freshCount = (result.metric_summary || []).reduce(
    (count, metric) => count + (Number.isFinite(metric.fresh_count) ? metric.fresh_count : 0),
    0,
  );
  const freshSensorCount = (result.hardware_sensors || []).filter(
    sensor => sensor.value_status === 'available' && sensor.freshness === 'fresh',
  ).length;
  const computeRows = [...(result.processor_sensors || []), ...(result.memory_pools || [])];
  const freshComputeRows = computeRows.filter(row => row.value_status === 'available' && row.freshness === 'fresh').length;
  const visibleFreshCount = freshCount || freshSensorCount + freshComputeRows;
  const hasFreshResult = visibleFreshCount > 0;
  const nativeRowCount = sensorCount || (result.hardware_sensors || []).length + computeRows.length;

  if (errorStates.has(state)) {
    return {
      message: zh
        ? `${localSource ? 'Nexora 本地硬件结果读取异常' : 'LibreNMS 原生结果读取异常'}：${redactHardwareDiagnosticText(result.message || state)}`
        : `${localSource ? 'Nexora local hardware result could not be read' : 'LibreNMS native result could not be read'}: ${redactHardwareDiagnosticText(result.message || state)}`,
      type: 'error',
    };
  }
  if (state === 'available' && hasFreshResult) {
    return {
      message: zh
        ? `${result.binding_resolution?.status === 'bound' ? '已按唯一管理 IP 自动关联；' : ''}已读取${localSource ? ' Nexora 本地 SNMP' : ' LibreNMS 原生'}结果：${nativeRowCount} 个传感器/采样行，${visibleFreshCount} 个有新鲜数值`
        : `${result.binding_resolution?.status === 'bound' ? 'Automatically linked by unique management IP; ' : ''}${localSource ? 'Nexora local SNMP' : 'LibreNMS native'} results loaded: ${nativeRowCount} sensor/sample rows, ${visibleFreshCount} with fresh values`,
      type: 'success',
    };
  }
  if (state === 'available') {
    return {
      message: zh
        ? `已读取${localSource ? ' Nexora 本地 SNMP' : ' LibreNMS 原生'}结果：${nativeRowCount} 个传感器/采样行；当前数值已过期或时间未知`
        : `${localSource ? 'Nexora local SNMP' : 'LibreNMS native'} results loaded: ${nativeRowCount} sensor/sample rows; values are stale or their timestamps are unknown`,
      type: 'info',
    };
  }

  const messages: Record<string, [string, string]> = {
    not_bound: ['该设备尚未绑定 LibreNMS 原生实例', 'This device is not bound to a native LibreNMS instance'],
    disabled: ['LibreNMS 资产绑定已停用', 'The LibreNMS device binding is disabled'],
    sync_pending: ['LibreNMS 设备关联尚未同步完成', 'The LibreNMS device binding is not synchronized yet'],
    instance_disabled: ['LibreNMS 实例已停用', 'The LibreNMS instance is disabled'],
    native_device_missing: ['绑定尚未关联 LibreNMS 原生设备', 'The binding has no native LibreNMS device'],
    metadata_only: ['已读取 LibreNMS 硬件元数据，当前没有可用数值样本', 'LibreNMS hardware metadata is available, but there are no numeric samples'],
    no_native_hardware_data: ['LibreNMS 当前没有返回硬件实体', 'LibreNMS returned no hardware entities'],
    pending: ['Nexora 本地 SNMP 硬件采集等待完成', 'Nexora local SNMP hardware collection is pending'],
    not_configured: ['Nexora 未配置设备 SNMP 凭据', 'Device SNMP credentials are not configured in Nexora'],
  };
  const safeMessage = redactHardwareDiagnosticText(result.message || '');
  if (localSource && safeMessage) return { message: safeMessage, type: state === 'not_configured' ? 'error' : 'info' };
  if (state === 'not_bound' && safeMessage) return { message: safeMessage, type: 'info' };
  const fallback = messages[state] || [safeMessage || '未知状态', safeMessage || 'Unknown state'];
  return { message: zh ? fallback[0] : fallback[1], type: 'info' };
};

const sanitizeShareValue = (value: unknown): unknown => {
  if (typeof value === 'string') return redactHardwareDiagnosticText(value);
  if (Array.isArray(value)) return value.map(sanitizeShareValue);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([key]) => !SENSITIVE_FIELD.test(key))
        .map(([key, nested]) => [key, sanitizeShareValue(nested)]),
    );
  }
  return value;
};

/** Builds a credential-free hardware-result export and caps sensor detail size. */
export const buildHardwareDiagnosticSharePayload = (result: SnmpHardwareDiscoveryTestResult): string => {
  const sensors = result.hardware_sensors || [];
  const payload = {
    source: result.source,
    state: result.state,
    message: result.message,
    matched_device_id: result.matched_device_id,
    matched_hostname: result.matched_hostname,
    binding_resolution: result.binding_resolution,
    binding: result.binding,
    engine: result.engine,
    identity: result.identity,
    collection: result.collection,
    health_graphs: result.health_graphs || [],
    metric_summary: result.metric_summary || [],
    processor_sensors: result.processor_sensors || [],
    memory_pools: result.memory_pools || [],
    hardware_sensors: sensors.slice(0, 100),
    hardware_sensors_omitted: Math.max(0, sensors.length - 100),
    transceivers: (result.transceivers || []).slice(0, 100),
    wireless_sensors: (result.wireless_sensors || []).slice(0, 100),
  };

  return JSON.stringify(sanitizeShareValue(payload), null, 2);
};
