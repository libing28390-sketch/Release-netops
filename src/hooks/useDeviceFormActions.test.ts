import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Device } from '../types';
import { useDeviceFormActions } from './useDeviceFormActions';

afterEach(() => { vi.unstubAllGlobals(); });

describe('ordinary device editing binding failures', () => {
  it.each(['detail', 'error'])('explains a structured %s and preserves the unsaved form', async (envelope) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      [envelope]: { code: 'PLATFORM_BINDING_LOCKED', message: 'Use the administrator platform binding endpoint.' },
    }), { status: 409, headers: { 'X-Request-ID': 'ordinary-edit-request' } })));
    const showToast = vi.fn();
    const setDevices = vi.fn();
    const { result } = renderHook(() => useDeviceFormActions({ devices: [], setDevices, showToast }));
    act(() => {
      result.current.setEditingDevice({ id: 'device-1', platform_profile_id: 'existing-profile' } as Device);
      result.current.setEditForm({ platform_profile_id: 'other-profile' });
      result.current.setShowEditModal(true);
    });
    await act(async () => { await result.current.handleSaveEdit(); });
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('Administrator account'), 'error');
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('ordinary-edit-request'), 'error');
    expect(setDevices).not.toHaveBeenCalled();
    expect(result.current.showEditModal).toBe(true);
    expect(result.current.editForm.platform_profile_id).toBe('other-profile');
  });
});
