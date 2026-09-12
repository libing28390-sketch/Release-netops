import React from 'react';
import { ChevronRight, Star } from 'lucide-react';
import type { NavItem, NavChild } from './types';

/* ─── 单个二级子项 ─── */
export const SubMenuItem: React.FC<{
  item: NavChild;
  isActive: boolean;
  language: string;
  onClick: () => void;
}> = ({ item, isActive, language, onClick }) => (
  <button
    onClick={onClick}
    className={`sidebar-sub-item group/sub w-full flex items-center gap-2 pl-9 pr-3 py-[5px] text-[12.5px] rounded-md transition-colors duration-100 ${
      isActive
        ? 'text-white bg-white/[0.06] sidebar-active-indicator'
        : 'text-[#8b9cb6] hover:text-[#c8d6e5] hover:bg-white/[0.03]'
    }`}
  >
    <item.icon size={14} className={isActive ? 'text-[#58a6ff]' : 'text-[#4a5568] group-hover/sub:text-[#718096]'} />
    <span className="truncate">{language === 'zh' ? item.labelZh : item.labelEn}</span>
  </button>
);

/* ─── 一级菜单项（无子菜单） ─── */
export const NavMenuItem: React.FC<{
  item: NavItem;
  isActive: boolean;
  language: string;
  isMini: boolean;
  onClick: () => void;
}> = ({ item, isActive, language, isMini, onClick }) => (
  <button
    onClick={onClick}
    title={isMini ? (language === 'zh' ? item.labelZh : item.labelEn) : undefined}
    className={`sidebar-nav-item group/nav w-full flex items-center gap-2.5 px-3 py-[7px] rounded-md text-[13px] font-medium transition-colors duration-100 ${
      isActive
        ? 'text-white bg-white/[0.07] sidebar-active-indicator'
        : 'text-[#8b9cb6] hover:text-[#c8d6e5] hover:bg-white/[0.035]'
    }`}
  >
    <item.icon size={17} strokeWidth={1.8} className={`shrink-0 ${isActive ? 'text-[#58a6ff]' : 'text-[#4a5568] group-hover/nav:text-[#718096]'}`} />
    {!isMini && (
      <>
        <span className="sidebar-nav-label flex-1 truncate text-left">{language === 'zh' ? item.labelZh : item.labelEn}</span>
        {item.badge !== undefined && item.badge > 0 && (
          <span className={`sidebar-nav-badge shrink-0 min-w-[18px] h-[18px] flex items-center justify-center rounded-full text-[10px] font-bold leading-none px-1 ${item.badgeTone || 'bg-red-500/90 text-white'}`}>
            {item.badge > 99 ? '99+' : item.badge}
          </span>
        )}
        {item.metricSlot}
      </>
    )}
  </button>
);

/* ─── 一级菜单项（有子菜单，可展开） ─── */
export const NavGroupItem: React.FC<{
  item: NavItem;
  isActive: boolean;
  isOpen: boolean;
  language: string;
  isMini: boolean;
  activeTab: string;
  currentPath: string;
  onClick: () => void;
  onChildClick: (child: NavChild) => void;
  isChildActive: (child: NavChild) => boolean;
}> = ({ item, isActive, isOpen, language, isMini, onClick, onChildClick, isChildActive }) => (
  <div>
    <button
      onClick={onClick}
      title={isMini ? (language === 'zh' ? item.labelZh : item.labelEn) : undefined}
      className={`sidebar-nav-item group/nav w-full flex items-center gap-2.5 px-3 py-[7px] rounded-md text-[13px] font-medium transition-colors duration-100 ${
        isActive
          ? 'text-white bg-white/[0.07] sidebar-active-indicator'
          : 'text-[#8b9cb6] hover:text-[#c8d6e5] hover:bg-white/[0.035]'
      }`}
    >
      <item.icon size={17} strokeWidth={1.8} className={`shrink-0 ${isActive ? 'text-[#58a6ff]' : 'text-[#4a5568] group-hover/nav:text-[#718096]'}`} />
      {!isMini && (
        <>
          <span className="sidebar-nav-label flex-1 truncate text-left">{language === 'zh' ? item.labelZh : item.labelEn}</span>
          {item.badge !== undefined && item.badge > 0 && (
            <span className={`sidebar-nav-badge shrink-0 min-w-[18px] h-[18px] flex items-center justify-center rounded-full text-[10px] font-bold leading-none px-1 ${item.badgeTone || 'bg-red-500/90 text-white'}`}>
              {item.badge > 99 ? '99+' : item.badge}
            </span>
          )}
          {item.metricSlot}
          <ChevronRight
            size={14}
            className={`sidebar-nav-chevron shrink-0 text-[#4a5568] transition-transform duration-150 ${isOpen ? 'rotate-90' : ''}`}
          />
        </>
      )}
    </button>
    {!isMini && item.children && (
      <div className={`sidebar-subitems overflow-hidden transition-all duration-150 ${isOpen ? 'mt-0.5 space-y-px' : 'hidden'}`}>
        {item.children.map((child) => (
          <SubMenuItem
            key={child.id}
            item={child}
            isActive={isChildActive(child)}
            language={language}
            onClick={() => onChildClick(child)}
          />
        ))}
      </div>
    )}
  </div>
);

/* ─── 分组标题 ─── */
export const SectionHeader: React.FC<{
  label: string;
  isMini: boolean;
}> = ({ label, isMini }) => {
  if (isMini) return <div className="sidebar-section-divider mt-3 mb-1 mx-2 h-px bg-white/[0.06]" />;
  return (
    <div className="sidebar-section-toggle mt-5 mb-1 px-3">
      <span className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-[#4a5568]">
        {label}
      </span>
    </div>
  );
};

/* ─── 收藏 / 最近访问标签 ─── */
export const QuickAccessChip: React.FC<{
  label: string;
  isActive: boolean;
  isPinned?: boolean;
  onNavigate: () => void;
  onTogglePin?: () => void;
  language: string;
}> = ({ label, isActive, isPinned, onNavigate, onTogglePin, language }) => (
  <div className="relative group/chip">
    <button
      onClick={onNavigate}
      title={label}
      className={`max-w-full px-2 py-1 rounded text-[11px] truncate transition-colors border ${
        isActive
          ? 'border-[#58a6ff]/30 text-[#58a6ff] bg-[#58a6ff]/[0.08]'
          : 'border-white/[0.06] text-[#6b7c93] bg-white/[0.02] hover:text-[#8b9cb6] hover:bg-white/[0.04]'
      }`}
    >
      {label}
    </button>
    {onTogglePin && (
      <button
        onClick={(e) => { e.stopPropagation(); onTogglePin(); }}
        title={isPinned ? (language === 'zh' ? '取消收藏' : 'Unstar') : (language === 'zh' ? '收藏' : 'Star')}
        className={`absolute -right-1 -top-1 p-0.5 rounded transition-opacity ${
          isPinned
            ? 'opacity-80 text-amber-400'
            : 'opacity-0 group-hover/chip:opacity-100 text-[#4a5568] hover:text-amber-400'
        }`}
      >
        <Star size={10} fill={isPinned ? 'currentColor' : 'none'} />
      </button>
    )}
  </div>
);
