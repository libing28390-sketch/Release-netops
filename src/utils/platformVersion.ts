import {
  getEditorSelection,
  getPlatformFamilyOption,
  getVendorOption,
  TEXTFSM_VERSION_LABELS,
} from '../pages/textfsmPlatformCatalog';
import type { PlatformProfileOption } from '../components/PlatformProfileSelector';

type PlatformProfileVersionSource = Partial<Pick<PlatformProfileOption, 'platform_code'>> & {
  id?: string;
  name_zh?: string;
  name_en?: string;
  vendor?: string;
  version?: string;
  adaptation_version?: string;
};

/** Extract a confident software major from a vendor-specific version string. */
export const extractSoftwareMajorVersion = (value: unknown): number | null => {
  const normalized = String(value ?? '').trim().toLowerCase();
  if (!normalized || ['unknown', 'common', 'none', 'null', 'na', 'n/a', '-'].includes(normalized)) return null;

  // Some vendors put a product train before the actual software major (for
  // example ZTE's `5900 V6.00...`). Prefer an explicit V-prefixed release
  // in those formats before applying the generic numeric fallback below.
  const explicitRelease = normalized.match(/\b(?:5900|5960|zsrv2)\s+v\s*(\d+)(?=[.\s(_-]|$)/i)
    || normalized.match(/\b(?:eg[_ -]?rgos|rgos|comware|vrp|ios|nxos|xe)\s*[_ -]?\s*v?\s*(\d+)(?=[.\s(_-]|$)/i)
    || normalized.match(/\bv\s*(\d+)(?=[.\s(_-]|$)/i);
  if (explicitRelease) return Number(explicitRelease[1]);

  const match = normalized.match(/(?:^|[^a-z0-9])(?:v|version|software(?:\s+version)?|eg[_ -]?rgos|rgos|comware|vrp|ios|nxos|xe)?\s*[_-]?\s*(\d+)(?=[.\s(_-]|$)/i);
  return match ? Number(match[1]) : null;
};

/** Resolve the Profile's command/parser adaptation label. */
export const getProfileAdaptationVersion = (profile: PlatformProfileVersionSource): string => {
  const explicit = String(profile.adaptation_version || '').trim().toLowerCase();
  const profileCode = String(profile.platform_code || profile.id || '').trim().replace(/^system-profile-/i, '');
  const version = explicit || getEditorSelection(profileCode, profile.version).version;
  return version || 'common';
};

/** Resolve the Profile's command/parser adaptation major, if it is versioned. */
export const getProfileAdaptationMajorVersion = (profile: PlatformProfileVersionSource): number | null => {
  const version = getProfileAdaptationVersion(profile);
  const match = String(version || '').trim().toLowerCase().match(/^v(\d+)$/);
  return match ? Number(match[1]) : null;
};

/**
 * Return a human-readable binding label even when an older API only returns
 * the internal ``system-profile-*`` id.  Internal IDs are useful for writes
 * and diagnostics, but should never be the primary label in inventory UI.
 */
export const getPlatformProfileDisplayLabel = (
  profile: PlatformProfileVersionSource | null | undefined,
  fallbackProfileId: string | null | undefined,
  language: string,
): string => {
  const source = profile || {};
  const explicit = String((language === 'zh' ? source.name_zh : source.name_en) || '').trim();
  if (explicit) return explicit;

  const profileCode = String(source.platform_code || source.id || fallbackProfileId || '')
    .trim()
    .replace(/^system-profile-/i, '');
  if (!profileCode) return '';

  const selection = getEditorSelection(profileCode, source.version || source.adaptation_version);
  const family = getPlatformFamilyOption(selection.platformFamily);
  const vendor = getVendorOption(selection.vendor);
  const familyLabel = language === 'zh'
    ? (family?.label || selection.platformFamily)
    : (family?.labelEn || selection.platformFamily);
  const vendorLabel = language === 'zh'
    ? (vendor?.label || selection.vendor)
    : (vendor?.labelEn || selection.vendor);
  const version = getProfileAdaptationVersion({
    platform_code: profileCode,
    version: source.version,
    adaptation_version: source.adaptation_version,
  });
  const versionLabel = TEXTFSM_VERSION_LABELS[version]
    ? (language === 'zh' ? TEXTFSM_VERSION_LABELS[version].label : TEXTFSM_VERSION_LABELS[version].labelEn)
    : version.toUpperCase();
  const suffix = version && !['common'].includes(version.toLowerCase()) ? ` ${versionLabel}` : '';
  return [vendorLabel, familyLabel].filter(Boolean).join(' ') + suffix;
};

export interface DevicePlatformAdaptationSummary {
  label: string;
  version: string;
  major: number | null;
  explicit: boolean;
}

/**
 * Resolve the label shown for every device, including legacy rows that have
 * no explicit ``platform_profile_id``.  Legacy rows use the platform family
 * plus a reliable software major as the default adaptation; they are marked
 * as defaults so operators can tell them apart from a manual Profile bind.
 */
export const getDevicePlatformAdaptation = (
  device: {
    platform?: unknown;
    version?: unknown;
    platform_profile_id?: string | null;
    platform_binding?: PlatformProfileVersionSource | null;
  },
  language: string,
): DevicePlatformAdaptationSummary => {
  const explicit = Boolean(device.platform_profile_id || device.platform_binding);
  const profile = device.platform_binding || (device.platform_profile_id
    ? { id: device.platform_profile_id, platform_code: '' }
    : null);
  if (profile) {
    return {
      label: getPlatformProfileDisplayLabel(profile, device.platform_profile_id, language),
      version: getProfileAdaptationVersion(profile),
      major: getProfileAdaptationMajorVersion(profile),
      explicit,
    };
  }

  const platform = String(device.platform || '').trim();
  if (!platform) {
    return { label: language === 'zh' ? '待自动识别' : 'Awaiting detection', version: '', major: null, explicit: false };
  }
  const softwareMajor = extractSoftwareMajorVersion(device.version);
  const selection = getEditorSelection(platform, softwareMajor === null ? undefined : `v${softwareMajor}`);
  const defaultProfile = { platform_code: selection.platformFamily, version: selection.version };
  return {
    label: getPlatformProfileDisplayLabel(defaultProfile, undefined, language),
    version: getProfileAdaptationVersion(defaultProfile),
    major: getProfileAdaptationMajorVersion(defaultProfile),
    explicit: false,
  };
};
