import React, { useState, useCallback } from 'react';
import { Copy, Check, Download, FileDown } from 'lucide-react';

/**
 * GitHub-style copy + download toolbar for command-output blocks.
 *
 * - Copy button: copies `text` to clipboard; shows a short "Copied!" confirmation.
 * - Download button: downloads `text` as a plaintext .txt file (UTF-8).
 * - Export CSV button (optional): when `csvRows` is provided, exports rows as a .csv
 *   file. Used by the quick-query parsed-table view.
 *
 * The toolbar is styled so it can sit on both dark (terminal) and light backgrounds.
 */
interface OutputActionsProps {
  /** Full text to be copied / saved. */
  text: string;
  /** Base filename (without extension). Defaults to "output". */
  filename?: string;
  /** Optional rows for CSV export. Headers derived from first row. */
  csvRows?: Array<Record<string, unknown>>;
  /** Visual theme. "dark" for black-terminal panels, "light" otherwise. */
  theme?: 'dark' | 'light';
  /** Labels in zh/en. */
  zh?: boolean;
  /** Extra Tailwind classes for the outer container. */
  className?: string;
  /** Hide the text label next to each button (icon-only). */
  iconOnly?: boolean;
}

function escapeCsvCell(value: unknown): string {
  const s = value == null ? '' : String(value);
  if (/[",\n\r]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

function rowsToCsv(rows: Array<Record<string, unknown>>): string {
  if (!rows.length) return '';
  // Preserve insertion order across all rows
  const headerSet = new Set<string>();
  rows.forEach(r => Object.keys(r || {}).forEach(k => headerSet.add(k)));
  const headers = Array.from(headerSet);
  const lines = [headers.map(escapeCsvCell).join(',')];
  rows.forEach(r => {
    lines.push(headers.map(h => escapeCsvCell(r?.[h])).join(','));
  });
  // Prepend UTF-8 BOM so Excel detects encoding correctly when opening.
  return '\uFEFF' + lines.join('\r\n');
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Give the browser a moment before revoking so the download settles.
  setTimeout(() => URL.revokeObjectURL(url), 200);
}

const OutputActions: React.FC<OutputActionsProps> = ({
  text,
  filename = 'output',
  csvRows,
  theme = 'dark',
  zh = true,
  className = '',
  iconOnly = false,
}) => {
  const [copied, setCopied] = useState(false);
  const label = (cn: string, en: string) => (zh ? cn : en);

  const handleCopy = useCallback(async () => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Fallback for insecure contexts
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* ignore */ }
      document.body.removeChild(ta);
    }
  }, [text]);

  const handleDownloadText = useCallback(() => {
    if (!text) return;
    const stamp = new Date().toISOString().replace(/[:]/g, '-').slice(0, 19);
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    triggerDownload(blob, `${filename}_${stamp}.txt`);
  }, [text, filename]);

  const handleDownloadCsv = useCallback(() => {
    if (!csvRows || !csvRows.length) return;
    const stamp = new Date().toISOString().replace(/[:]/g, '-').slice(0, 19);
    const blob = new Blob([rowsToCsv(csvRows)], { type: 'text/csv;charset=utf-8' });
    triggerDownload(blob, `${filename}_${stamp}.csv`);
  }, [csvRows, filename]);

  const baseBtn =
    theme === 'dark'
      ? 'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-semibold bg-white/5 hover:bg-white/10 text-white/70 hover:text-white border border-white/10 hover:border-white/20 transition-all'
      : 'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-semibold bg-slate-100 hover:bg-slate-200 text-slate-600 hover:text-slate-900 border border-slate-200 transition-all';

  const successBtn =
    theme === 'dark'
      ? 'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-semibold bg-emerald-500/15 text-emerald-300 border border-emerald-400/30 transition-all'
      : 'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-semibold bg-emerald-50 text-emerald-600 border border-emerald-200 transition-all';

  return (
    <div className={`flex items-center gap-1.5 ${className}`}>
      <button type="button" onClick={handleCopy} className={copied ? successBtn : baseBtn} title={label('复制到剪贴板', 'Copy to clipboard')}>
        {copied ? <Check size={12} /> : <Copy size={12} />}
        {!iconOnly && <span>{copied ? label('已复制', 'Copied') : label('复制', 'Copy')}</span>}
      </button>
      <button type="button" onClick={handleDownloadText} className={baseBtn} title={label('下载 TXT', 'Download TXT')} disabled={!text}>
        <Download size={12} />
        {!iconOnly && <span>{label('下载', 'Download')}</span>}
      </button>
      {csvRows && csvRows.length > 0 && (
        <button type="button" onClick={handleDownloadCsv} className={baseBtn} title={label('导出 CSV (Excel 可直接打开)', 'Export CSV (opens in Excel)')}>
          <FileDown size={12} />
          {!iconOnly && <span>{label('导出 CSV', 'Export CSV')}</span>}
        </button>
      )}
    </div>
  );
};

export default OutputActions;
