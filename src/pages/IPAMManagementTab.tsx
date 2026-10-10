import React, { Suspense, lazy, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

// Lazy load children to optimize initial package size
const PrefixManagementTab = lazy(() => import('./IPVlan/PrefixManagementTab'));
const IPAddressTab = lazy(() => import('./IPVlan/IPAddressTab'));
const IPPoolTab = lazy(() => import('./IPVlan/IPPoolTab'));
const VIPManagementTab = lazy(() => import('./IPVlan/VIPManagementTab'));
const DHCPLeaseTab = lazy(() => import('./IPVlan/DHCPLeaseTab'));
const IPUtilizationTab = lazy(() => import('./IPVlan/IPUtilizationTab'));
const IPReconciliationTab = lazy(() => import('./IPVlan/IPReconciliationTab'));
const IPLocatorPage = lazy(() => import('./IPLocatorPage'));

interface IPAMPrefixContext {
  id: string;
  prefix: string;
  name?: string;
  tenant_id?: string | null;
}

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
  const navigate = useNavigate();
  const location = useLocation();
  const zh = language === 'zh';
  const [prefixes, setPrefixes] = useState<IPAMPrefixContext[]>([]);
  const prefixId = useMemo(
    () => new URLSearchParams(location.search).get('prefix_id') || '',
    [location.search],
  );
  const selectedPrefix = prefixes.find((prefix) => prefix.id === prefixId) || null;
  const isAddressSpace = ['prefixes', 'ips', 'pools', 'vips'].includes(ipamPage);
  const showsAddressData = ['ips', 'pools', 'vips'].includes(ipamPage);

  useEffect(() => {
    if (!isAddressSpace) return;
    const token = localStorage.getItem('netops_token');
    fetch('/api/ipam/subnets', { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((response) => (response.ok ? response.json() : []))
      .then((payload) => {
        const data = Array.isArray(payload) ? payload : (payload?.items || payload?.data || []);
        setPrefixes(Array.isArray(data) ? data : []);
      })
      .catch((error) => console.error('Failed to load IPAM prefix context', error));
  }, [isAddressSpace]);

  const changePrefixContext = (nextPrefixId: string) => {
    const params = new URLSearchParams(location.search);
    if (nextPrefixId) params.set('prefix_id', nextPrefixId);
    else params.delete('prefix_id');
    const query = params.toString();
    navigate(`${location.pathname}${query ? `?${query}` : ''}`);
  };

  return (
    <div className="flex h-full min-h-0 w-full min-w-0 flex-col overflow-hidden">
      {isAddressSpace && showsAddressData && (
        <div className="flex flex-shrink-0 flex-col gap-3 border-b border-slate-200/70 bg-white/70 px-6 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <span className="whitespace-nowrap text-[11px] font-bold uppercase tracking-wider text-slate-400">
              {zh ? '当前网段' : 'Current Prefix'}
            </span>
            {ipamPage === 'ips' ? (
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-slate-800">
                  {selectedPrefix ? `${selectedPrefix.prefix}${selectedPrefix.name ? ` · ${selectedPrefix.name}` : ''}` : (zh ? '全部网段' : 'All prefixes')}
                </div>
                <div className="text-[11px] text-slate-400">
                  {zh ? '使用下方筛选器切换网段；地址池和 VIP 会沿用当前选择' : 'Change the prefix in the filter below; Pools and VIPs will use the same scope'}
                </div>
              </div>
            ) : (
              <select
                aria-label={zh ? '当前工作网段' : 'Current working prefix'}
                value={prefixId}
                onChange={(event) => changePrefixContext(event.target.value)}
                className="min-w-0 max-w-[min(70vw,34rem)] rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 outline-none transition focus:border-blue-400"
              >
                <option value="">{zh ? '全部网段' : 'All prefixes'}</option>
                {prefixes.map((prefix) => (
                  <option key={prefix.id} value={prefix.id}>
                    {prefix.prefix}{prefix.name ? ` · ${prefix.name}` : ''}
                  </option>
                ))}
              </select>
            )}
          </div>
          <p className="text-xs text-slate-400">
            {zh ? 'IP 地址、地址池和 VIP 共用此网段范围' : 'IP addresses, pools, and VIPs share this prefix scope'}
          </p>
        </div>
      )}

      <div className="min-h-0 w-full min-w-0 flex-1 overflow-hidden">
        <Suspense fallback={lazyPanelFallback}>
          {ipamPage === 'prefixes' && <PrefixManagementTab language={language} t={t} />}
          {ipamPage === 'ips' && <IPAddressTab key={prefixId} language={language} t={t} />}
          {ipamPage === 'pools' && <IPPoolTab language={language} t={t} prefixId={prefixId} />}
          {ipamPage === 'vips' && <VIPManagementTab language={language} t={t} prefixId={prefixId} prefixScope={selectedPrefix} />}
          {ipamPage === 'dhcp' && <DHCPLeaseTab language={language} t={t} />}
          {ipamPage === 'utilization' && <IPUtilizationTab language={language} t={t} />}
          {ipamPage === 'reconciliation' && <IPReconciliationTab language={language} t={t} />}
          {ipamPage === 'locate' && <IPLocatorPage language={language} t={t} mode="toolbox" />}
        </Suspense>
      </div>
    </div>
  );
};

export default IPAMManagementTab;
