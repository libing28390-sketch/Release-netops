export type TopologyOperationalState = 'up' | 'degraded' | 'down' | 'stale' | 'unknown';

export const normalizeTopologyPort = (value?: string) => String(value || '')
  .trim()
  .toLowerCase()
  .replace(/\s+/g, '')
  .replace(/^gigabitethernet/, 'gi')
  .replace(/^tengigabitethernet/, 'te')
  .replace(/^twentyfivegige/, 'tw')
  .replace(/^fortygigabitethernet/, 'fo')
  .replace(/^hundredgigabitethernet/, 'hu')
  .replace(/^ethernet/, 'eth')
  .replace(/^port-channel/, 'po')
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
