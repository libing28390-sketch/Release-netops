export type TopologyOperationalState = 'up' | 'degraded' | 'down' | 'stale' | 'unknown';

export const normalizeTopologyPort = (value?: string) => String(value || '')
  .trim()
  .toLowerCase()
  // Neighbor parsers from different vendors sometimes append a literal
  // "Interface" suffix. It is descriptive noise, not part of the port key.
  .replace(/\binterface\b/g, '')
  .replace(/\s+/g, '')
  .replace(/interface$/, '')
  .replace(/^gigabitethernet/, 'gi')
  .replace(/^tengigabitethernet/, 'te')
  .replace(/^ten-gigabitethernet/, 'te')
  .replace(/^xgigabitethernet/, 'te')
  .replace(/^twentyfivegige/, 'tw')
  .replace(/^fortygigabitethernet/, 'fo')
  .replace(/^hundredgigabitethernet/, 'hu')
  .replace(/^hundred-gigabitethernet/, 'hu')
  .replace(/^fastethernet/, 'fa')
  .replace(/^ethernet/, 'eth')
  .replace(/^et(?=\d)/, 'eth')
  .replace(/^e(?=\d)/, 'eth')
  .replace(/^ge(?=\d)/, 'gi')
  .replace(/^bridge-aggregation/, 'bagg')
  .replace(/^bridgeaggregation/, 'bagg')
  .replace(/^link-aggregation/, 'bagg')
  .replace(/^linkaggregation/, 'bagg')
  .replace(/^route-aggregation/, 'ragg')
  .replace(/^routeaggregation/, 'ragg')
  .replace(/^eth-trunk/, 'eth-trunk')
  .replace(/^ethtrunk/, 'eth-trunk')
  .replace(/^port-channel/, 'po')
  .replace(/^portchannel/, 'po')
  .replace(/^bundle-ether/, 'be')
  .replace(/^bundleether/, 'be')
  .replace(/^aggregateport/, 'ag')
  .replace(/^aggregate-port/, 'ag')
  .replace(/^aggregated-ethernet/, 'ae')
  .replace(/^aggregatedethernet/, 'ae')
  .replace(/^loopback/, 'lo');

export const getTopologyOperationalTone = (state?: TopologyOperationalState) => {
  switch (state) {
    case 'up':
      return {
        badge: 'border-emerald-200 bg-emerald-100 text-emerald-700',
        panel: 'border-emerald-200/70 bg-emerald-50',
        dot: 'bg-emerald-500',
      };
    case 'degraded':
      return {
        badge: 'border-amber-200 bg-amber-100 text-amber-700',
        panel: 'border-amber-200/70 bg-amber-50',
        dot: 'bg-amber-500',
      };
    case 'down':
      return {
        badge: 'border-rose-200 bg-rose-100 text-rose-700',
        panel: 'border-rose-200/70 bg-rose-50',
        dot: 'bg-rose-500',
      };
    case 'stale':
      return {
        badge: 'border-sky-200 bg-sky-100 text-sky-700',
        panel: 'border-sky-200/70 bg-sky-50',
        dot: 'bg-sky-500',
      };
    default:
      return {
        badge: 'border-slate-200 bg-slate-100 text-slate-700',
        panel: 'border-slate-200/70 bg-slate-50',
        dot: 'bg-slate-400',
      };
  }
};
