import React from 'react';
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react';

interface PaginationProps {
  currentPage: number;
  totalItems: number;
  onPageChange: (page: number) => void;
  itemsPerPage?: number;
  onItemsPerPageChange?: (size: number) => void;
  language: string;
  alwaysVisible?: boolean;
}

const Pagination: React.FC<PaginationProps> = ({
  currentPage,
  totalItems,
  onPageChange,
  itemsPerPage = 10,
  onItemsPerPageChange,
  language,
  alwaysVisible,
}) => {
  const totalPages = Math.max(1, Math.ceil(totalItems / itemsPerPage));
  if (totalItems === 0 && !alwaysVisible) return null;

  const zh = language === 'zh';
  const moveToPage = (value: number) => {
    onPageChange(Math.max(1, Math.min(totalPages, value)));
  };

  return (
    <div className="nx-table-pagination flex flex-wrap items-center justify-between gap-3 border-t px-3 py-2.5 text-xs">
      <span className="whitespace-nowrap">{zh ? `共 ${totalItems} 条` : `${totalItems} items`}</span>

      <div className="flex items-center gap-2">
        {onItemsPerPageChange && (
          <label className="flex items-center gap-1 whitespace-nowrap">
            <select
              value={itemsPerPage}
              onChange={(event) => onItemsPerPageChange(Number(event.target.value))}
              className="rounded border-0 bg-transparent px-1 py-1 text-xs text-slate-700 outline-none dark:text-slate-200"
              aria-label={zh ? '每页条数' : 'Items per page'}
            >
              {[10, 20, 50, 100].map(size => <option key={size} value={size}>{size}</option>)}
            </select>
            <span>{zh ? '条/页' : 'per page'}</span>
          </label>
        )}

        <div className="flex items-center overflow-hidden rounded border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
          <button type="button" disabled={currentPage <= 1} onClick={() => moveToPage(1)} title={zh ? '第一页' : 'First page'} className="border-r border-slate-200 p-1.5 text-slate-400 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-30 dark:border-slate-700 dark:hover:bg-slate-800"><ChevronsLeft size={14} /></button>
          <button type="button" disabled={currentPage <= 1} onClick={() => moveToPage(currentPage - 1)} title={zh ? '上一页' : 'Previous page'} className="border-r border-slate-200 p-1.5 text-slate-400 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-30 dark:border-slate-700 dark:hover:bg-slate-800"><ChevronLeft size={14} /></button>
          <input
            type="number"
            min={1}
            max={totalPages}
            value={currentPage}
            onChange={(event) => {
              const value = Number(event.target.value);
              if (Number.isFinite(value) && value >= 1) moveToPage(value);
            }}
            className="h-7 w-10 border-0 bg-transparent px-1 text-center text-xs text-slate-700 outline-none dark:text-slate-200"
            aria-label={zh ? '当前页' : 'Current page'}
          />
          <span className="border-l border-slate-200 px-2 text-xs text-slate-400 dark:border-slate-700">/ {totalPages} {zh ? '页' : 'pages'}</span>
          <button type="button" disabled={currentPage >= totalPages} onClick={() => moveToPage(currentPage + 1)} title={zh ? '下一页' : 'Next page'} className="border-l border-slate-200 p-1.5 text-slate-400 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-30 dark:border-slate-700 dark:hover:bg-slate-800"><ChevronRight size={14} /></button>
          <button type="button" disabled={currentPage >= totalPages} onClick={() => moveToPage(totalPages)} title={zh ? '最后一页' : 'Last page'} className="border-l border-slate-200 p-1.5 text-slate-400 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-30 dark:border-slate-700 dark:hover:bg-slate-800"><ChevronsRight size={14} /></button>
        </div>
      </div>
    </div>
  );
};

export default Pagination;
