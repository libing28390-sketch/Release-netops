const VENDOR_ALIASES: Array<[string, string]> = [
  ['huawei', 'huawei'],
  ['华为', 'huawei'],
  ['h3c', 'h3c'],
  ['hpcomware', 'h3c'],
  ['hp', 'h3c'],
  ['华三', 'h3c'],
  ['cisco', 'cisco'],
  ['思科', 'cisco'],
  ['juniper', 'juniper'],
  ['junos', 'juniper'],
  ['瞻博', 'juniper'],
  ['arista', 'arista'],
  ['ruijie', 'ruijie'],
  ['锐捷', 'ruijie'],
  ['zte', 'zte'],
  ['中兴', 'zte'],
  ['maipu', 'maipu'],
  ['迈普', 'maipu'],
  ['dptech', 'dptech'],
  ['迪普', 'dptech'],
  ['raisecom', 'raisecom'],
  ['瑞斯康达', 'raisecom'],
  ['fortinet', 'fortinet'],
  ['飞塔', 'fortinet'],
];

const compact = (value: unknown) => String(value ?? '').trim().toLowerCase().replace(/[\s_\-./]+/g, '');

export const normalizePlatformVendor = (value: unknown): string => {
  const normalized = compact(value);
  if (['', 'unknown', 'generic', 'none', 'null', 'na', 'n/a', 'unassigned'].includes(normalized)) return '';
  const match = [...VENDOR_ALIASES]
    .sort((left, right) => right[0].length - left[0].length)
    .find(([alias]) => normalized === compact(alias) || normalized.includes(compact(alias)));
  return match?.[1] || normalized;
};

export const inferPlatformVendor = (...values: unknown[]): string => {
  for (const value of values) {
    const vendor = normalizePlatformVendor(value);
    if (vendor) return vendor;
  }
  return '';
};

export const PLATFORM_VENDOR_LABELS: Record<string, { zh: string; en: string }> = {
  huawei: { zh: '华为', en: 'Huawei' },
  h3c: { zh: 'H3C', en: 'H3C' },
  cisco: { zh: 'Cisco', en: 'Cisco' },
  juniper: { zh: 'Juniper', en: 'Juniper' },
  arista: { zh: 'Arista', en: 'Arista' },
  ruijie: { zh: '锐捷', en: 'Ruijie' },
  zte: { zh: '中兴', en: 'ZTE' },
  maipu: { zh: '迈普', en: 'Maipu' },
  dptech: { zh: '迪普', en: 'DPTech' },
  raisecom: { zh: '瑞斯康达', en: 'Raisecom' },
  fortinet: { zh: 'Fortinet', en: 'Fortinet' },
};

export const platformVendorLabel = (value: unknown, language: string): string => {
  const normalized = normalizePlatformVendor(value);
  const labels = PLATFORM_VENDOR_LABELS[normalized];
  return language === 'zh' ? (labels?.zh || normalized || '未知厂商') : (labels?.en || normalized || 'Unknown vendor');
};
