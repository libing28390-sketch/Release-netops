import React, { useMemo, useState } from 'react';
import { ArrowRight, Search, Server, Star, Terminal, Wifi, WifiOff } from 'lucide-react';
import type { Device } from '../types';
import PageHero from '../components/PageHero';
import { ActionButton, ActionIconButton } from '../components/ui/ActionIconButton';

interface AccessFavoritesTabProps {
  devices: Device[];
  language: string;
  favoriteDeviceIds: string[];
  onToggleFavorite: (device: Device) => void;
  onOpenWorkspace: (device?: Device) => void;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
}

const AccessFavoritesTab: React.FC<AccessFavoritesTabProps> = ({
  devices,
  language,
  favoriteDeviceIds,
  onToggleFavorite,
  onOpenWorkspace,
  showToast,
}) => {
  const isZh = language === 'zh';
  const [searchQuery, setSearchQuery] = useState('');

  const favoriteDevices = useMemo(() => {
    const favoriteSet = new Set(favoriteDeviceIds);
    const query = searchQuery.trim().toLowerCase();
    return devices
      .filter((device) => favoriteSet.has(device.id))
      .filter((device) => {
        if (!query) return true;
        return [device.hostname, device.ip_address, device.site_name, device.site, device.platform]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(query));
      });
  }, [devices, favoriteDeviceIds, searchQuery]);

  const staleFavoriteCount = favoriteDeviceIds.filter(
    (id) => !devices.some((device) => device.id === id),
  ).length;
  const onlineCount = favoriteDevices.filter((device) => device.status === 'online').length;

  const removeFavorite = (device: Device) => {
    onToggleFavorite(device);
    showToast(isZh ? `已取消收藏 ${device.hostname}` : `${device.hostname} removed from favorites`, 'success');
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <PageHero
        icon={Star}
        accent="#d97706"
        title={isZh ? '我的收藏' : 'My Favorites'}
        subtitle={isZh ? '快速访问常用网络设备' : 'Quick access to frequently used network devices'}
        actions={(
          <ActionButton icon={Terminal} variant="accent" onClick={() => onOpenWorkspace()}>
            {isZh ? '打开操作工作台' : 'Open workspace'}
          </ActionButton>
        )}
        extras={(
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="relative min-w-[240px] flex-1 sm:max-w-sm">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-300" />
              <input
                type="search"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder={isZh ? '搜索收藏的设备、IP 或站点...' : 'Search devices, IPs, or sites...'}
                aria-label={isZh ? '搜索我的收藏' : 'Search my favorites'}
                className="h-9 w-full rounded-xl border border-slate-200 bg-slate-50 pl-9 pr-3 text-xs font-medium text-slate-700 outline-none transition focus:border-amber-400 focus:bg-white focus:ring-4 focus:ring-amber-100"
              />
            </div>
            <span className="text-xs font-semibold text-slate-400">
              {isZh ? `${favoriteDeviceIds.length} 个收藏` : `${favoriteDeviceIds.length} favorites`}
            </span>
          </div>
        )}
      />

      <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
        <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
          {[
            { label: isZh ? '收藏设备' : 'Favorite devices', value: favoriteDeviceIds.length, icon: Star, tone: 'amber' },
            { label: isZh ? '在线设备' : 'Online devices', value: onlineCount, icon: Wifi, tone: 'emerald' },
            { label: isZh ? '待同步' : 'Needs sync', value: staleFavoriteCount, icon: WifiOff, tone: 'slate' },
          ].map((item) => {
            const Icon = item.icon;
            const tone = item.tone === 'amber'
              ? 'border-amber-100 bg-amber-50 text-amber-600'
              : item.tone === 'emerald'
                ? 'border-emerald-100 bg-emerald-50 text-emerald-600'
                : 'border-slate-200 bg-slate-50 text-slate-500';
            return (
              <div key={item.label} className="flex items-center gap-3 rounded-2xl border border-slate-200/80 bg-white px-4 py-3 shadow-sm">
                <span className={`flex h-10 w-10 items-center justify-center rounded-xl border ${tone}`}><Icon size={18} /></span>
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-400">{item.label}</div>
                  <div className="mt-0.5 text-xl font-black tabular-nums text-slate-800">{item.value}</div>
                </div>
              </div>
            );
          })}
        </div>

        {favoriteDeviceIds.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-amber-200 bg-amber-50/40 px-6 py-16 text-center">
            <Star className="mx-auto h-10 w-10 text-amber-300" />
            <h2 className="mt-4 text-base font-bold text-slate-700">{isZh ? '还没有收藏设备' : 'No favorite devices yet'}</h2>
            <p className="mx-auto mt-2 max-w-md text-sm text-slate-400">
              {isZh ? '在操作工作台的设备名称旁点击星标，即可将常用设备放到这里。' : 'Click the star beside a device in the workspace to keep it here.'}
            </p>
            <ActionButton className="mt-5" icon={Terminal} variant="accent" onClick={() => onOpenWorkspace()}>
              {isZh ? '去操作工作台' : 'Go to workspace'}
            </ActionButton>
          </div>
        ) : favoriteDevices.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50/70 px-6 py-16 text-center">
            <Search className="mx-auto h-10 w-10 text-slate-300" />
            <h2 className="mt-4 text-base font-bold text-slate-700">{isZh ? '没有匹配的收藏' : 'No matching favorites'}</h2>
            <p className="mt-2 text-sm text-slate-400">{isZh ? '请调整搜索条件后重试。' : 'Try a different search term.'}</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {favoriteDevices.map((device) => (
              <article key={device.id} className="group rounded-2xl border border-slate-200 bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:border-amber-200 hover:shadow-md">
                <div className="flex items-start gap-3">
                  <div className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-amber-100 bg-gradient-to-br from-amber-50 to-orange-50 text-amber-600">
                    <Server className="h-5 w-5" />
                    <span className={`absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-white ${device.status === 'online' ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <h2 className="truncate text-sm font-bold text-slate-800">{device.hostname}</h2>
                      <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-bold ${device.status === 'online' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-400'}`}>
                        {device.status === 'online' ? (isZh ? '在线' : 'Online') : (isZh ? '离线' : 'Offline')}
                      </span>
                    </div>
                    <p className="mt-1 font-mono text-xs text-slate-500">{device.ip_address}:{device.management_port || 22}</p>
                    <p className="mt-1 truncate text-[11px] font-medium text-slate-400">
                      {[device.site_name || device.site, device.platform, device.vendor].filter(Boolean).join(' · ') || (isZh ? '未配置描述' : 'No description')}
                    </p>
                  </div>
                  <ActionIconButton
                    icon={Star}
                    size="sm"
                    variant="default"
                    label={isZh ? `取消收藏 ${device.hostname}` : `Remove ${device.hostname} from favorites`}
                    className="text-amber-500 hover:bg-amber-50"
                    onClick={() => removeFavorite(device)}
                    iconSize={17}
                  />
                </div>
                <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                    {device.connection_method === 'none' ? (isZh ? '未配置终端' : 'No terminal') : (isZh ? '可发起访问' : 'Ready to access')}
                  </span>
                  <button type="button" onClick={() => onOpenWorkspace(device)} className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-bold text-cyan-700 transition hover:bg-cyan-50">
                    {isZh ? '在工作台访问' : 'Open in workspace'} <ArrowRight size={14} />
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}

        {staleFavoriteCount > 0 && (
          <p className="mt-4 text-[11px] text-slate-400">
            {isZh ? `${staleFavoriteCount} 个收藏设备当前不在资产清单中，恢复资产后会自动显示。` : `${staleFavoriteCount} favorite device(s) are not in the current inventory and will return when synced.`}
          </p>
        )}
      </div>
    </div>
  );
};

export default AccessFavoritesTab;
