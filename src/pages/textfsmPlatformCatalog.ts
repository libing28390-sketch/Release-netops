export interface TextFSMVendorOption {
  value: string;
  label: string;
  labelEn: string;
}

export interface TextFSMPlatformFamilyOption {
  value: string;
  vendor: string;
  label: string;
  labelEn: string;
  versions: string[];
}

export const TEXTFSM_VENDOR_OPTIONS: TextFSMVendorOption[] = [
  { value: 'cisco', label: '思科', labelEn: 'Cisco' },
  { value: 'huawei', label: '华为', labelEn: 'Huawei' },
  { value: 'h3c', label: '华三', labelEn: 'H3C' },
  { value: 'juniper', label: 'Juniper', labelEn: 'Juniper' },
  { value: 'arista', label: 'Arista', labelEn: 'Arista' },
  { value: 'ruijie', label: '锐捷', labelEn: 'Ruijie' },
  { value: 'zte', label: '中兴', labelEn: 'ZTE' },
  { value: 'dptech', label: '迪普', labelEn: 'DPTech' },
  { value: 'maipu', label: '迈普', labelEn: 'Maipu' },
  { value: 'paloalto', label: 'Palo Alto', labelEn: 'Palo Alto' },
  { value: 'fortinet', label: 'Fortinet', labelEn: 'Fortinet' },
  { value: 'hillstone', label: '山石', labelEn: 'Hillstone' },
];

export const TEXTFSM_PLATFORM_FAMILIES: TextFSMPlatformFamilyOption[] = [
  { value: 'cisco_ios', vendor: 'cisco', label: 'IOS', labelEn: 'IOS', versions: ['common'] },
  { value: 'cisco_xe', vendor: 'cisco', label: 'IOS-XE', labelEn: 'IOS-XE', versions: ['common'] },
  { value: 'cisco_nxos', vendor: 'cisco', label: 'NX-OS', labelEn: 'NX-OS', versions: ['common'] },
  { value: 'cisco_xr', vendor: 'cisco', label: 'IOS-XR', labelEn: 'IOS-XR', versions: ['common'] },
  { value: 'cisco_asa', vendor: 'cisco', label: 'ASA', labelEn: 'ASA', versions: ['common'] },
  { value: 'huawei_vrp', vendor: 'huawei', label: 'VRP', labelEn: 'VRP', versions: ['v5', 'v8', 'unknown'] },
  {
    value: 'h3c_comware',
    vendor: 'h3c',
    label: 'Comware',
    labelEn: 'Comware',
    versions: ['common', 'v3', 'v5', 'v7', 'v9', 'unknown'],
  },
  { value: 'juniper_junos', vendor: 'juniper', label: 'JunOS', labelEn: 'JunOS', versions: ['common'] },
  { value: 'arista_eos', vendor: 'arista', label: 'EOS', labelEn: 'EOS', versions: ['common'] },
  {
    value: 'ruijie_rgos',
    vendor: 'ruijie',
    label: 'RGOS',
    labelEn: 'RGOS',
    versions: ['common', 'v10', 'v11', 'v12', 'unknown'],
  },
  { value: 'zte_zxros', vendor: 'zte', label: 'ZXROS', labelEn: 'ZXROS', versions: ['common'] },
  { value: 'zte_rosng', vendor: 'zte', label: 'ROSng', labelEn: 'ROSng', versions: ['common'] },
  { value: 'zte_os_unknown', vendor: 'zte', label: '未知系统', labelEn: 'Unknown OS', versions: ['common'] },
  { value: 'dptech_conplat', vendor: 'dptech', label: 'ConPlat', labelEn: 'ConPlat', versions: ['common'] },
  {
    value: 'dptech_conplat_unknown',
    vendor: 'dptech',
    label: '未知系统',
    labelEn: 'Unknown OS',
    versions: ['common'],
  },
  {
    value: 'maipu_mypower',
    vendor: 'maipu',
    label: 'MyPower',
    labelEn: 'MyPower',
    versions: ['common', 'v6', 'v8', 'v9', 'unknown'],
  },
  { value: 'paloalto_panos', vendor: 'paloalto', label: 'PAN-OS', labelEn: 'PAN-OS', versions: ['common'] },
  { value: 'fortinet', vendor: 'fortinet', label: 'FortiOS', labelEn: 'FortiOS', versions: ['common'] },
  { value: 'hillstone_stoneos', vendor: 'hillstone', label: 'StoneOS', labelEn: 'StoneOS', versions: ['common'] },
];

export const TEXTFSM_VERSION_LABELS: Record<string, { label: string; labelEn: string }> = {
  common: { label: '通用', labelEn: 'Common' },
  v5: { label: 'V5', labelEn: 'V5' },
  v3: { label: 'V3', labelEn: 'V3' },
  v6: { label: 'V6', labelEn: 'V6' },
  v7: { label: 'V7', labelEn: 'V7' },
  v8: { label: 'V8', labelEn: 'V8' },
  v9: { label: 'V9', labelEn: 'V9' },
  v10: { label: 'V10', labelEn: 'V10' },
  v11: { label: 'V11', labelEn: 'V11' },
  v12: { label: 'V12', labelEn: 'V12' },
  unknown: { label: '未知', labelEn: 'Unknown' },
};

const CONCRETE_PLATFORM_BY_SELECTION: Record<string, string> = {
  'huawei_vrp:v5': 'huawei_vrp5',
  'huawei_vrp:v8': 'huawei_vrp8',
  'huawei_vrp:unknown': 'huawei_vrp_unknown',
  'h3c_comware:v5': 'h3c_comware_v5',
  'h3c_comware:v3': 'h3c_comware_v3',
  'h3c_comware:v7': 'h3c_comware_v7',
  'h3c_comware:v9': 'h3c_comware_v9',
  'h3c_comware:unknown': 'h3c_comware_unknown',
  'maipu_mypower:v6': 'maipu_mypower_v6',
  'maipu_mypower:v8': 'maipu_mypower_v8',
  'maipu_mypower:v9': 'maipu_mypower_v9',
  'maipu_mypower:unknown': 'maipu_mypower_unknown',
  'ruijie_rgos:v10': 'ruijie_rgos_v10',
  'ruijie_rgos:v11': 'ruijie_rgos_v11',
  'ruijie_rgos:v12': 'ruijie_rgos_v12',
  'ruijie_rgos:unknown': 'ruijie_rgos_unknown',
};

const LEGACY_PLATFORM_SELECTIONS: Record<string, { platformFamily: string; version: string }> = {
  huawei_vrp: { platformFamily: 'huawei_vrp', version: 'v5' },
  huawei_vrpv8: { platformFamily: 'huawei_vrp', version: 'v8' },
  huawei_vrp5: { platformFamily: 'huawei_vrp', version: 'v5' },
  huawei_vrp8: { platformFamily: 'huawei_vrp', version: 'v8' },
  huawei_vrp_unknown: { platformFamily: 'huawei_vrp', version: 'unknown' },
  hp_comware: { platformFamily: 'h3c_comware', version: 'v5' },
  h3c_comware_v3: { platformFamily: 'h3c_comware', version: 'v3' },
  h3c_comware: { platformFamily: 'h3c_comware', version: 'v7' },
  h3c_comware9: { platformFamily: 'h3c_comware', version: 'v9' },
  h3c_comware_v5: { platformFamily: 'h3c_comware', version: 'v5' },
  h3c_comware_v7: { platformFamily: 'h3c_comware', version: 'v7' },
  h3c_comware_v9: { platformFamily: 'h3c_comware', version: 'v9' },
  h3c_comware_unknown: { platformFamily: 'h3c_comware', version: 'unknown' },
  maipu: { platformFamily: 'maipu_mypower', version: 'common' },
  maipu_mypower: { platformFamily: 'maipu_mypower', version: 'common' },
  maipu_mypower_v6: { platformFamily: 'maipu_mypower', version: 'v6' },
  maipu_mypower_v8: { platformFamily: 'maipu_mypower', version: 'v8' },
  maipu_mypower_v9: { platformFamily: 'maipu_mypower', version: 'v9' },
  maipu_mypower_unknown: { platformFamily: 'maipu_mypower', version: 'unknown' },
  ruijie_rgos_v10: { platformFamily: 'ruijie_rgos', version: 'v10' },
  ruijie_rgos_v11: { platformFamily: 'ruijie_rgos', version: 'v11' },
  ruijie_rgos_v12: { platformFamily: 'ruijie_rgos', version: 'v12' },
  ruijie_rgos_unknown: { platformFamily: 'ruijie_rgos', version: 'unknown' },
  ruijie_s6k_rgos12: { platformFamily: 'ruijie_rgos', version: 'v12' },
  ruijie_eg_rgos11: { platformFamily: 'ruijie_rgos', version: 'v11' },
  zte_zxros: { platformFamily: 'zte_zxros', version: 'common' },
  zte_5900_v6: { platformFamily: 'zte_zxros', version: 'common' },
  zte_zsrv2_v3: { platformFamily: 'zte_zxros', version: 'common' },
  zte_rosng: { platformFamily: 'zte_rosng', version: 'common' },
  zte_os_unknown: { platformFamily: 'zte_os_unknown', version: 'common' },
  dptech_ios: { platformFamily: 'dptech_conplat', version: 'common' },
  dptech_conplat: { platformFamily: 'dptech_conplat', version: 'common' },
  dptech_conplat_unknown: { platformFamily: 'dptech_conplat_unknown', version: 'common' },
  dptech_fw_s211: { platformFamily: 'dptech_conplat', version: 'common' },
  maipu_s3330_v9: { platformFamily: 'maipu_mypower', version: 'v9' },
};

export const getVendorOption = (value: string) => (
  TEXTFSM_VENDOR_OPTIONS.find((item) => item.value === value)
);

export const getPlatformFamilyOption = (value: string) => (
  TEXTFSM_PLATFORM_FAMILIES.find((item) => item.value === value)
);

export const getConcreteEditorPlatform = (platformFamily: string, version: string): string => (
  CONCRETE_PLATFORM_BY_SELECTION[`${platformFamily}:${version}`]
    || (platformFamily === 'maipu_mypower' && version === 'common' ? 'maipu' : platformFamily)
);

export const getEditorSelection = (platform: string, versionHint?: string) => {
  const normalizedPlatform = String(platform || '').trim().toLowerCase();
  const normalizedVersion = String(versionHint || '').trim().toLowerCase();
  const directSelection = LEGACY_PLATFORM_SELECTIONS[normalizedPlatform];
  let platformFamily = directSelection?.platformFamily || normalizedPlatform;
  let version = directSelection?.version || normalizedVersion;

  const family = getPlatformFamilyOption(platformFamily);
  const supportedVersions = family?.versions || ['common'];
  if (platformFamily === 'huawei_vrp' && !['v5', 'v8', 'unknown'].includes(version)) {
    version = 'v5';
  }
  if (!supportedVersions.includes(version)) version = supportedVersions[0] || 'common';

  return {
    vendor: family?.vendor || normalizedPlatform.split('_', 1)[0] || 'cisco',
    platformFamily: family?.value || platformFamily || 'cisco_ios',
    version,
  };
};

export const TEXTFSM_VERSION_ORDER = [
  'common', 'v3', 'v5', 'v6', 'v7', 'v8', 'v9', 'v10', 'v11', 'v12', 'unknown',
];
