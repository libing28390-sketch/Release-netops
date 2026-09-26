export interface ConfigBackupCommands {
  running: string;
  startup: string;
}

const DEFAULT_COMMANDS: Record<string, ConfigBackupCommands> = {
  cisco: { running: 'show running-config', startup: 'show startup-config' },
  huawei: { running: 'display current-configuration', startup: 'display saved-configuration' },
  h3c: { running: 'display current-configuration', startup: 'display saved-configuration' },
  juniper: { running: 'show configuration', startup: 'show configuration' },
  arista: { running: 'show running-config', startup: 'show startup-config' },
  ruijie: { running: 'show running-config', startup: 'show startup-config' },
  zte: { running: 'show running-config', startup: 'show startup-config' },
  raisecom: { running: 'show running-config', startup: 'show startup-config' },
  dptech: { running: 'display current-configuration', startup: 'display saved-configuration' },
  maipu: { running: 'show running-config', startup: 'show startup-config' },
  fortinet: { running: 'show full-configuration', startup: 'show full-configuration' },
  hillstone: { running: 'show configuration running', startup: 'show configuration startup' },
};

const VENDOR_ALIASES: Array<[string, string[]]> = [
  ['cisco', ['cisco', '思科']],
  ['huawei', ['huawei', '华为', 'vrp']],
  ['h3c', ['h3c', 'comware', '华三']],
  ['juniper', ['juniper', 'junos']],
  ['arista', ['arista', 'eos']],
  ['ruijie', ['ruijie', '锐捷', 'rgos']],
  ['zte', ['zte', '中兴', 'zxros']],
  ['raisecom', ['raisecom', '瑞斯康达']],
  ['dptech', ['dptech', '迪普']],
  ['maipu', ['maipu', '迈普', 'mypower']],
  ['fortinet', ['fortinet', 'fortigate', 'fortios']],
  ['hillstone', ['hillstone', 'stoneos', '山石']],
];

const PLATFORM_ALIASES: Array<[string, string[]]> = [
  ['cisco', ['cisco_ios', 'cisco_nxos']],
  ['huawei', ['huawei_vrp', 'vrp']],
  ['h3c', ['h3c_comware', 'hp_comware', 'comware']],
  ['juniper', ['juniper_junos', 'junos']],
  ['arista', ['arista_eos', 'eos']],
  ['ruijie', ['ruijie_rgos', 'ruijie_os', 'rgos']],
  ['zte', ['zte_zxros', 'zte_5900', 'zxros']],
  ['raisecom', ['raisecom_ros']],
  ['dptech', ['dptech', 'conplat']],
  ['maipu', ['maipu', 'mypower']],
  ['fortinet', ['fortinet', 'fortios', 'fortigate']],
  ['hillstone', ['hillstone_stoneos', 'hillstone', 'stoneos', '山石']],
];

function normalize(value?: string | null): string {
  return String(value || '').trim().toLowerCase().replace(/[-\s]/g, '_');
}

function findKey(value: string, aliases: Array<[string, string[]]>): string | undefined {
  const normalized = normalize(value);
  if (!normalized) return undefined;
  const valueTokens = normalized.split('_').filter(Boolean);
  const matches = (name: string) => {
    if ([...name].some((char) => char.charCodeAt(0) > 127)) return normalized.includes(name);
    const nameTokens = name.split('_').filter(Boolean);
    return valueTokens.some((_, index) =>
      nameTokens.every((token, offset) => valueTokens[index + offset] === token),
    );
  };
  return aliases.find(([, names]) => names.some(matches))?.[0];
}

/**
 * Resolve default backup commands from the vendor first. The platform is only
 * consulted when the vendor is empty or the inventory's generic "Other" value.
 */
export function getDefaultConfigBackupCommands(
  vendor?: string | null,
  platform?: string | null,
): ConfigBackupCommands | null {
  const vendorValue = normalize(vendor);
  const vendorKey = findKey(vendorValue, VENDOR_ALIASES);
  if (vendorKey) return DEFAULT_COMMANDS[vendorKey];
  if (vendorValue && vendorValue !== 'other') return null;

  const platformKey = findKey(normalize(platform), PLATFORM_ALIASES);
  return platformKey ? DEFAULT_COMMANDS[platformKey] : null;
}
