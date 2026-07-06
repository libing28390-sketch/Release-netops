import { useCallback, useMemo, useState } from 'react';
import type { Language } from '../i18n.tsx';

export interface CommandPaletteItem {
  path: string;
  label: string;
  group: string;
}

interface UseCommandPaletteArgs {
  language: Language;
  t: (key: string) => string;
}

interface UseCommandPaletteResult {
  pinnedPaths: string[];
  togglePin: (path: string) => void;
  cmdPaletteQuery: string;
  setCmdPaletteQuery: (value: string) => void;
  allNavItems: CommandPaletteItem[];
  cmdPaletteFiltered: CommandPaletteItem[];
}

const PINNED_STORAGE_KEY = 'netops_pinned_nav';
const PIN_LIMIT = 6;

export const useCommandPalette = ({ language, t }: UseCommandPaletteArgs): UseCommandPaletteResult => {
  const [pinnedPaths, setPinnedPaths] = useState<string[]>(() => {
    try {
      const value = JSON.parse(localStorage.getItem(PINNED_STORAGE_KEY) || '[]');
      return Array.isArray(value) ? value : [];
    } catch {
      return [];
    }
  });

  const [cmdPaletteQuery, setCmdPaletteQuery] = useState('');

  const togglePin = useCallback((path: string) => {
    setPinnedPaths((prev) => {
      const next = prev.includes(path)
        ? prev.filter((entry) => entry !== path)
        : [...prev, path].slice(0, PIN_LIMIT);
      try {
        localStorage.setItem(PINNED_STORAGE_KEY, JSON.stringify(next));
      } catch {
        // ignore storage errors (private mode, quota, etc.)
      }
      return next;
    });
  }, []);

  const allNavItems = useMemo<CommandPaletteItem[]>(() => {
    const zh = language === 'zh';
    return [
      { path: '/dashboard', label: zh ? '功能中心' : 'Home', group: zh ? '首页' : 'Home' },
      { path: '/overview', label: zh ? '运营总览' : 'Overview', group: zh ? '实时监控' : 'Real-time' },
      { path: '/monitoring', label: zh ? '监控中心' : 'Monitoring Center', group: zh ? '实时监控' : 'Real-time' },
      { path: '/topology', label: zh ? '网络拓扑' : 'Topology', group: zh ? '实时监控' : 'Real-time' },
      { path: '/pam-audit', label: zh ? '受控审计' : 'PAM Audit', group: zh ? '终端接入' : 'Access' },
      { path: '/inventory/devices', label: t('deviceList'), group: zh ? '设备清单' : 'Inventory' },
      { path: '/inventory/servers', label: zh ? '服务器' : 'Servers', group: zh ? '设备清单' : 'Inventory' },
      { path: '/ipam', label: zh ? 'IP/VLAN 管理' : 'IP/VLAN Mgmt', group: zh ? '设备清单' : 'Inventory' },
      { path: '/assets/diagnose', label: zh ? 'NPA 智能路径诊断' : 'NPA Path Diagnostics', group: zh ? '设备清单' : 'Inventory' },
      { path: '/assets/nsot', label: zh ? '网络事实库' : 'Network Facts (NSOT)', group: zh ? '设备清单' : 'Inventory' },
      { path: '/assets/toolbox', label: zh ? 'IP 工具箱' : 'IP Toolbox', group: zh ? '设备清单' : 'Inventory' },
      { path: '/assets', label: zh ? '资产管理' : 'Assets', group: zh ? '设备清单' : 'Inventory' },
      { path: '/access', label: zh ? '操作工作台' : 'Operation Workspace', group: zh ? '终端接入' : 'Access' },
      { path: '/alerts', label: zh ? '告警信息' : 'Alert Desk', group: zh ? '告警管理' : 'Alerts' },
      { path: '/alert-history', label: zh ? '历史告警' : 'Alert History', group: zh ? '告警管理' : 'Alerts' },
      { path: '/alert-rules', label: zh ? '告警规则' : 'Alert Rules', group: zh ? '告警管理' : 'Alerts' },
      { path: '/maintenance', label: zh ? '维护期' : 'Maintenance', group: zh ? '告警管理' : 'Alerts' },
      { path: '/automation/execute', label: t('directExecution'), group: zh ? '作业自动化' : 'Automation' },
      { path: '/automation/scenarios', label: t('scenarioLibrary'), group: zh ? '作业自动化' : 'Automation' },
      { path: '/automation/schedule-history', label: zh ? '执行历史' : 'Execution History', group: zh ? '作业自动化' : 'Automation' },
      { path: '/automation/scheduled-jobs', label: zh ? '定时作业' : 'Scheduled Jobs', group: zh ? '作业自动化' : 'Automation' },
      { path: '/automation/metrics', label: zh ? '巡检指标项' : 'Inspection Metrics', group: zh ? '作业自动化' : 'Automation' },
      { path: '/automation/textfsm-templates', label: zh ? 'TextFSM 解析模板' : 'TextFSM Templates', group: zh ? '作业自动化' : 'Automation' },
      { path: '/automation/scripts', label: zh ? '脚本管理' : 'Script Management', group: zh ? '作业自动化' : 'Automation' },
      { path: '/config/backup', label: t('backupHistory'), group: zh ? '配置与合规' : 'Config & Compliance' },
      { path: '/config/diff', label: t('diffCompare'), group: zh ? '配置与合规' : 'Config & Compliance' },
      { path: '/config/search', label: t('configSearchTab'), group: zh ? '配置与合规' : 'Config & Compliance' },
      { path: '/config/schedule', label: zh ? '备份计划' : 'Backup Schedule', group: zh ? '配置与合规' : 'Config & Compliance' },
      { path: '/config/drift', label: zh ? '配置漂移' : 'Config Drift', group: zh ? '配置与合规' : 'Config & Compliance' },
      { path: '/config/templates', label: zh ? '配置管理' : 'Config Management', group: zh ? '配置与合规' : 'Config & Compliance' },
      { path: '/compliance', label: t('compliance'), group: zh ? '配置与合规' : 'Config & Compliance' },
      { path: '/capacity', label: zh ? '容量规划' : 'Capacity Planning', group: zh ? '分析报告' : 'Analytics' },
      { path: '/reports', label: zh ? '报表中心' : 'Reports', group: zh ? '分析报告' : 'Analytics' },
      { path: '/audit', label: t('auditLogs'), group: zh ? '平台管理' : 'Management' },
      { path: '/users', label: t('userManagement'), group: zh ? '平台管理' : 'Management' },
      { path: '/change-orders/all', label: zh ? '全部工单' : 'All Orders', group: zh ? '工单管理' : 'Tickets' },
      { path: '/change-orders/group-todo', label: zh ? '组内待办' : 'Group Todo', group: zh ? '工单管理' : 'Tickets' },
      { path: '/change-orders/my-todo', label: zh ? '个人待办' : 'My Todo', group: zh ? '工单管理' : 'Tickets' },
      { path: '/change-orders/participated', label: zh ? '我参与的' : 'My Participated', group: zh ? '工单管理' : 'Tickets' },
      { path: '/change-orders/focus', label: zh ? '我的关注' : 'My Focus', group: zh ? '工单管理' : 'Tickets' },
      { path: '/change-orders/drafts', label: zh ? '草稿箱' : 'Drafts', group: zh ? '工单管理' : 'Tickets' },
      { path: '/change-orders/new', label: zh ? '新建工单' : 'New Order', group: zh ? '工单管理' : 'Tickets' },
    ];
  }, [language, t]);

  const cmdPaletteFiltered = useMemo<CommandPaletteItem[]>(() => {
    const q = cmdPaletteQuery.trim().toLowerCase();
    if (!q) return allNavItems;
    return allNavItems.filter(
      (item) =>
        item.label.toLowerCase().includes(q)
        || item.group.toLowerCase().includes(q)
        || item.path.toLowerCase().includes(q),
    );
  }, [allNavItems, cmdPaletteQuery]);

  return {
    pinnedPaths,
    togglePin,
    cmdPaletteQuery,
    setCmdPaletteQuery,
    allNavItems,
    cmdPaletteFiltered,
  };
};
