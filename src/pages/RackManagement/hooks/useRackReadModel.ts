import { useCallback, useEffect, useRef, useState } from 'react';
import { API } from '../constants';
import { authHeaders, formatErrorDetail } from '../helpers';
import { RackLayout, RackSummary, RackSummaryPage } from '../types';

interface RackSummaryFilters {
  page: number;
  pageSize: number;
  keyword?: string;
  siteId?: string;
  floor?: string;
  room?: string;
  row?: string;
  status?: string;
  health?: string;
}

interface CachedLayout {
  data: RackLayout;
  expiresAt: number;
}

const LAYOUT_CACHE_TTL_MS = 5 * 60 * 1000;
const LAYOUT_CACHE_MAX_ENTRIES = 12;

async function parseApiResponse<T>(response: Response): Promise<T> {
  const payload = await response.json();
  if (!response.ok || !payload?.success) {
    throw new Error(formatErrorDetail(payload?.detail || payload?.message || `HTTP ${response.status}`));
  }
  return payload.data as T;
}

export function useRackReadModel(filters: RackSummaryFilters) {
  const [racks, setRacks] = useState<RackSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [summaryError, setSummaryError] = useState('');
  const [summaryReloadKey, setSummaryReloadKey] = useState(0);

  const [layout, setLayout] = useState<RackLayout | null>(null);
  const [layoutRackId, setLayoutRackId] = useState('');
  const [layoutLoading, setLayoutLoading] = useState(false);
  const [layoutError, setLayoutError] = useState('');

  const summaryAbortRef = useRef<AbortController | null>(null);
  const layoutAbortRef = useRef<AbortController | null>(null);
  const layoutRequestSeqRef = useRef(0);
  const layoutCacheRef = useRef<Map<string, CachedLayout>>(new Map());

  useEffect(() => {
    const controller = new AbortController();
    summaryAbortRef.current?.abort();
    summaryAbortRef.current = controller;
    setSummaryLoading(true);
    setSummaryError('');

    const params = new URLSearchParams({
      page: String(filters.page),
      page_size: String(filters.pageSize),
    });
    if (filters.keyword?.trim()) params.set('keyword', filters.keyword.trim());
    if (filters.siteId) params.set('site_id', filters.siteId);
    if (filters.floor) params.set('floor', filters.floor);
    if (filters.room) params.set('room', filters.room);
    if (filters.row) params.set('row', filters.row);
    if (filters.status) params.set('status', filters.status);
    if (filters.health) params.set('health', filters.health);

    fetch(`${API}/racks/summary?${params.toString()}`, {
      headers: authHeaders(),
      signal: controller.signal,
    })
      .then(response => parseApiResponse<RackSummaryPage>(response))
      .then(result => {
        if (controller.signal.aborted) return;
        setRacks(result.items);
        setTotal(result.total);
      })
      .catch(error => {
        if (controller.signal.aborted || error?.name === 'AbortError') return;
        setRacks([]);
        setTotal(0);
        setSummaryError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setSummaryLoading(false);
      });

    return () => controller.abort();
  }, [
    filters.floor,
    filters.health,
    filters.keyword,
    filters.page,
    filters.pageSize,
    filters.room,
    filters.row,
    filters.siteId,
    filters.status,
    summaryReloadKey,
  ]);

  const reloadSummaries = useCallback(() => {
    setSummaryReloadKey(value => value + 1);
  }, []);

  const invalidateLayout = useCallback((rackId?: string) => {
    if (rackId) layoutCacheRef.current.delete(rackId);
    else layoutCacheRef.current.clear();
  }, []);

  const loadLayout = useCallback(async (rackId: string, force = false) => {
    const requestSeq = ++layoutRequestSeqRef.current;
    layoutAbortRef.current?.abort();

    if (!rackId) {
      setLayout(null);
      setLayoutRackId('');
      setLayoutLoading(false);
      setLayoutError('');
      return null;
    }

    const cached = layoutCacheRef.current.get(rackId);
    if (!force && cached && cached.expiresAt > Date.now()) {
      layoutCacheRef.current.delete(rackId);
      layoutCacheRef.current.set(rackId, cached);
      setLayout(cached.data);
      setLayoutRackId(rackId);
      setLayoutLoading(false);
      setLayoutError('');
      return cached.data;
    }

    const controller = new AbortController();
    layoutAbortRef.current = controller;
    setLayoutLoading(true);
    setLayoutError('');
    if (layoutRackId !== rackId) setLayout(null);

    try {
      const response = await fetch(`${API}/racks/${encodeURIComponent(rackId)}/layout`, {
        headers: authHeaders(),
        signal: controller.signal,
      });
      const nextLayout = await parseApiResponse<RackLayout>(response);
      if (controller.signal.aborted || requestSeq !== layoutRequestSeqRef.current) return null;

      layoutCacheRef.current.delete(rackId);
      layoutCacheRef.current.set(rackId, {
        data: nextLayout,
        expiresAt: Date.now() + LAYOUT_CACHE_TTL_MS,
      });
      while (layoutCacheRef.current.size > LAYOUT_CACHE_MAX_ENTRIES) {
        const oldestKey = layoutCacheRef.current.keys().next().value;
        if (!oldestKey) break;
        layoutCacheRef.current.delete(oldestKey);
      }
      setLayout(nextLayout);
      setLayoutRackId(rackId);
      return nextLayout;
    } catch (error: any) {
      if (controller.signal.aborted || requestSeq !== layoutRequestSeqRef.current || error?.name === 'AbortError') return null;
      setLayout(null);
      setLayoutRackId(rackId);
      setLayoutError(error instanceof Error ? error.message : String(error));
      return null;
    } finally {
      if (!controller.signal.aborted && requestSeq === layoutRequestSeqRef.current) setLayoutLoading(false);
    }
  }, [layoutRackId]);

  useEffect(() => () => {
    summaryAbortRef.current?.abort();
    layoutAbortRef.current?.abort();
  }, []);

  return {
    racks,
    total,
    summaryLoading,
    summaryError,
    reloadSummaries,
    layout,
    layoutRackId,
    layoutLoading,
    layoutError,
    loadLayout,
    invalidateLayout,
  };
}
