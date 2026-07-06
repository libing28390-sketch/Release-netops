import { useState, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import type { ConfigSnapshot, DiffLine } from '../types';
import { computeDiff, buildDiffDerivedData } from '../utils/configDiffEngine';

export interface UseConfigDiffOptions {
  language: string;
  configSnapshots: ConfigSnapshot[];
  loadSnapshotContent: (snap: ConfigSnapshot) => Promise<string>;
  showToast: (msg: string, type?: 'success' | 'error' | 'info') => void;
}

export function useConfigDiff({
  language,
  configSnapshots,
  loadSnapshotContent,
  showToast,
}: UseConfigDiffOptions) {
  const navigate = useNavigate();

  const [configDiffLeft, setConfigDiffLeft] = useState<ConfigSnapshot | null>(null);
  const [configDiffRight, setConfigDiffRight] = useState<ConfigSnapshot | null>(null);
  const [diffPreSelectedDeviceId, setDiffPreSelectedDeviceId] = useState<string | null>(null);
  const [diffOnlyChanges, setDiffOnlyChanges] = useState(false);
  const [diffShowFullBoth, setDiffShowFullBoth] = useState(false);
  const [diffFocusChangeIdx, setDiffFocusChangeIdx] = useState(0);
  const [diffBlockQuery, setDiffBlockQuery] = useState('');
  const diffLineRefs = useRef<Record<number, HTMLDivElement | null>>({});

  // ── Snapshot compare key ──
  const getSnapshotCompareKey = useCallback((snap: ConfigSnapshot | null): string => {
    if (!snap) return '';
    const ip = (snap.ip_address || '').trim();
    if (ip) return `ip:${ip}`;
    return `device:${snap.device_id}`;
  }, []);

  // ── Same-target snapshots for right side picker ──
  const sameTargetSnapshots = (() => {
    const leftKey = getSnapshotCompareKey(configDiffLeft);
    if (!leftKey) return [] as ConfigSnapshot[];
    return configSnapshots.filter((snap) => {
      if (configDiffLeft && snap.id === configDiffLeft.id) return false;
      return getSnapshotCompareKey(snap) === leftKey;
    });
  })();

  // ── Compute diff lines ──
  const activeDiffLines: DiffLine[] = configDiffLeft && configDiffRight
    ? computeDiff(configDiffLeft.content || '', configDiffRight.content || '')
    : [];

  const derived = buildDiffDerivedData(activeDiffLines, diffOnlyChanges, diffBlockQuery, language);

  // ── Navigation helpers ──
  const focusDiffChangeAt = useCallback((changeIdx: number) => {
    if (derived.activeChangeLineIndexes.length === 0) return;
    const safeIdx = Math.max(0, Math.min(changeIdx, derived.activeChangeLineIndexes.length - 1));
    const targetLine = derived.activeChangeLineIndexes[safeIdx];
    setDiffFocusChangeIdx(safeIdx);
    window.requestAnimationFrame(() => {
      diffLineRefs.current[targetLine]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }, [derived.activeChangeLineIndexes]);

  const jumpToDiff = useCallback((direction: 'prev' | 'next') => {
    const total = derived.activeChangeLineIndexes.length;
    if (total === 0) return;
    setDiffFocusChangeIdx((prev) => {
      const next = direction === 'next'
        ? (prev + 1) % total
        : (prev - 1 + total) % total;
      const targetLine = derived.activeChangeLineIndexes[next];
      window.requestAnimationFrame(() => {
        diffLineRefs.current[targetLine]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
      return next;
    });
  }, [derived.activeChangeLineIndexes]);

  // ── Reset ──
  const handleResetDiffView = useCallback(() => {
    setConfigDiffLeft(null);
    setConfigDiffRight(null);
    setDiffFocusChangeIdx(0);
    setDiffBlockQuery('');
    diffLineRefs.current = {};
  }, []);

  // ── Navigate to diff view for a specific device ──
  const handleNavigateToConfigDiff = useCallback((deviceId: string) => {
    setDiffPreSelectedDeviceId(deviceId);
    setConfigDiffLeft(null);
    setConfigDiffRight(null);
    setDiffFocusChangeIdx(0);
    setDiffBlockQuery('');
    diffLineRefs.current = {};
    navigate('/config/diff');
  }, [navigate]);

  // ── Select snapshot pair by ID (used by config backup page) ──
  const handleSelectSnapshotPair = useCallback(async (leftId: string, rightId: string) => {
    try {
      const [leftResp, rightResp] = await Promise.all([
        fetch(`/api/configs/snapshots/${leftId}/content`),
        fetch(`/api/configs/snapshots/${rightId}/content`),
      ]);
      if (!leftResp.ok || !rightResp.ok) {
        showToast(language === 'zh' ? '快照内容加载失败' : 'Failed to load snapshot content', 'error');
        return;
      }
      const leftData = await leftResp.json();
      const rightData = await rightResp.json();
      setConfigDiffLeft({
        id: leftId,
        device_id: leftData.device_id || '',
        hostname: leftData.hostname || '',
        vendor: leftData.vendor || '',
        timestamp: leftData.timestamp || '',
        trigger: leftData.trigger || 'manual',
        content: leftData.content,
        author: leftData.author || '',
        created_at: leftData.created_at || leftData.timestamp || '',
      } as ConfigSnapshot);
      setConfigDiffRight({
        id: rightId,
        device_id: rightData.device_id || '',
        hostname: rightData.hostname || '',
        vendor: rightData.vendor || '',
        timestamp: rightData.timestamp || '',
        trigger: rightData.trigger || 'manual',
        content: rightData.content,
        author: rightData.author || '',
        created_at: rightData.created_at || rightData.timestamp || '',
      } as ConfigSnapshot);
      setDiffFocusChangeIdx(0);
      setDiffBlockQuery('');
      diffLineRefs.current = {};
    } catch {
      showToast(language === 'zh' ? '对比加载失败' : 'Failed to load comparison', 'error');
    }
  }, [language, showToast]);

  // ── Select individual snapshot for left or right side ──
  const handleSelectDiffSnapshot = useCallback(async (side: 'left' | 'right', snapshotId: string) => {
    const snapshotList = side === 'right' && configDiffLeft ? sameTargetSnapshots : configSnapshots;
    const snapshot = snapshotList.find((item) => item.id === snapshotId) || null;

    if (snapshot) {
      const content = await loadSnapshotContent(snapshot);
      const selected = { ...snapshot, content };

      if (side === 'left') {
        setConfigDiffLeft(selected);
        setDiffFocusChangeIdx(0);
        setDiffBlockQuery('');
        diffLineRefs.current = {};
        if (
          configDiffRight &&
          (configDiffRight.id === selected.id || getSnapshotCompareKey(configDiffRight) !== getSnapshotCompareKey(selected))
        ) {
          setConfigDiffRight(null);
        }
      } else {
        if (configDiffLeft && getSnapshotCompareKey(selected) !== getSnapshotCompareKey(configDiffLeft)) {
          setConfigDiffRight(null);
        } else {
          setConfigDiffRight(selected);
        }
        setDiffFocusChangeIdx(0);
        diffLineRefs.current = {};
      }
      return;
    }

    if (side === 'left') {
      setConfigDiffLeft(null);
      setConfigDiffRight(null);
      setDiffFocusChangeIdx(0);
      setDiffBlockQuery('');
      diffLineRefs.current = {};
      return;
    }

    setConfigDiffRight(null);
    setDiffFocusChangeIdx(0);
    diffLineRefs.current = {};
  }, [configDiffLeft, configDiffRight, configSnapshots, sameTargetSnapshots, getSnapshotCompareKey, loadSnapshotContent]);

  // ── Open diff page for a specific snapshot ──
  const handleOpenConfigDiff = useCallback((snapshot: ConfigSnapshot) => {
    setDiffPreSelectedDeviceId(snapshot.device_id || null);
    setConfigDiffLeft(null);
    setConfigDiffRight(null);
    setDiffFocusChangeIdx(0);
    setDiffBlockQuery('');
    diffLineRefs.current = {};
    navigate('/config/diff');
  }, [navigate]);

  return {
    // State
    configDiffLeft,
    configDiffRight,
    diffPreSelectedDeviceId,
    diffOnlyChanges,
    diffShowFullBoth,
    diffFocusChangeIdx,
    diffBlockQuery,
    diffLineRefs,
    // Setters (only expose those used as props)
    setConfigDiffLeft,
    setConfigDiffRight,
    setDiffOnlyChanges,
    setDiffShowFullBoth,
    setDiffFocusChangeIdx,
    setDiffBlockQuery,
    // Derived data
    activeDiffLines,
    activeChangeLineIndexes: derived.activeChangeLineIndexes,
    renderedDiffLines: derived.renderedDiffLines,
    fullSideBySideRows: derived.fullSideBySideRows,
    diffChangeBlocks: derived.diffChangeBlocks,
    filteredDiffChangeBlocks: derived.filteredDiffChangeBlocks,
    sameTargetSnapshots,
    // Actions
    handleResetDiffView,
    handleNavigateToConfigDiff,
    handleSelectSnapshotPair,
    handleSelectDiffSnapshot,
    handleOpenConfigDiff,
    focusDiffChangeAt,
    jumpToDiff,
  };
}
