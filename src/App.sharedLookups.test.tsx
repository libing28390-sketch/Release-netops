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

const lookupPayloadFor = (input: RequestInfo | URL) => {
  const url = String(input);
  if (url === '/api/scripts') return [];
  if (url === '/api/users') return [];
  if (url.startsWith('/api/config-templates')) return { items: [{ id: 'template-1', name: 'Template 1' }] };
  return [];
};

const lookupPayloadForSession = (input: RequestInfo | URL, session: string) => {
  const url = String(input);
  if (url === '/api/scripts' || url === '/api/users' || url === '/api/vars') return [session];
  if (url.startsWith('/api/config-templates')) return { items: [{ id: `${session}-template`, name: 'Template' }] };
  return [];
};

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
    const setters = {
      sessionIdentity: 'user-a:session-a',
      setScripts: vi.fn(),
      setUsers: vi.fn(),
      setConfigTemplates: vi.fn(),
      setGlobalVars: vi.fn(),
    };
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

  it('deduplicates overlapping lookup calls, selects the first template once, and permits a later refresh', async () => {
    vi.mocked(fetch).mockImplementation(async input => {
      const url = String(input);
      return response(lookupPayloadFor(url));
    });

    const setters = {
      sessionIdentity: 'user-a:session-a',
      setScripts: vi.fn(),
      setUsers: vi.fn(),
      setConfigTemplates: vi.fn(),
      setGlobalVars: vi.fn(),
    };
    const { result } = renderHook(() => {
      const [selectedTemplateId, setSelectedTemplateId] = useState('');
      return {
        selectedTemplateId,
        fetchSharedLookups: useAppSharedLookups({ ...setters, setSelectedTemplateId }),
      };
    });

    let first!: Promise<void>;
    let overlapping!: Promise<void>;
    act(() => {
      first = result.current.fetchSharedLookups();
      overlapping = result.current.fetchSharedLookups();
    });
    expect(overlapping).toBe(first);
    expect(fetch).toHaveBeenCalledTimes(4);

    await act(async () => { await Promise.all([first, overlapping]); });
    expect(result.current.selectedTemplateId).toBe('template-1');

    await act(async () => { await result.current.fetchSharedLookups(); });
    expect(fetch).toHaveBeenCalledTimes(8);
    expect(result.current.selectedTemplateId).toBe('template-1');
  });

  it('aborts an old session on logout, starts a new request for the next session, and ignores late old responses', async () => {
    const delayedOldResponses: Array<{ url: string; resolve: (value: Response) => void }> = [];
    const signals: AbortSignal[] = [];
    let requestCount = 0;
    vi.mocked(fetch).mockImplementation((input, init) => {
      const url = String(input);
      const signal = init?.signal as AbortSignal;
      signals.push(signal);
      requestCount += 1;
      if (requestCount <= 4) {
        return new Promise<Response>(resolve => delayedOldResponses.push({ url, resolve }));
      }
      return Promise.resolve(response(lookupPayloadForSession(url, 'session-b')));
    });

    const setters = {
      setScripts: vi.fn(),
      setUsers: vi.fn(),
      setConfigTemplates: vi.fn(),
      setSelectedTemplateId: vi.fn(),
      setGlobalVars: vi.fn(),
    };
    const { result, rerender } = renderHook(
      ({ sessionIdentity }) => useAppSharedLookups({ ...setters, sessionIdentity }),
      { initialProps: { sessionIdentity: 'user-a:session-a' } },
    );

    let oldSessionRequest!: Promise<void>;
    act(() => { oldSessionRequest = result.current(); });
    expect(fetch).toHaveBeenCalledTimes(4);

    rerender({ sessionIdentity: '' });
    expect(signals.every(signal => signal.aborted)).toBe(true);
    await act(async () => { await result.current(); });
    expect(fetch).toHaveBeenCalledTimes(4);

    rerender({ sessionIdentity: 'user-b:session-b' });
    let newSessionRequest!: Promise<void>;
    act(() => { newSessionRequest = result.current(); });
    expect(fetch).toHaveBeenCalledTimes(8);
    await act(async () => { await newSessionRequest; });
    expect(setters.setScripts).toHaveBeenCalledWith(['session-b']);
    expect(setters.setUsers).toHaveBeenCalledWith(['session-b']);
    expect(setters.setConfigTemplates).toHaveBeenCalledWith([{ id: 'session-b-template', name: 'Template' }]);
    expect(setters.setGlobalVars).toHaveBeenCalledWith(['session-b']);

    const writesAfterNewSession = Object.values(setters).map(setter => setter.mock.calls.length);
    await act(async () => {
      delayedOldResponses.forEach(({ url, resolve }) => resolve(response(lookupPayloadForSession(url, 'session-a'))));
      await oldSessionRequest;
    });
    expect(Object.values(setters).map(setter => setter.mock.calls.length)).toEqual(writesAfterNewSession);
  });

  it('aborts an in-flight request and ignores its response when the hook unmounts', async () => {
    const delayedResponses: Array<{ url: string; resolve: (value: Response) => void }> = [];
    const signals: AbortSignal[] = [];
    vi.mocked(fetch).mockImplementation((input, init) => {
      const signal = init?.signal as AbortSignal;
      signals.push(signal);
      return new Promise<Response>(resolve => delayedResponses.push({ url: String(input), resolve }));
    });
    const setters = {
      sessionIdentity: 'user-a:session-a',
      setScripts: vi.fn(),
      setUsers: vi.fn(),
      setConfigTemplates: vi.fn(),
      setSelectedTemplateId: vi.fn(),
      setGlobalVars: vi.fn(),
    };
    const { result, unmount } = renderHook(() => useAppSharedLookups(setters));

    let request!: Promise<void>;
    act(() => { request = result.current(); });
    unmount();
    expect(signals.every(signal => signal.aborted)).toBe(true);

    await act(async () => {
      delayedResponses.forEach(({ url, resolve }) => resolve(response(lookupPayloadForSession(url, 'session-a'))));
      await request;
    });
    expect(setters.setScripts).not.toHaveBeenCalled();
    expect(setters.setUsers).not.toHaveBeenCalled();
    expect(setters.setConfigTemplates).not.toHaveBeenCalled();
    expect(setters.setGlobalVars).not.toHaveBeenCalled();
  });

  it('runs the production initial and route effects once, keeps the 120-second lookup poll, and cleans timers on unmount', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
    const fetchSharedLookups = vi.fn().mockResolvedValue(undefined);
    const fetchHotData = vi.fn().mockResolvedValue(undefined);
    const fetchDevicesData = vi.fn().mockResolvedValue(undefined);
    const setIsLoading = vi.fn();
    const initialProps = {
      isAuthenticated: true,
      pathname: '/monitor/overview',
      activeTab: 'dashboard',
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
    expect(fetchHotData).toHaveBeenCalledTimes(1);
    expect(fetchDevicesData).toHaveBeenCalledTimes(0);

    await act(async () => { await Promise.resolve(); });
    rerender({ ...initialProps, pathname: '/config/templates' });
    expect(fetchSharedLookups).toHaveBeenCalledTimes(2);
    expect(fetchHotData).toHaveBeenCalledTimes(2);

    await act(async () => { await vi.advanceTimersByTimeAsync(119999); });
    expect(fetchSharedLookups).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(fetchSharedLookups).toHaveBeenCalledTimes(3);

    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(240000); });
    expect(fetchSharedLookups).toHaveBeenCalledTimes(3);
  });
});
