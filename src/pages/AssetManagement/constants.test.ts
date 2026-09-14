import { describe, expect, it } from 'vitest';
import {
  ALL_VENDOR_NAMES,
  COL_MAP,
  IMPORT_VALUE_MAP,
  NETWORK_IMPORT_PLATFORM_VALUES,
  NETWORK_IMPORT_VENDOR_VALUES,
  NETWORK_TOPOLOGY_ROLE_OPTIONS,
  TOPOLOGY_FUNCTION_OPTIONS,
  TOPOLOGY_ZONE_OPTIONS,
  NETWORK_VENDOR_GROUPS,
  VENDOR_PLATFORMS,
  getPlatformsForVendor,
  isNetworkVendor,
  isValidVendorPlatform,
  SERVER_ONLY_VENDOR_VALUES,
  SSH_ALGORITHM_PROFILE_OPTIONS,
} from './constants';

describe('asset vendor catalog', () => {
  it('contains network and security vendor groups used by asset forms', () => {
    expect(NETWORK_VENDOR_GROUPS.map((group) => group.key)).toEqual(['network', 'security']);
    expect(ALL_VENDOR_NAMES).toContain('FiberHome');
    expect(ALL_VENDOR_NAMES).toContain('Raisecom');
    expect(ALL_VENDOR_NAMES).toContain('Hillstone');
    expect(ALL_VENDOR_NAMES).toContain('Sangfor');
    expect(ALL_VENDOR_NAMES).toContain('Check Point');
    expect(NETWORK_IMPORT_VENDOR_VALUES).toContain('山石');
    expect(NETWORK_IMPORT_VENDOR_VALUES).toContain('Hillstone');
    expect(NETWORK_IMPORT_VENDOR_VALUES).not.toContain('HP');
    expect(NETWORK_IMPORT_VENDOR_VALUES).not.toContain('Lenovo');
    expect(NETWORK_IMPORT_VENDOR_VALUES).not.toContain('Inspur');
    expect(NETWORK_IMPORT_VENDOR_VALUES).not.toContain('Generic Server');
  });

  it('provides a platform identity for the newly catalogued vendors', () => {
    expect(VENDOR_PLATFORMS.DCN[0].value).toBe('dcn_network');
    expect(VENDOR_PLATFORMS.Raisecom[0].value).toBe('raisecom_ros');
    expect(VENDOR_PLATFORMS.FiberHome[0].value).toBe('fiberhome_fengine');
    expect(VENDOR_PLATFORMS.Hillstone[0].value).toBe('hillstone_stoneos');
    expect(VENDOR_PLATFORMS['Qi An Xin'][0].value).toBe('qianxin_firewall');
    expect(NETWORK_IMPORT_PLATFORM_VALUES).toContain('hillstone_stoneos');
    expect(IMPORT_VALUE_MAP.vendor['山石']).toBe('Hillstone');
    expect(IMPORT_VALUE_MAP.vendor['瑞斯康达']).toBe('Raisecom');
    expect(IMPORT_VALUE_MAP.platform['瑞斯康达 ROS']).toBe('raisecom_ros');
    expect(IMPORT_VALUE_MAP.platform['Hillstone StoneOS']).toBe('hillstone_stoneos');
  });

  it('keeps network platform options scoped to the selected vendor', () => {
    expect(getPlatformsForVendor('山石').map(option => option.value)).toEqual(['hillstone_stoneos']);
    expect(getPlatformsForVendor('Cisco').map(option => option.value)).toContain('cisco_ios');
    expect(getPlatformsForVendor('Cisco').map(option => option.value)).not.toContain('linux');
    expect(isNetworkVendor('山石')).toBe(true);
    expect(isNetworkVendor('HP')).toBe(false);
    expect(SERVER_ONLY_VENDOR_VALUES).toContain('HP');
    expect(isValidVendorPlatform('network_device', 'Cisco', 'cisco_ios')).toBe(true);
    expect(isValidVendorPlatform('network_device', 'Cisco', 'linux')).toBe(false);
    expect(isValidVendorPlatform('server', 'HP', 'linux')).toBe(true);
  });
});

describe('asset import role header contract', () => {
  it('accepts both display and API-style role headers', () => {
    expect(COL_MAP.Role).toBe('device_role');
    expect(COL_MAP['拓扑角色']).toBe('device_role');
    expect(COL_MAP.role).toBe('device_role');
    expect(COL_MAP.device_role).toBe('device_role');
  });

  it('accepts named SNMP credential headers without colliding with SSH credentials', () => {
    expect(COL_MAP['SNMP凭据']).toBe('snmp_credential_name');
    expect(COL_MAP['SNMP凭据（推荐）']).toBe('snmp_credential_name');
    expect(COL_MAP['SNMP Credential']).toBe('snmp_credential_name');
    expect(COL_MAP['SNMP Credential (recommended)']).toBe('snmp_credential_name');
    expect(COL_MAP.snmp_credential_name).toBe('snmp_credential_name');
    expect(COL_MAP['SNMP凭据ID']).toBe('snmp_credential_id');
    expect(COL_MAP['绑定凭据']).toBe('credential_id');
    expect(IMPORT_VALUE_MAP.connection_method['Web管理']).toBe('web');
    expect(IMPORT_VALUE_MAP.connection_method['Web Management']).toBe('web');
  });

  it('uses one role vocabulary across import, editing, and topology filters', () => {
    expect(IMPORT_VALUE_MAP.device_role['核心层']).toBe('core');
    expect(IMPORT_VALUE_MAP.device_role['汇聚层']).toBe('distribution');
    expect(IMPORT_VALUE_MAP.device_role['接入层']).toBe('access');
    expect(IMPORT_VALUE_MAP.device_role['核心交换机']).toBeUndefined();
    expect(NETWORK_TOPOLOGY_ROLE_OPTIONS.map(option => option.value)).toContain('core');
    expect(NETWORK_TOPOLOGY_ROLE_OPTIONS.map(option => option.value)).not.toContain('core_switch');
  });

  it('normalizes function and zone dropdown labels to canonical values', () => {
    expect(IMPORT_VALUE_MAP.function['园区核心']).toBe('Campus Core');
    expect(IMPORT_VALUE_MAP.zone['生产区']).toBe('Production');
    expect(TOPOLOGY_FUNCTION_OPTIONS.some(option => option.value === 'Campus Core')).toBe(true);
    expect(TOPOLOGY_ZONE_OPTIONS.some(option => option.value === 'Production')).toBe(true);
  });

  it('keeps SSH algorithm profiles vendor-neutral and importable', () => {
    expect(SSH_ALGORITHM_PROFILE_OPTIONS.map(option => option.value)).toEqual([
      'auto', 'modern', 'legacy_compat', 'legacy_break_glass',
    ]);
    expect(COL_MAP['SSH算法策略']).toBe('ssh_algorithm_profile');
    expect(COL_MAP['SSH Algorithm Profile']).toBe('ssh_algorithm_profile');
    expect(IMPORT_VALUE_MAP.ssh_algorithm_profile['兼容旧算法']).toBe('legacy_compat');
    expect(IMPORT_VALUE_MAP.ssh_algorithm_profile['Legacy Break Glass']).toBe('legacy_break_glass');
  });
});
