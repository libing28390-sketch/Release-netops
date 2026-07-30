import type { DiffLine } from '../types';

export function normalizeConfigForDiff(content: string): string {
  const volatilePatterns = [
    /^\s*!?\s*(last configuration change|current configuration|time source is)/i,
    /^\s*#\s*(last commit|generated at)/i,
  ];
  const lines = String(content || '')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .split('\n')
    .map((line) => line.replace(/\s+$/, ''))
    .filter((line) => !volatilePatterns.some((pattern) => pattern.test(line)));
  return `${lines.join('\n').trim()}\n`;
}

/**
 * Compute a unified diff between two text contents using LCS dynamic programming.
 * Returns an array of DiffLine objects representing context, add, and remove operations.
 */
export function computeDiff(oldText: string, newText: string): DiffLine[] {
  const oldLines = oldText.replace(/\r\n/g, '\n').split('\n');
  const newLines = newText.replace(/\r\n/g, '\n').split('\n');
  const m = oldLines.length;
  const n = newLines.length;

  // LCS dynamic programming — O(m*n) correctness, handles any offset
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (oldLines[i - 1] === newLines[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }

  // Backtrack through dp table to reconstruct edit operations
  const ops: Array<{ type: 'context' | 'add' | 'remove'; oi?: number; ni?: number }> = [];
  let i = m, j = n;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
      ops.push({ type: 'context', oi: i - 1, ni: j - 1 });
      i--; j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      ops.push({ type: 'add', ni: j - 1 });
      j--;
    } else {
      ops.push({ type: 'remove', oi: i - 1 });
      i--;
    }
  }
  ops.reverse();

  return ops.map(op => {
    if (op.type === 'context') return { type: 'context', lineA: op.oi! + 1, lineB: op.ni! + 1, content: oldLines[op.oi!] };
    if (op.type === 'add')     return { type: 'add',     lineB: op.ni! + 1, content: newLines[op.ni!] };
    return                            { type: 'remove',  lineA: op.oi! + 1, content: oldLines[op.oi!] };
  });
}

export interface SideBySideRow {
  originalIndex: number;
  rowType: 'context' | 'add' | 'remove';
  leftLine: number | null;
  rightLine: number | null;
  leftContent: string;
  rightContent: string;
}

export interface DiffChangeBlock {
  startChangeIdx: number;
  endChangeIdx: number;
  label: string;
  searchText: string;
}

export function buildDiffDerivedData(
  diffLines: DiffLine[],
  onlyChanges: boolean,
  blockQuery: string,
  language: string,
) {
  const activeChangeLineIndexes: number[] = [];
  diffLines.forEach((line, idx) => {
    if (line.type !== 'context') activeChangeLineIndexes.push(idx);
  });

  const renderedDiffLines = diffLines
    .map((line, originalIndex) => ({ line, originalIndex }))
    .filter((entry) => (onlyChanges ? entry.line.type !== 'context' : true));

  const fullSideBySideRows: SideBySideRow[] = diffLines
    .map((line, originalIndex) => {
      if (line.type === 'context') {
        return {
          originalIndex,
          rowType: 'context' as const,
          leftLine: line.lineA || null,
          rightLine: line.lineB || null,
          leftContent: line.content,
          rightContent: line.content,
        };
      }
      if (line.type === 'remove') {
        return {
          originalIndex,
          rowType: 'remove' as const,
          leftLine: line.lineA || null,
          rightLine: null,
          leftContent: line.content,
          rightContent: '',
        };
      }
      return {
        originalIndex,
        rowType: 'add' as const,
        leftLine: null,
        rightLine: line.lineB || null,
        leftContent: '',
        rightContent: line.content,
      };
    })
    .filter((row) => (onlyChanges ? row.rowType !== 'context' : true));

  const diffChangeBlocks: DiffChangeBlock[] = [];
  if (activeChangeLineIndexes.length > 0) {
    let blockStart = 0;
    for (let i = 1; i < activeChangeLineIndexes.length; i++) {
      const prevLineIndex = activeChangeLineIndexes[i - 1];
      const currentLineIndex = activeChangeLineIndexes[i];
      if (currentLineIndex - prevLineIndex > 8) {
        const startLine = diffLines[activeChangeLineIndexes[blockStart]];
        const labelBase = (startLine?.content || '').trim();
        const searchText = activeChangeLineIndexes
          .slice(blockStart, i)
          .map((idx) => diffLines[idx]?.content || '')
          .join(' ')
          .toLowerCase();
        diffChangeBlocks.push({
          startChangeIdx: blockStart,
          endChangeIdx: i - 1,
          label: labelBase.length > 42 ? `${labelBase.slice(0, 42)}...` : (labelBase || (language === 'zh' ? '变更片段' : 'Change block')),
          searchText,
        });
        blockStart = i;
      }
    }

    const lastLine = diffLines[activeChangeLineIndexes[blockStart]];
    const lastLabelBase = (lastLine?.content || '').trim();
    const lastSearchText = activeChangeLineIndexes
      .slice(blockStart)
      .map((idx) => diffLines[idx]?.content || '')
      .join(' ')
      .toLowerCase();
    diffChangeBlocks.push({
      startChangeIdx: blockStart,
      endChangeIdx: activeChangeLineIndexes.length - 1,
      label: lastLabelBase.length > 42 ? `${lastLabelBase.slice(0, 42)}...` : (lastLabelBase || (language === 'zh' ? '变更片段' : 'Change block')),
      searchText: lastSearchText,
    });
  }

  const q = blockQuery.trim().toLowerCase();
  const filteredDiffChangeBlocks = q
    ? diffChangeBlocks.filter((block) => block.label.toLowerCase().includes(q) || block.searchText.includes(q))
    : diffChangeBlocks;

  return {
    activeChangeLineIndexes,
    renderedDiffLines,
    fullSideBySideRows,
    diffChangeBlocks,
    filteredDiffChangeBlocks,
  };
}
