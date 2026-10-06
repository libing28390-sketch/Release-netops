import { describe, expect, it } from 'vitest';
import {
  TEXTFSM_PLATFORM_FAMILIES,
  getConcreteEditorPlatform,
  getEditorSelection,
  getPlatformFamilyOption,
} from './textfsmPlatformCatalog';

describe('TextFSM platform catalog', () => {
  it('covers every planned domestic platform namespace', () => {
    const plannedPlatforms = [
      'huawei_vrp5', 'huawei_vrp8', 'huawei_vrp_unknown',
      'h3c_comware_v3',
      'h3c_comware_v5', 'h3c_comware_v7', 'h3c_comware_v9', 'h3c_comware_unknown',
      'maipu_mypower_v6', 'maipu_mypower_v8', 'maipu_mypower_v9', 'maipu_mypower_unknown',
      'ruijie_rgos_v10', 'ruijie_rgos_v11', 'ruijie_rgos_v12', 'ruijie_rgos_unknown',
      'zte_zxros', 'zte_rosng', 'zte_os_unknown',
      'dptech_conplat', 'dptech_conplat_unknown',
    ];

    const selections = new Set(
      TEXTFSM_PLATFORM_FAMILIES.flatMap((family) => (
        family.versions.map((version) => getConcreteEditorPlatform(family.value, version))
      )),
    );

    expect(plannedPlatforms.every((platform) => selections.has(platform))).toBe(true);
  });

  it('round-trips concrete platform codes back to the three-level editor selection', () => {
    expect(getEditorSelection('huawei_vrp8')).toEqual({
      vendor: 'huawei', platformFamily: 'huawei_vrp', version: 'v8',
    });
    expect(getEditorSelection('h3c_comware_unknown')).toEqual({
      vendor: 'h3c', platformFamily: 'h3c_comware', version: 'unknown',
    });
    expect(getEditorSelection('h3c_comware_v3')).toEqual({
      vendor: 'h3c', platformFamily: 'h3c_comware', version: 'v3',
    });
    expect(getEditorSelection('maipu_mypower_v6')).toEqual({
      vendor: 'maipu', platformFamily: 'maipu_mypower', version: 'v6',
    });
    expect(getEditorSelection('ruijie_rgos_v12')).toEqual({
      vendor: 'ruijie', platformFamily: 'ruijie_rgos', version: 'v12',
    });
    expect(getEditorSelection('zte_os_unknown')).toEqual({
      vendor: 'zte', platformFamily: 'zte_os_unknown', version: 'common',
    });
    expect(getEditorSelection('dptech_conplat_unknown')).toEqual({
      vendor: 'dptech', platformFamily: 'dptech_conplat_unknown', version: 'common',
    });
  });

  it('keeps the legacy Maipu common namespace available', () => {
    expect(getConcreteEditorPlatform('maipu_mypower', 'common')).toBe('maipu');
    expect(getEditorSelection('maipu')).toEqual({
      vendor: 'maipu', platformFamily: 'maipu_mypower', version: 'common',
    });
  });
});

describe('Huawei YunShan TextFSM platform family', () => {
  it('uses a single common version and the independent parser key', () => {
    expect(getPlatformFamilyOption('huawei_yunshan')).toMatchObject({
      vendor: 'huawei',
      label: '华为 YunShan OS（云杉）',
      labelEn: 'Huawei YunShan OS',
      versions: ['common'],
    });
    expect(getEditorSelection('huawei_yunshan')).toEqual({
      vendor: 'huawei',
      platformFamily: 'huawei_yunshan',
      version: 'common',
    });
    expect(getConcreteEditorPlatform('huawei_yunshan', 'common')).toBe('huawei_yunshan');
  });

  it('keeps YunShan aliases out of Huawei VRP version inference', () => {
    for (const alias of [
      'yunshanos',
      'YunShan OS',
      'Huawei YunShan OS',
      '华为 YunShan OS（云杉）',
    ]) {
      expect(getEditorSelection(alias)).toEqual({
        vendor: 'huawei',
        platformFamily: 'huawei_yunshan',
        version: 'common',
      });
    }
  });
});
