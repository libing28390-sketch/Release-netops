import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import { useAppSharedDataRefreshLifecycle, useAppSharedLookups } from './App';

const response = (payload: unknown) => ({
  ok: true,
  status: 200,
  headers: new Headers(),
  json: vi.fn().mockResolvedValue(payload),
}) as unknown as Response;

const lookupPayloadFor = (input: RequestInfo | URL, session = 'user-a') => {
  const url = String(input);
  if (url === '/api/scripts' || url === '/api/vars') return [session];
  if (url.startsWith('/api/config-templates')) return { items: [{ id: `${session}-template`, name: 'Template' }] };
  return [];
};

const lookupSetters = (sessionIdentity = 'user-a:session-a') => ({
  sessionIdentity,
  setScripts: vi.fn(),
  setConfigTemplates: vi.fn(),
  setSelectedTemplateId: vi.fn(),
  setGlobalVars: vi.fn(),
});

describe('App shared lookup refresh', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => response(lookupPayloadFor(input))));
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('keeps the lookup callback stable when template selection changes', () => {
    const setters = lookupSetters();
    const { result } = renderHook(() => {
      const [selectedTemplateId, setSelectedTemplateId] = useState('');
      const fetchSharedLookups = useAppSharedLookups({ ...setters, setSelectedTemplateId });
      return { selectedTemplateId, setSelectedTemplateId, fetchSharedLookups };
    });
    const originalCallback = result.current.fetchSharedLookups;

    act(() => result.current.setSelectedTemplateId('manually-selected'));

    expect(result.current.selectedTemplateId).toBe('manually-selected');
    expect(result.current.fetchSharedLookups).toBe(originalCallback);
  });

  it('loads only the requested resources and reuses successful results for two minutes', async () => {
    vi.useFakeTimers();
    const setters = lookupSetters();
    const { result } = renderHook(() => useAppSharedLookups(setters));

    await act(async () => { await result.current('automation'); });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith('/api/scripts', expect.anything());
    expect(fetch).not.toHaveBeenCalledWith('/api/users', expect.anything());

    await act(async () => { await result.current('automation'); });
    expect(fetch).toHaveBeenCalledTimes(1);

    await act(async () => { await result.current('configuration'); });
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(fetch).toHaveBeenCalledWith('/api/config-templates?page=1&page_size=200&sort=updated', expect.anything());
    expect(fetch).toHaveBeenCalledWith('/api/vars', expect.anything());

    await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
    await act(async () => { await result.current('automation'); });
    expect(fetch).toHaveBeenCalledTimes(4);

    await act(async () => { await result.current('automation', { force: true }); });
    expect(fetch).toHaveBeenCalledTimes(5);
  });

  it('deduplicates overlapping lookups and selects the first template without replacing a manual choice', async () => {
    const setters = lookupSetters();
    const { result } = renderHook(() => useAppSharedLookups(setters));

    let first!: Promise<void>;
    let overlapping!: Promise<void>;
    act(() => {
      first = result.current();
      overlapping = result.current();
    });
    expect(overlapping).toBe(first);
    expect(fetch).toHaveBeenCalledTimes(3);

    await act(async () => { await Promise.all([first, overlapping]); });
    expect(setters.setSelectedTemplateId).toHaveBeenCalledWith(expect.any(Function));

    await act(async () => { await result.current(undefined, { force: true }); });
    expect(fetch).toHaveBeenCalledTimes(6);
  });

  it('aborts an old session on logout and ignores late responses after the next session starts', async () => {
    const delayedOldResponses: Array<(value: Response) => void> = [];
    const signals: AbortSignal[] = [];
    let requestCount = 0;
    vi.mocked(fetch).mockImplementation((input, init) => {
      const signal = init?.signal as AbortSignal;
      signals.push(signal);
      requestCount += 1;
      if (requestCount <= 3) return new Promise<Response>(resolve => delayedOldResponses.push(resolve));
      return Promise.resolve(response(lookupPayloadFor(input, 'session-b')));
    });

    const setters = lookupSetters();
    const { result, rerender } = renderHook(
      ({ sessionIdentity }) => useAppSharedLookups({ ...setters, sessionIdentity }),
      { initialProps: { sessionIdentity: 'user-a:session-a' } },
    );

    let oldSessionRequest!: Promise<void>;
    act(() => { oldSessionRequest = result.current(); });
    expect(fetch).toHaveBeenCalledTimes(3);

    rerender({ sessionIdentity: '' });
    expect(signals.every(signal => signal.aborted)).toBe(true);
    await act(async () => { await result.current(); });
    expect(fetch).toHaveBeenCalledTimes(3);

    rerender({ sessionIdentity: 'user-b:session-b' });
    let newSessionRequest!: Promise<void>;
    act(() => { newSessionRequest = result.current(); });
    expect(fetch).toHaveBeenCalledTimes(6);
    await act(async () => { await newSessionRequest; });
    expect(setters.setScripts).toHaveBeenCalledWith(['session-b']);
    expect(setters.setGlobalVars).toHaveBeenCalledWith(['session-b']);
    expect(setters.setConfigTemplates).toHaveBeenCalledWith([{ id: 'session-b-template', name: 'Template' }]);

    const captureWrites = () => [
      setters.setScripts.mock.calls.length,
      setters.setConfigTemplates.mock.calls.length,
      setters.setSelectedTemplateId.mock.calls.length,
      setters.setGlobalVars.mock.calls.length,
    ];
    const writesAfterNewSession = captureWrites();
    await act(async () => {
      delayedOldResponses.forEach(resolve => resolve(response(lookupPayloadFor('/api/scripts', 'session-a'))));
      await oldSessionRequest;
    });
    expect(captureWrites()).toEqual(writesAfterNewSession);
  });

  it('loads Dashboard hot data only there and refreshes route-specific lookup scopes', async () => {
    vi.useFakeTimers();
    const fetchSharedLookups = vi.fn().mockResolvedValue(undefined);
    const fetchHotData = vi.fn().mockResolvedValue(undefined);
    const fetchDevicesData = vi.fn().mockResolvedValue(undefined);
    const setIsLoading = vi.fn();
    const initialProps = {
      isAuthenticated: true,
      pathname: '/monitor/overview',
      activeTab: 'dashboard',
      automationPage: '',
      configPage: '',
      changeOrderPage: '',
      inventorySubPage: '',
      autoRefreshEnabled: true,
      fetchSharedLookups,
      fetchHotData,
      fetchDevicesData,
      setIsLoading,
    };

    const { rerender, unmount } = renderHook(
      (props: typeof initialProps) => useAppSharedDataRefreshLifecycle(props),
      { initialProps },
    );
    await act(async () => { await Promise.resolve(); });
    expect(fetchSharedLookups).toHaveBeenCalledTimes(1);
    expect(fetchSharedLookups).toHaveBeenNthCalledWith(1, 'none');
    expect(fetchHotData).toHaveBeenCalledTimes(1);
    expect(fetchDevicesData).toHaveBeenCalledTimes(0);

    await act(async () => { await Promise.resolve(); });
    rerender({ ...initialProps, pathname: '/config/templates', activeTab: 'config', configPage: 'templates' });
    expect(fetchSharedLookups).toHaveBeenCalledTimes(2);
    expect(fetchSharedLookups).toHaveBeenNthCalledWith(2, 'configuration');
    expect(fetchHotData).toHaveBeenCalledTimes(1);
    expect(fetchDevicesData).toHaveBeenCalledTimes(1);

    await act(async () => { await vi.advanceTimersByTimeAsync(119_999); });
    expect(fetchSharedLookups).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(fetchSharedLookups).toHaveBeenCalledTimes(3);
    expect(fetchSharedLookups).toHaveBeenNthCalledWith(3, 'configuration');

    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(240_000); });
    expect(fetchSharedLookups).toHaveBeenCalledTimes(3);
  });
});
