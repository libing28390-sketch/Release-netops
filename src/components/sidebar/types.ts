import type React from 'react';
import type { LucideIcon } from 'lucide-react';

/** 权限标识 — 后端驱动菜单时由接口返回 */
export type Permission = string;

/** 二级菜单项 */
export interface NavChild {
  id: string;
  /** 路由路径，如 "/config/backup"；为 null 表示走 setActiveTab */
  path: string | null;
  icon: LucideIcon;
  labelZh: string;
  labelEn: string;
  /** 需要的权限列表（空 = 公开） */
  permissions?: Permission[];
}

/** 一级菜单项 */
export interface NavItem {
  id: string;
  /** 用于 setActiveTab 的 key */
  tabKey?: string;
  /** 路由路径 */
  path?: string | null;
  icon: LucideIcon;
  labelZh: string;
  labelEn: string;
  /** 二级子项 */
  children?: NavChild[];
  /** badge 数字 */
  badge?: number;
  /** badge 样式 tone class */
  badgeTone?: string;
  /** 额外渲染的右侧信息 */
  metricSlot?: React.ReactNode;
  permissions?: Permission[];
}

/** 导航分组（section） */
export interface NavSection {
  id: string;
  labelZh: string;
  labelEn: string;
  items: NavItem[];
}
