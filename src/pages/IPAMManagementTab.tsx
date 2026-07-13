import React, { Suspense, lazy } from 'react';
import EnterpriseWorkflowPanel from './IPVlan/components/EnterpriseWorkflowPanel';

// Lazy load children to optimize initial package size
const PrefixManagementTab = lazy(() => import('./IPVlan/PrefixManagementTab'));
const IPAddressTab = lazy(() => import('./IPVlan/IPAddressTab'));
const IPPoolTab = lazy(() => import('./IPVlan/IPPoolTab'));
const VIPManagementTab = lazy(() => import('./IPVlan/VIPManagementTab'));
const DHCPLeaseTab = lazy(() => import('./IPVlan/DHCPLeaseTab'));
const IPUtilizationTab = lazy(() => import('./IPVlan/IPUtilizationTab'));
const IPReconciliationTab = lazy(() => import('./IPVlan/IPReconciliationTab'));

interface IPAMManagementTabProps {
  language: string;
  t: (key: string) => string;
  ipamPage: string;
}

const lazyPanelFallback = (
  <div className="flex min-h-[240px] items-center justify-center rounded-2xl border border-black/5 bg-white/70 text-sm text-black/40">
    Loading IPAM panel...
  </div>
);

const IPAMManagementTab: React.FC<IPAMManagementTabProps> = ({ language, t, ipamPage }) => {
  return (
    <>
      <EnterpriseWorkflowPanel language={language} />
      <Suspense fallback={lazyPanelFallback}>
        {ipamPage === 'prefixes' && <PrefixManagementTab language={language} t={t} />}
        {ipamPage === 'ips' && <IPAddressTab language={language} t={t} />}
        {ipamPage === 'pools' && <IPPoolTab language={language} t={t} />}
        {ipamPage === 'vips' && <VIPManagementTab language={language} t={t} />}
        {ipamPage === 'dhcp' && <DHCPLeaseTab language={language} t={t} />}
        {ipamPage === 'utilization' && <IPUtilizationTab language={language} t={t} />}
        {ipamPage === 'reconciliation' && <IPReconciliationTab language={language} t={t} />}
      </Suspense>
    </>
  );
};

export default IPAMManagementTab;
