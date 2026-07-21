import React from 'react';
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react';
import { motion } from 'motion/react';

function buildPaginationItems(currentPage: number, totalPages: number) {
  if (totalPages <= 7) return Array.from({ length: totalPages }, (_, index) => index + 1);
  const items: Array<number | string> = [1];
  const windowStart = Math.max(2, currentPage - 1);
  const windowEnd = Math.min(totalPages - 1, currentPage + 1);
  if (windowStart > 2) items.push('left-ellipsis');
  for (let page = windowStart; page <= windowEnd; page += 1) items.push(page);
  if (windowEnd < totalPages - 1) items.push('right-ellipsis');
  items.push(totalPages);
  return items;
}

interface PaginationProps {
  currentPage: number;
  totalItems: number;
  onPageChange: (page: number) => void;
  itemsPerPage?: number;
  onItemsPerPageChange?: (size: number) => void;
  language: string;
  alwaysVisible?: boolean;
}

const Pagination: React.FC<PaginationProps> = ({ currentPage, totalItems, onPageChange, itemsPerPage = 10, onItemsPerPageChange, language, alwaysVisible }) => {
  const totalPages = Math.max(1, Math.ceil(totalItems / itemsPerPage));
  if (totalItems === 0 && !alwaysVisible) return null;

  const startItem = totalItems === 0 ? 0 : Math.min((currentPage - 1) * itemsPerPage + 1, totalItems);
  const endItem = Math.min(currentPage * itemsPerPage, totalItems);
  const progressPct = totalItems === 0 ? 0 : Math.max(2, Math.min(100, Math.round((endItem / totalItems) * 100)));
  const pageItems = buildPaginationItems(currentPage, totalPages);
  const zh = language === 'zh';

  return (
    <div className="flex flex-col gap-6 px-8 py-6 bg-slate-50/50 border-t border-black/[0.05] lg:flex-row lg:items-center lg:justify-between">
      {/* Left side: Progress and Summary */}
      <div className="flex items-center gap-6">
        <div className="w-48 h-1.5 bg-black/[0.04] rounded-full overflow-hidden relative">
          <motion.div 
            initial={{ width: 0 }}
            animate={{ width: `${progressPct}%` }}
            className="absolute top-0 left-0 h-full bg-cyan-500 rounded-full shadow-[0_0_8px_rgba(6,182,212,0.5)]"
          />
        </div>
        <div className="space-y-0.5">
          <p className="text-[11px] font-bold text-black/30 uppercase tracking-widest tabular-nums">
            {zh ? `第 ${startItem}-${endItem} 条 / 共 ${totalItems} 条` : `Items ${startItem}-${endItem} of ${totalItems}`}
          </p>
          <p className="text-[11px] font-medium text-black/20 italic">
            {zh ? `第 ${currentPage} 页，共 ${totalPages} 页` : `Page ${currentPage} of ${totalPages}`}
          </p>
        </div>
      </div>

      {/* Right side: Settings and Navigation */}
      <div className="flex flex-col sm:flex-row items-center gap-8">
        {/* Page Size Selector */}
        {onItemsPerPageChange && (
          <div className="flex items-center gap-3">
            <span className="text-[10px] font-black uppercase text-black/25 tracking-widest">{zh ? '每页' : 'Rows'}</span>
            <div className="flex p-0.5 rounded-xl bg-black/[0.03] border border-black/[0.05]">
              {[10, 20, 50, 100].map(size => {
                const isActive = itemsPerPage === size;
                return (
                  <button
                    key={size}
                    onClick={() => onItemsPerPageChange(size)}
                    className={`px-3 py-1 rounded-lg text-[10px] font-black transition-all ${
                      isActive 
                        ? 'bg-[#00172d] text-white shadow-sm' 
                        : 'text-black/40 hover:text-black/70'
                    }`}
                  >
                    {size}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Page Numbers */}
        <div className="flex items-center gap-1 sm:gap-2">
          <button
            disabled={currentPage === 1}
            onClick={() => onPageChange(1)}
            title={zh ? '第一页' : 'First page'}
            className="p-2 rounded-xl border border-black/[0.05] bg-white text-black/40 hover:text-black hover:border-black/10 disabled:opacity-20 transition-all active:scale-90"
          >
            <ChevronsLeft size={16} />
          </button>
          <button
            disabled={currentPage === 1}
            onClick={() => onPageChange(currentPage - 1)}
            title={zh ? '上一页' : 'Previous page'}
            className="p-2 rounded-xl border border-black/[0.05] bg-white text-black/40 hover:text-black hover:border-black/10 disabled:opacity-20 transition-all active:scale-90"
          >
            <ChevronLeft size={16} />
          </button>

          <div className="flex items-center gap-1 sm:gap-1.5">
            {pageItems.map((item, index) => {
              if (typeof item !== 'number') {
                return <span key={index} className="px-1 text-black/20 font-bold">...</span>;
              }
              const isActive = currentPage === item;
              return (
                <button
                  key={item}
                  onClick={() => onPageChange(item)}
                  className={`min-w-[32px] h-8 rounded-xl text-[11px] font-black transition-all ${
                    isActive
                      ? 'bg-[#00172d] text-white shadow-lg shadow-[#00172d]/20 scale-105'
                      : 'hover:bg-black/[0.03] text-black/40 hover:text-black'
                  }`}
                >
                  {item}
                </button>
              );
            })}
          </div>

          <button
            disabled={currentPage === totalPages}
            onClick={() => onPageChange(currentPage + 1)}
            title={zh ? '下一页' : 'Next page'}
            className="p-2 rounded-xl border border-black/[0.05] bg-white text-black/40 hover:text-black hover:border-black/10 disabled:opacity-20 transition-all active:scale-90 group"
          >
            <ChevronRight size={16} className="group-hover:translate-x-0.5 transition-transform" />
          </button>
          <button
            disabled={currentPage === totalPages}
            onClick={() => onPageChange(totalPages)}
            title={zh ? '最后一页' : 'Last page'}
            className="p-2 rounded-xl border border-black/[0.05] bg-white text-black/40 hover:text-black hover:border-black/10 disabled:opacity-20 transition-all active:scale-90"
          >
            <ChevronsRight size={16} />
          </button>
        </div>
      </div>
    </div>
  );
};

export default Pagination;
