import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { useAccessFavorites } from './useAccessFavorites';

describe('useAccessFavorites', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('persists favorites per authenticated username', () => {
    const alice = renderHook(() => useAccessFavorites('alice'));
    const bob = renderHook(() => useAccessFavorites('bob'));

    act(() => alice.result.current.toggleFavorite('device-1'));

    expect(alice.result.current.favoriteDeviceIds).toEqual(['device-1']);
    expect(bob.result.current.favoriteDeviceIds).toEqual([]);
    expect(localStorage.getItem('nexora_access_favorites:alice')).toBe('["device-1"]');
    expect(localStorage.getItem('nexora_access_favorites:bob')).toBeNull();
  });

  it('toggles an existing favorite off and ignores empty identifiers', () => {
    const { result } = renderHook(() => useAccessFavorites('operator'));

    act(() => result.current.toggleFavorite('device-2'));
    act(() => result.current.toggleFavorite('device-2'));
    act(() => result.current.toggleFavorite(''));

    expect(result.current.favoriteDeviceIds).toEqual([]);
    expect(localStorage.getItem('nexora_access_favorites:operator')).toBe('[]');
  });
});
