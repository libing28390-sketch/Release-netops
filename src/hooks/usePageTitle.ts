import { useMemo } from 'react';
import type { Language } from '../i18n.tsx';

interface UsePageTitleArgs {
  activeTab: string;
  automationPage: string;
  configPage: string;
  inventorySubPage: string;
  changeOrderPage: string;
  ipamPage: string;
  cmdbPage?: string;
  language: Language;
  t: (key: string) => string;
}

/**
 * Resolves the human-readable page title for the current tab/sub-tab combination.
 * Extracted from App.tsx to keep the entry point focused on layout composition.
 */
export const usePageTitle = ({
  activeTab,
  automationPage,
  configPage,
  inventorySubPage,
  changeOrderPage,
  ipamPage,
  cmdbPage,
  language,
  t,
}: UsePageTitleArgs): string => {
  return useMemo(() => {
    if (activeTab === 'automation') {
      const map: Record<string, string> = {
        execute: t('directExecution'),
        scenarios: t('scenarioLibrary'),
        history: t('executionHistory'),
        inspection: language === 'zh' ? '巡检概览' : 'Inspection Overview',
        'inspection-records': language === 'zh' ? '巡检记录' : 'Inspection Records',
        schedule: language === 'zh' ? '执行计划' : 'Execution Schedules',
        'schedule-history': language === 'zh' ? '执行历史' : 'Execution History',
        'scheduled-jobs': language === 'zh' ? '定时作业' : 'Scheduled Jobs',
        metrics: language === 'zh' ? '巡检指标' : 'Inspection Metrics',
        scripts: language === 'zh' ? '脚本管理' : 'Script Management',
        'textfsm-templates': language === 'zh' ? 'TextFSM 解析模板' : 'TextFSM Parse Templates',
      };
      return map[automationPage] || automationPage;
    }
    if (activeTab === 'config') {
      const map: Record<string, string> = {
        backup: t('backupHistory'),
        diff: t('diffCompare'),
        search: t('configSearchTab'),
        schedule: language === 'zh' ? '备份计划' : 'Backup Schedule',
        drift: language === 'zh' ? '配置漂移' : 'Config Drift',
        templates: language === 'zh' ? '配置管理' : 'Config Management',
      };
      return map[configPage] || configPage;
    }
    if (activeTab === 'inventory') {
      const map: Record<string, string> = {
        devices: t('deviceList'),
        servers: language === 'zh' ? '服务器' : 'Servers',
      };
      return map[inventorySubPage] || inventorySubPage;
    }
    if (activeTab === 'users') return t('userManagement');
    if (activeTab === 'alerts') return language === 'zh' ? '告警信息' : 'Alert Desk';
    if (activeTab === 'alert-history') return language === 'zh' ? '历史告警' : 'Alert History';
    if (activeTab === 'alert-rules') return language === 'zh' ? '告警规则' : 'Alert Rules';
    if (activeTab === 'maintenance') return language === 'zh' ? '维护期' : 'Maintenance';
    if (activeTab === 'history' || activeTab === 'audit') return t('auditLogs');
    if (activeTab === 'reports') return language === 'zh' ? '报表中心' : 'Reports';
    if (activeTab === 'capacity') return language === 'zh' ? '容量规划' : 'Capacity Planning';
    if (activeTab === 'ipam') {
      const map: Record<string, string> = {
        prefixes: language === 'zh' ? 'Prefix管理' : 'Prefix Management',
        ips: language === 'zh' ? 'IP地址' : 'IP Address Management',
        pools: language === 'zh' ? '地址池' : 'IP Pool Management',
        vips: language === 'zh' ? 'VIP管理' : 'VIP Management',
        dhcp: language === 'zh' ? 'DHCP租约' : 'DHCP Leases',
        utilization: language === 'zh' ? '利用率分析' : 'IP Utilization Analysis',
      };
      return map[ipamPage] || (language === 'zh' ? 'IPAM管理' : 'IPAM Management');
    }
    if (activeTab === 'cmdb') {
      const map: Record<string, string> = {
        credentials: language === 'zh' ? '凭据中心' : 'Credentials',
        racks: language === 'zh' ? '机柜管理' : 'Rack Management',
        sites: language === 'zh' ? '站点管理' : 'Sites',
        vrfs: language === 'zh' ? 'VRF管理' : 'VRFs',
        vlans: language === 'zh' ? 'VLAN管理' : 'VLANs',
        tenants: language === 'zh' ? '租户管理' : 'Tenants',
      };
      return map[cmdbPage || ''] || (language === 'zh' ? 'CMDB 基础数据' : 'CMDB Core Data');
    }
    if (activeTab === 'ip-locator') return language === 'zh' ? 'IP 定位' : 'IP Locator';
    if (activeTab === 'assets') return language === 'zh' ? '资产管理' : 'Asset Management';
    if (activeTab === 'tags') return language === 'zh' ? '标签管理' : 'Tag Management';
    if (activeTab === 'racks') return language === 'zh' ? '机柜管理' : 'Rack Management';
    if (activeTab === 'credentials') return language === 'zh' ? '凭据管理' : 'Credential Management';
    if (activeTab === 'change-orders') {
      if (changeOrderPage === 'all') return language === 'zh' ? '全部工单' : 'All Orders';
      if (changeOrderPage === 'my-todo') return language === 'zh' ? '个人待办' : 'My Todo';
      if (changeOrderPage === 'group-todo') return language === 'zh' ? '组内待办' : 'Group Todo';
      if (changeOrderPage === 'participated') return language === 'zh' ? '我参与的' : 'My Participated';
      if (changeOrderPage === 'focus') return language === 'zh' ? '我的关注' : 'My Focus';
      if (changeOrderPage === 'drafts') return language === 'zh' ? '草稿箱' : 'Drafts';
      if (changeOrderPage === 'new') return language === 'zh' ? '新建工单' : 'New Order';
      return language === 'zh' ? '变更工单' : 'Change Orders';
    }
    if (activeTab === 'compliance') return t('compliance');
    if (activeTab === 'monitoring') return language === 'zh' ? '监控中心' : 'Monitoring Center';
    if (activeTab === 'access') return language === 'zh' ? '操作工作台' : 'Operation Workspace';
    if (activeTab === 'pam-audit') return language === 'zh' ? 'PAM 受控审计' : 'PAM Session Audit';
    if (activeTab === 'topology') return language === 'zh' ? '网络拓扑' : 'Topology';
    return t('dashboard');
  }, [activeTab, automationPage, configPage, inventorySubPage, changeOrderPage, ipamPage, cmdbPage, language, t]);
};
