export interface RouteContext {
  activeTab: string;
  subPage: string;
  configPage: string;
  automationPage: string;
  inventorySubPage: string;
  changeOrderPage: string;
}

export function getRouteContext(pathname: string): RouteContext {
  const parts = pathname.split('/');
  const activeTab = parts[1] || 'dashboard';
  const subPage = parts[2] || '';
  return {
    activeTab,
    subPage,
    configPage: subPage || 'backup',
    automationPage: subPage,
    inventorySubPage: subPage || 'devices',
    changeOrderPage: subPage,
  };
}

