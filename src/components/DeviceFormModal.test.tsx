import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DeviceFormModal from './DeviceFormModal';
import type { Device } from '../types';

const profiles = [
  { id: 'profile-zte-5900', platform_code: 'zte_5900_v6', name_zh: '中兴 5900 V6', name_en: 'ZTE 5900 V6', vendor: 'ZTE', status: 'ACTIVE' },
  { id: 'profile-zte-zsrv2', platform_code: 'zte_zsrv2_v3', name_zh: '中兴 ZSRV2 V3', name_en: 'ZTE ZSRV2 V3', vendor: 'ZTE', status: 'ACTIVE' },
];

describe('DeviceFormModal platform registry selector', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes('/api/tags/definitions')) {
        return { ok: true, json: async () => ({ success: true, data: [] }) };
      }
      if (String(input).includes('/api/platform-registry/profiles')) {
        return { ok: true, headers: { get: () => null }, json: async () => ({ success: true, data: profiles }) };
      }
      return { ok: true, json: async () => ({}) };
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('offers concrete registry profiles and writes the selected profile id', async () => {
    const user = userEvent.setup();
    const onFormChange = vi.fn();
    render(
      <DeviceFormModal
        mode="add"
        language="en"
        form={{ platform: 'zte_zxros', vendor: 'ZTE' }}
        passwordVisible={false}
        onFormChange={onFormChange}
        onTogglePasswordVisibility={vi.fn()}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    const platformSelect = screen.getByTitle('Select device platform');
    await waitFor(() => expect(screen.getByRole('option', { name: 'ZTE 5900 V6 · ZTE' })).toBeTruthy());
    await user.selectOptions(platformSelect, 'profile-zte-zsrv2');

    expect(onFormChange).toHaveBeenLastCalledWith(expect.objectContaining({
      platform: 'zte_zsrv2_v3',
      platform_profile_id: 'profile-zte-zsrv2',
      platform_source: 'MANUAL',
    }));
    expect(screen.getByRole('link', { name: 'Manage platforms' }).getAttribute('href')).toBe('/automation/platforms');
  });

  it('defaults SSH algorithm policy to auto and gates break-glass submission behind acknowledgement', async () => {
    const user = userEvent.setup();
    const onFormChange = vi.fn();
    const onSubmit = vi.fn();
    const Harness = () => {
      const [form, setForm] = React.useState<Partial<Device>>({ platform: 'cisco_ios', connection_method: 'ssh' });
      return (
        <DeviceFormModal
          mode="add"
          language="en"
          form={form}
          passwordVisible={false}
          onFormChange={(nextForm) => { onFormChange(nextForm); setForm(nextForm); }}
          onTogglePasswordVisibility={vi.fn()}
          onClose={vi.fn()}
          onSubmit={onSubmit}
        />
      );
    };
    render(
      <Harness />,
    );

    const algorithmSelect = screen.getByTitle('SSH algorithm profile');
    expect((algorithmSelect as HTMLSelectElement).value).toBe('auto');
    await user.selectOptions(algorithmSelect, 'legacy_break_glass');

    const submitButton = screen.getByRole('button', { name: 'Create Device' });
    expect((submitButton as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('Acknowledge high-risk compatibility')).toBeTruthy();

    await user.click(screen.getByRole('checkbox'));
    expect((submitButton as HTMLButtonElement).disabled).toBe(false);
    await user.click(submitButton);
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onFormChange).toHaveBeenLastCalledWith(expect.objectContaining({ ssh_algorithm_profile: 'legacy_break_glass' }));
  });

  it('keeps an existing binding read-only in ordinary editing while allowing other fields', async () => {
    const user = userEvent.setup();
    const onFormChange = vi.fn();
    render(<DeviceFormModal
      mode="edit" language="en"
      form={{ platform: 'zte_zsrv2_v3', platform_profile_id: 'profile-zte-zsrv2', vendor: 'ZTE' }}
      platformBindingReadOnly passwordVisible={false}
      onFormChange={onFormChange} onTogglePasswordVisibility={vi.fn()}
      onClose={vi.fn()} onSubmit={vi.fn()}
    />);
    await screen.findByRole('option', { name: 'ZTE 5900 V6 · ZTE' });
    const selector = screen.getByTitle('Select device platform') as HTMLSelectElement;
    expect(selector.disabled).toBe(true);
    expect(screen.getByText(/An existing platform binding can only be changed/)).toBeTruthy();
    await user.selectOptions(selector, 'profile-zte-5900');
    expect(onFormChange).not.toHaveBeenCalled();
    await user.type(screen.getByTitle('Device IP address'), '192.0.2.5');
    expect(onFormChange).toHaveBeenCalled();
  });

  it('keeps the hostname read-only when the device is linked to a CMDB asset', () => {
    const onFormChange = vi.fn();
    render(<DeviceFormModal
      mode="edit" language="en"
      form={{ hostname: 'cmdb-core-01', asset_id: 'asset-1' } as Partial<Device>}
      passwordVisible={false}
      onFormChange={onFormChange} onTogglePasswordVisibility={vi.fn()}
      onClose={vi.fn()} onSubmit={vi.fn()}
    />);

    const hostnameInput = screen.getByTitle('Device hostname') as HTMLInputElement;
    expect(hostnameInput.value).toBe('cmdb-core-01');
    expect(hostnameInput.readOnly).toBe(true);
    expect(screen.getByText('Hostname is maintained by CMDB; edit it in Asset Management.')).toBeTruthy();
  });

  it('keeps the hostname editable when the device has no CMDB asset', async () => {
    const user = userEvent.setup();
    const onFormChange = vi.fn();
    render(<DeviceFormModal
      mode="edit" language="en"
      form={{ hostname: 'legacy-core-01' }}
      passwordVisible={false}
      onFormChange={onFormChange} onTogglePasswordVisibility={vi.fn()}
      onClose={vi.fn()} onSubmit={vi.fn()}
    />);

    const hostnameInput = screen.getByTitle('Device hostname') as HTMLInputElement;
    expect(hostnameInput.readOnly).toBe(false);
    await user.type(hostnameInput, '-updated');
    expect(onFormChange).toHaveBeenCalled();
    expect(screen.queryByText('Hostname is maintained by CMDB; edit it in Asset Management.')).toBeNull();
  });
});
