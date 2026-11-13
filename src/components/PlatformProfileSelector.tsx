import React, { useEffect, useMemo, useState } from 'react';
import {
  getEditorSelection,
  getPlatformFamilyOption,
  getVendorOption,
  TEXTFSM_PLATFORM_FAMILIES,
  TEXTFSM_VENDOR_OPTIONS,
  TEXTFSM_VERSION_LABELS,
  TEXTFSM_VERSION_ORDER,
} from '../pages/textfsmPlatformCatalog';
import { normalizePlatformVendor, platformVendorLabel } from '../utils/platformVendor';

export interface PlatformProfileOption {
  id: string;
  platform_code: string;
  name_zh?: string;
  name_en?: string;
  vendor?: string;
  parser_platform?: string;
  source?: string;
  status?: string;
  catalog_vendor?: string;
  platform_family?: string;
  version?: string;
}

interface NormalizedProfile {
  profile: PlatformProfileOption;
  vendor: string;
  platformFamily: string;
  version: string;
}

interface PlatformProfileSelectorProps {
  profiles: PlatformProfileOption[];
  value: string;
  language: string;
  onChange: (profile: PlatformProfileOption | null) => void;
  disabled?: boolean;
  className?: string;
  title?: string;
  /** Restrict the selector to the vendor already identified on the device. */
  allowedVendor?: string;
  /** Hide all choices until a device vendor is known. */
  requireVendor?: boolean;
}

const normalizeProfile = (profile: PlatformProfileOption): NormalizedProfile => {
  const inferred = getEditorSelection(profile.platform_code, profile.version);
  return {
    profile,
    vendor: normalizePlatformVendor(profile.catalog_vendor || inferred.vendor || profile.vendor),
    platformFamily: String(profile.platform_family || inferred.platformFamily || profile.parser_platform || '').trim().toLowerCase(),
    version: String(profile.version || inferred.version || 'common').trim().toLowerCase(),
  };
};

const unique = (values: string[]) => Array.from(new Set(values.filter(Boolean)));

const vendorLabel = (value: string, language: string) => {
  const option = getVendorOption(value);
  return language === 'zh' ? (option?.label || value) : (option?.labelEn || value);
};

const familyLabel = (value: string, language: string) => {
  const option = getPlatformFamilyOption(value);
  return language === 'zh' ? (option?.label || value) : (option?.labelEn || value);
};

const versionLabel = (value: string, language: string) => {
  const option = TEXTFSM_VERSION_LABELS[value];
  return language === 'zh' ? (option?.label || value) : (option?.labelEn || value);
};

const PlatformProfileSelector: React.FC<PlatformProfileSelectorProps> = ({
  profiles,
  value,
  language,
  onChange,
  disabled = false,
  className = '',
  title,
  allowedVendor = '',
  requireVendor = false,
}) => {
  const normalizedProfiles = useMemo(() => profiles
    .filter((profile) => String(profile.status || 'ACTIVE').toUpperCase() !== 'ARCHIVED')
    .map(normalizeProfile), [profiles]);
  const normalizedAllowedVendor = normalizePlatformVendor(allowedVendor);
  const scopedProfiles = useMemo(() => normalizedProfiles.filter((item) => (
    requireVendor && !normalizedAllowedVendor
      ? false
      : !normalizedAllowedVendor || item.vendor === normalizedAllowedVendor
  )), [normalizedAllowedVendor, normalizedProfiles, requireVendor]);
  const selectedProfile = scopedProfiles.find((item) => item.profile.id === value);
  const [selection, setSelection] = useState({
    vendor: selectedProfile?.vendor || '',
    platformFamily: selectedProfile?.platformFamily || '',
    version: selectedProfile?.version || '',
  });

  useEffect(() => {
    const current = scopedProfiles.find((item) => item.profile.id === value);
    if (current) {
      setSelection({
        vendor: current.vendor,
        platformFamily: current.platformFamily,
        version: current.version,
      });
    } else if (normalizedAllowedVendor) {
      setSelection((previous) => previous.vendor === normalizedAllowedVendor
        ? previous
        : { vendor: normalizedAllowedVendor, platformFamily: '', version: '' });
    }
  }, [normalizedAllowedVendor, scopedProfiles, value]);

  const vendorValues = useMemo(() => {
    const available = new Set(scopedProfiles.map((item) => item.vendor));
    return [
      ...TEXTFSM_VENDOR_OPTIONS.map((item) => item.value).filter((item) => available.has(item)),
      ...unique(scopedProfiles.map((item) => item.vendor)).filter((item) => !TEXTFSM_VENDOR_OPTIONS.some((option) => option.value === item)),
    ];
  }, [scopedProfiles]);

  const familyValues = useMemo(() => {
    const available = new Set(scopedProfiles
      .filter((item) => !selection.vendor || item.vendor === selection.vendor)
      .map((item) => item.platformFamily));
    return [
      ...TEXTFSM_PLATFORM_FAMILIES.map((item) => item.value).filter((item) => available.has(item)),
      ...unique(Array.from(available)).filter((item) => !TEXTFSM_PLATFORM_FAMILIES.some((option) => option.value === item)),
    ];
  }, [scopedProfiles, selection.vendor]);

  const versionValues = useMemo(() => {
    const available = new Set(scopedProfiles
      .filter((item) => (!selection.vendor || item.vendor === selection.vendor)
        && (!selection.platformFamily || item.platformFamily === selection.platformFamily))
      .map((item) => item.version));
    return [
      ...TEXTFSM_VERSION_ORDER.filter((item) => available.has(item)),
      ...unique(Array.from(available)).filter((item) => !TEXTFSM_VERSION_ORDER.includes(item)),
    ];
  }, [scopedProfiles, selection.platformFamily, selection.vendor]);

  const matchingProfile = useMemo(() => scopedProfiles.find((item) => (
    item.vendor === selection.vendor
      && item.platformFamily === selection.platformFamily
      && item.version === selection.version
  ))?.profile || null, [scopedProfiles, selection]);

  const updateSelection = (next: Partial<typeof selection>) => {
    const candidate = { ...selection, ...next };
    setSelection(candidate);
    const profile = scopedProfiles.find((item) => (
      item.vendor === candidate.vendor
        && item.platformFamily === candidate.platformFamily
        && item.version === candidate.version
    ))?.profile || null;
    onChange(profile);
  };

  const selectClass = 'w-full rounded-lg border border-cyan-200 bg-white px-2.5 py-2 text-xs text-slate-700 outline-none transition-colors focus:border-cyan-500 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500';
  const zh = language === 'zh';

  return (
    <div className={className} title={title}>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <select
          aria-label={zh ? '平台厂商' : 'Platform vendor'}
          value={selection.vendor}
           disabled={disabled || Boolean(normalizedAllowedVendor) || requireVendor || scopedProfiles.length === 0}
          onChange={(event) => {
            const vendor = event.target.value;
             const family = scopedProfiles.find((item) => item.vendor === vendor)?.platformFamily || '';
             const version = scopedProfiles.find((item) => item.vendor === vendor && item.platformFamily === family)?.version || '';
            updateSelection({ vendor, platformFamily: family, version });
          }}
          className={selectClass}
        >
          <option value="">{zh ? '选择厂商' : 'Select vendor'}</option>
          {vendorValues.map((vendor) => <option key={vendor} value={vendor}>{vendorLabel(vendor, language)}</option>)}
        </select>
        <select
          aria-label={zh ? '平台类型' : 'Platform family'}
          value={selection.platformFamily}
          disabled={disabled || !selection.vendor || familyValues.length === 0}
          onChange={(event) => {
            const platformFamily = event.target.value;
            const version = normalizedProfiles.find((item) => item.vendor === selection.vendor && item.platformFamily === platformFamily)?.version || '';
            updateSelection({ platformFamily, version });
          }}
          className={selectClass}
        >
          <option value="">{zh ? '选择平台' : 'Select platform'}</option>
          {familyValues.map((family) => <option key={family} value={family}>{familyLabel(family, language)}</option>)}
        </select>
        <select
          aria-label={zh ? '平台版本' : 'Platform version'}
          value={selection.version}
          disabled={disabled || !selection.platformFamily || versionValues.length === 0}
          onChange={(event) => updateSelection({ version: event.target.value })}
          className={selectClass}
        >
          <option value="">{zh ? '选择版本' : 'Select version'}</option>
          {versionValues.map((version) => <option key={version} value={version}>{versionLabel(version, language)}</option>)}
        </select>
      </div>
      {requireVendor && !normalizedAllowedVendor ? (
        <p className="mt-1 text-[10px] font-semibold text-amber-700">
          {zh ? '设备厂商未知，无法安全绑定平台。请先补充厂商或完成自动识别。' : 'The device vendor is unknown. Add the vendor or run detection before binding.'}
        </p>
      ) : normalizedAllowedVendor && (
        <p className="mt-1 text-[10px] font-semibold text-slate-600">
          {zh ? `已限制为设备厂商：${platformVendorLabel(normalizedAllowedVendor, language)}` : `Vendor restricted to ${platformVendorLabel(normalizedAllowedVendor, language)}`}
        </p>
      )}
      {matchingProfile ? (
        <p className="mt-1 text-[10px] text-cyan-800/70">
          {zh ? `将绑定：${matchingProfile.name_zh || matchingProfile.platform_code}` : `Will bind: ${matchingProfile.name_en || matchingProfile.platform_code}`}
          <span className="ml-1 font-mono">({matchingProfile.platform_code})</span>
        </p>
      ) : (
        <p className="mt-1 text-[10px] text-amber-700">
          {zh ? '该厂商/平台/版本尚未在平台注册表中发布，暂不能绑定。' : 'This vendor/platform/version is not published in the platform registry yet.'}
        </p>
      )}
    </div>
  );
};

export default PlatformProfileSelector;
