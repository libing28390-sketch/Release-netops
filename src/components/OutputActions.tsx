import React, { useState, useCallback } from 'react';
import { Copy, Check, Download, FileDown } from 'lucide-react';

/**
 * GitHub-style compact toolbar for command-output blocks.
 *
 * Visual reference (from project screenshots):
 *   ┌──────────────────────────┐
 *   │ sJz+-wO3W_4vIvQRmV20  ⧉ │   black/dark-navy pill
 *   └──────────────────────────┘   cyan text + icon, "✓" after copy
 *
 * - Copy:     copies `text` to clipboard, shows ✓ briefly.
 * - Download: saves `text` as a UTF-8 .txt.
 * - CSV:      optional, exports `csvRows` as .csv (Excel-ready with BOM).
 *
 * Theme presets:
 *   - `dark`  : GitHub-style emphasis surface with the semantic accent color (default).
 *   - `light` : the same semantic palette on a light surface.
 */
interface OutputActionsProps {
  text: string;
  filename?: string;
  csvRows?: Array<Record<string, unknown>>;
  theme?: 'dark' | 'light';
  zh?: boolean;
  className?: string;
  iconOnly?: boolean;
}

function escapeCsvCell(value: unknown): string {
  const s = value == null ? '' : String(value);
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function rowsToCsv(rows: Array<Record<string, unknown>>): string {
  if (!rows.length) return '';
  const headerSet = new Set<string>();
  rows.forEach(r => Object.keys(r || {}).forEach(k => headerSet.add(k)));
  const headers = Array.from(headerSet);
  const lines = [headers.map(escapeCsvCell).join(',')];
  rows.forEach(r => lines.push(headers.map(h => escapeCsvCell(r?.[h])).join(',')));
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

  // ── Pill styles ─────────────────────────────────────────────
  // Both presets use the shared Primer-inspired semantic tokens so output
  // actions remain consistent with the rest of the application in light/dark mode.
  const isDark = theme === 'dark';
  const pillBase = isDark
    ? 'bg-[var(--ui-surface-emphasis)] hover:bg-[var(--ui-border)] border border-[var(--ui-border)]'
    : 'bg-[var(--ui-surface-muted)] hover:bg-[var(--ui-surface-emphasis)] border border-[var(--ui-border)]';
  const textDefault = 'text-[var(--ui-accent)]';
  const textSuccess = 'text-[var(--ui-success)]';
  const textDisabled = 'text-[var(--ui-fg-subtle)]';
  const dividerCol = 'bg-[var(--ui-border)]';

  // Segmented pill: [Copy | Download | CSV?]
  return (
    <div
      className={`inline-flex items-stretch rounded-full overflow-hidden ${pillBase} shadow-sm ${className}`}
      role="toolbar"
    >
      {/* Copy segment */}
      <button
        type="button"
        onClick={handleCopy}
        disabled={!text}
        className={`group/copy inline-flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-mono font-semibold transition-colors ${
          !text ? `${textDisabled} cursor-not-allowed` : copied ? textSuccess : `${textDefault} hover:text-[var(--ui-accent-hover)]`
          }`}
        title={label('复制到剪贴板', 'Copy to clipboard')}
        aria-label={label('复制', 'Copy')}
      >
        {copied
          ? <Check size={13} strokeWidth={2.5} />
          : <Copy size={13} strokeWidth={2} />}
        {!iconOnly && <span>{copied ? label('已复制', 'Copied') : label('复制', 'Copy')}</span>}
      </button>

      {/* Divider */}
      <span className={`w-px ${dividerCol} my-1.5`} aria-hidden="true" />

      {/* Download TXT segment */}
      <button
        type="button"
        onClick={handleDownloadText}
        disabled={!text}
        className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-mono font-semibold transition-colors ${
          !text ? `${textDisabled} cursor-not-allowed` : `${textDefault} hover:text-[var(--ui-accent-hover)]`
          }`}
        title={label('下载 TXT', 'Download TXT')}
        aria-label={label('下载', 'Download')}
      >
        <Download size={13} strokeWidth={2} />
        {!iconOnly && <span>{label('下载', 'Download')}</span>}
      </button>

      {/* Optional CSV segment */}
      {csvRows && csvRows.length > 0 && (
        <>
          <span className={`w-px ${dividerCol} my-1.5`} aria-hidden="true" />
          <button
            type="button"
            onClick={handleDownloadCsv}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-mono font-semibold transition-colors ${textDefault} hover:text-[var(--ui-accent-hover)]`}
            title={label('导出 CSV (Excel 可直接打开)', 'Export CSV (opens in Excel)')}
            aria-label={label('导出 CSV', 'Export CSV')}
          >
            <FileDown size={13} strokeWidth={2} />
            {!iconOnly && <span>CSV</span>}
          </button>
        </>
      )}
    </div>
  );
};

export default OutputActions;
