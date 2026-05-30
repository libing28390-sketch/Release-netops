export interface RouteContext {
  activeTab: string;
  subPage: string;
  configPage: string;
  automationPage: string;
  inventorySubPage: string;
  changeOrderPage: string;
}

export function getRouteContext(pathname: string): RouteContext {
  const parts = pathname.split('/').filter(Boolean);
  const first = parts[0] || 'dashboard';
  const second = parts[1] || '';

  let activeTab = first;
  let subPage = second;
  let configPage = 'backup';
  let automationPage = '';
  let inventorySubPage = 'devices';
  let changeOrderPage = '';

  // 1. Dashboard / Home
  if (first === 'dashboard') {
    activeTab = 'dashboard';
  }
  // 2. Real-time Monitoring (/monitor/...)
  else if (first === 'monitor') {
    if (second === 'overview') {
      activeTab = 'overview';
    } else if (second === 'telemetry') {
      activeTab = 'monitoring';
    } else if (second === 'servers') {
      activeTab = 'server-monitoring';
    } else if (second === 'networks') {
      activeTab = 'network-monitoring';
    } else if (second === 'topology') {
      activeTab = 'topology';
    } else {
      activeTab = 'overview';
    }
  }
  // 3. Terminal Access (/access/...)
  else if (first === 'access') {
    if (second === 'workspace') {
      activeTab = 'access';
    } else if (second === 'pam-audit') {
      activeTab = 'pam-audit';
    } else {
      activeTab = 'access';
    }
  }
  // 4. Alerts (/alerts/...)
  else if (first === 'alerts') {
    if (second === 'desk') {
      activeTab = 'alerts';
    } else if (second === 'history') {
      activeTab = 'alert-history';
    } else if (second === 'rules') {
      activeTab = 'alert-rules';
    } else if (second === 'maintenance') {
      activeTab = 'maintenance';
    } else {
      activeTab = 'alerts';
    }
  }
  // 5. Assets & Config (/assets/...)
  else if (first === 'assets') {
    if (second === 'dashboard') {
      activeTab = 'assets';
    } else if (second === 'devices') {
      activeTab = 'inventory';
      inventorySubPage = 'devices';
    } else if (second === 'servers') {
      activeTab = 'inventory';
      inventorySubPage = 'servers';
    } else if (second === 'interfaces') {
      activeTab = 'inventory';
      inventorySubPage = 'interfaces';
    } else if (second === 'ipam') {
      activeTab = 'ipam';
    } else if (second === 'toolbox') {
      activeTab = 'ip-locator';
    } else if (second === 'tags') {
      activeTab = 'tags';
    } else if (second === 'racks') {
      activeTab = 'racks';
    } else {
      activeTab = 'assets';
    }
  }
  // 6. Config (/config/...)
  else if (first === 'config') {
    activeTab = 'config';
    configPage = second || 'backup';
  }
  // 7. Automation (/automation/...)
  else if (first === 'automation') {
    activeTab = 'automation';
    if (second === 'tasks') {
      automationPage = 'execute';
    } else if (second === 'inspections') {
      automationPage = 'inspection';
    } else if (second === 'records') {
      automationPage = 'inspection-records';
    } else if (second === 'schedules') {
      automationPage = 'schedule';
    } else if (second === 'history') {
      automationPage = 'history';
    } else if (second === 'scheduled-jobs') {
      automationPage = 'scheduled-jobs';
    } else if (second === 'metrics') {
      automationPage = 'metrics';
    } else if (second === 'textfsm') {
      automationPage = 'textfsm-templates';
    } else if (second === 'scripts') {
      automationPage = 'scripts';
    } else {
      automationPage = second || 'execute';
    }
  }
  // 8. Tickets (Change Orders) (/change-orders/...)
  else if (first === 'change-orders') {
    activeTab = 'change-orders';
    changeOrderPage = second || 'all';
  }
  // 9. Capacity (/capacity/...)
  else if (first === 'capacity') {
    if (second === 'analysis') {
      activeTab = 'capacity';
    } else if (second === 'reports') {
      activeTab = 'reports';
    } else {
      activeTab = 'capacity';
    }
  }
  // 10. Platform Management (/management/...)
  else if (first === 'management') {
    if (second === 'audit') {
      activeTab = 'audit';
    } else if (second === 'users') {
      activeTab = 'users';
    } else if (second === 'credentials') {
      activeTab = 'credentials';
    } else if (second === 'license') {
      activeTab = 'license';
    } else {
      activeTab = 'audit';
    }
  }
  // 11. Legacy or other direct paths
  else {
    if (first === 'overview') activeTab = 'overview';
    else if (first === 'monitoring') activeTab = 'monitoring';
    else if (first === 'topology') activeTab = 'topology';
    else if (first === 'pam-audit') activeTab = 'pam-audit';
    else if (first === 'alert-history') activeTab = 'alert-history';
    else if (first === 'alert-rules') activeTab = 'alert-rules';
    else if (first === 'maintenance') activeTab = 'maintenance';
    else if (first === 'ipam') activeTab = 'ipam';
    else if (first === 'ip-locator') activeTab = 'ip-locator';
    else if (first === 'tags') activeTab = 'tags';
    else if (first === 'racks') activeTab = 'racks';
    else if (first === 'audit') activeTab = 'audit';
    else if (first === 'users') activeTab = 'users';
    else if (first === 'credentials') activeTab = 'credentials';
    else if (first === 'license') activeTab = 'license';
    else if (first === 'reports') activeTab = 'reports';
  }

  return {
    activeTab,
    subPage,
    configPage,
    automationPage,
    inventorySubPage,
    changeOrderPage,
  };
}

