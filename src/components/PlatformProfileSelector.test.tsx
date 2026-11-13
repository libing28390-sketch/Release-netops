import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import PlatformProfileSelector from './PlatformProfileSelector';

afterEach(() => cleanup());

describe('PlatformProfileSelector', () => {
  it('only exposes profiles from the device vendor when vendor locking is enabled', () => {
    render(
      <PlatformProfileSelector
        profiles={[
          {
            id: 'huawei-v8',
            platform_code: 'huawei_vrp8',
            vendor: 'Huawei',
            catalog_vendor: 'huawei',
            platform_family: 'huawei_vrp',
            version: 'v8',
          },
          {
            id: 'h3c-v7',
            platform_code: 'h3c_comware_v7',
            vendor: 'H3C',
            catalog_vendor: 'h3c',
            platform_family: 'h3c_comware',
            version: 'v7',
          },
        ]}
        value=""
        language="zh"
        allowedVendor="Huawei"
        requireVendor
        onChange={vi.fn()}
      />,
    );

    const vendor = screen.getByLabelText('平台厂商') as HTMLSelectElement;
    expect(vendor.disabled).toBe(true);
    expect(Array.from(vendor.options).map((option) => option.value)).toEqual(['', 'huawei']);
    expect(screen.getByText(/已限制为设备厂商：华为/)).toBeTruthy();
  });

  it('shows Huawei YunShan OS as one common-version family', () => {
    render(
      <PlatformProfileSelector
        profiles={[
          {
            id: 'profile-huawei-yunshan',
            platform_code: 'huawei_yunshan',
            vendor: 'Huawei',
            catalog_vendor: 'huawei',
            platform_family: 'huawei_yunshan',
            version: 'common',
          },
        ]}
        value="profile-huawei-yunshan"
        language="zh"
        allowedVendor="Huawei"
        requireVendor
        onChange={vi.fn()}
      />,
    );

    expect((screen.getByLabelText('平台类型') as HTMLSelectElement).value).toBe('huawei_yunshan');
    expect(screen.getByRole('option', { name: '华为 YunShan OS（云杉）' })).toBeTruthy();
    const version = screen.getByLabelText('平台版本') as HTMLSelectElement;
    expect(version.value).toBe('common');
    expect(Array.from(version.options).map((option) => option.value)).toEqual(['', 'common']);
  });
});
