import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Copy, Check, Terminal } from 'lucide-react';
import { copyTextWithFallback } from '../utils/clipboard';

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

const VENDOR_BADGES: Record<string, { label: string; color: string; bg: string }> = {
  huawei: { label: 'Huawei CLI', color: '#10b981', bg: 'rgba(16, 185, 129, 0.12)' },
  vrp: { label: 'Huawei VRP', color: '#10b981', bg: 'rgba(16, 185, 129, 0.12)' },
  h3c: { label: 'H3C Comware', color: '#8b5cf6', bg: 'rgba(139, 92, 246, 0.12)' },
  comware: { label: 'H3C Comware', color: '#8b5cf6', bg: 'rgba(139, 92, 246, 0.12)' },
  cisco: { label: 'Cisco IOS/NX-OS', color: '#0078d4', bg: 'rgba(0, 120, 212, 0.12)' },
  ios: { label: 'Cisco IOS', color: '#0078d4', bg: 'rgba(0, 120, 212, 0.12)' },
  bash: { label: 'Shell / CLI', color: '#64748b', bg: 'rgba(100, 116, 139, 0.12)' },
  sh: { label: 'Shell', color: '#64748b', bg: 'rgba(100, 116, 139, 0.12)' },
  python: { label: 'Python Script', color: '#3b82f6', bg: 'rgba(59, 130, 246, 0.12)' },
  json: { label: 'JSON Data', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.12)' },
  sql: { label: 'SQL Query', color: '#ec4899', bg: 'rgba(236, 72, 153, 0.12)' },
};

const CodeBlockHeader: React.FC<{ language: string; code: string }> = ({ language, code }) => {
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const langKey = (language || '').toLowerCase();
  const badgeInfo = VENDOR_BADGES[langKey] || {
    label: language ? `${language.toUpperCase()} Code` : 'CLI / Text',
    color: '#6b7280',
    bg: 'rgba(107, 114, 128, 0.12)',
  };

  const handleCopy = async () => {
    const copiedSuccessfully = await copyTextWithFallback(code);
    setCopyFailed(!copiedSuccessfully);
    if (!copiedSuccessfully) return;

    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex items-center justify-between px-3.5 py-1.5 bg-[#18181b] border-b border-gray-800 rounded-t-xl text-xs font-mono select-none">
      <div className="flex items-center gap-2">
        <Terminal className="w-3.5 h-3.5 text-gray-400" />
        <span
          className="px-2 py-0.5 rounded font-semibold text-[11px]"
          style={{ color: badgeInfo.color, backgroundColor: badgeInfo.bg }}
        >
          {badgeInfo.label}
        </span>
      </div>

      <button
        type="button"
        onClick={handleCopy}
        aria-label={copied ? '已复制代码' : '复制代码'}
        title={copyFailed ? '复制失败，请检查浏览器权限' : copied ? '已复制代码' : '复制代码'}
        className={`p-1.5 rounded-md transition ${
          copied
            ? 'text-emerald-400 hover:bg-emerald-400/10'
            : copyFailed
              ? 'text-rose-400 hover:bg-rose-400/10'
              : 'text-gray-400 hover:text-white hover:bg-gray-800'
        }`}
      >
        {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
        <span className="sr-only">{copied ? '已复制代码' : '复制代码'}</span>
      </button>
    </div>
  );
};

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ content, className = '' }) => {
  return (
    <div className={`markdown-body space-y-3 leading-relaxed text-sm ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 className="text-lg font-bold text-gray-900 dark:text-white border-b border-gray-200 dark:border-gray-700 pb-1 mt-4 mb-2">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-base font-bold text-gray-900 dark:text-white border-b border-gray-100 dark:border-gray-700/60 pb-1 mt-3 mb-2">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-sm font-bold text-gray-900 dark:text-white mt-2.5 mb-1.5">
              {children}
            </h3>
          ),
          p: ({ children }) => <p className="mb-2 leading-relaxed">{children}</p>,
          ul: ({ children }) => <ul className="list-disc list-inside space-y-1 my-2 pl-2">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal list-inside space-y-1 my-2 pl-2">{children}</ol>,
          li: ({ children }) => <li className="leading-normal">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-4 border-indigo-500 bg-indigo-50/50 dark:bg-indigo-950/30 px-3.5 py-2 my-2 rounded-r-lg text-gray-700 dark:text-gray-300 italic">
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto my-3 rounded-lg border border-gray-200 dark:border-gray-700">
              <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700 text-xs text-left">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-200 font-semibold">
              {children}
            </thead>
          ),
          tbody: ({ children }) => (
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700 bg-white dark:bg-gray-900/40">
              {children}
            </tbody>
          ),
          tr: ({ children }) => (
            <tr className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
              {children}
            </tr>
          ),
          th: ({ children }) => <th className="px-3.5 py-2 font-medium">{children}</th>,
          td: ({ children }) => <td className="px-3.5 py-2">{children}</td>,
          hr: () => <hr className="my-4 border-gray-200 dark:border-gray-700" />,
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-indigo-600 dark:text-indigo-400 hover:underline font-medium"
            >
              {children}
            </a>
          ),
          code({ inline, className: codeClassName, children, ...props }: any) {
            const match = /language-(\w+)/.exec(codeClassName || '');
            const language = match ? match[1] : '';
            const codeString = String(children).replace(/\n$/, '');

            if (inline || !codeClassName) {
              return (
                <code
                  className="bg-gray-200/70 dark:bg-gray-800 text-indigo-600 dark:text-indigo-300 font-mono text-[12px] px-1.5 py-0.5 rounded border border-gray-300/40 dark:border-gray-700/40"
                  {...props}
                >
                  {children}
                </code>
              );
            }

            return (
              <div className="my-3 rounded-xl overflow-hidden shadow-md border border-gray-800 bg-[#0d1117]">
                <CodeBlockHeader language={language} code={codeString} />
                <div className="p-3.5 overflow-x-auto text-[#e6edf3] font-mono text-xs leading-relaxed select-text">
                  <pre>
                    <code>{codeString}</code>
                  </pre>
                </div>
              </div>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};

export default MarkdownRenderer;
