import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import PlatformProfileSelector from './PlatformProfileSelector';

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
});
