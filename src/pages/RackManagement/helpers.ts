import { ROLE_COLORS, U_PX } from './constants';
import { DeviceType, RackLayout, RackDevice } from './types';

export function getNormalizedRoleColor(role?: string, name?: string, model?: string) {
  if (!role && !name && !model) return ROLE_COLORS.other;

  const combined = `${role || ''} ${name || ''} ${model || ''}`.trim().toLowerCase();
  const roleNorm = (role || '').trim().toLowerCase();

  if (ROLE_COLORS[roleNorm]) return ROLE_COLORS[roleNorm];

  if (combined.includes('switch') || combined.includes('sw') || combined.includes('tor') || 
      combined.includes('core') || combined.includes('dist') || combined.includes('spine') || 
      combined.includes('leaf') || combined.includes('access') || combined.includes('acc')) {
    if (combined.includes('server') || combined.includes('srv') || combined.includes('ubuntu') || combined.includes('linux') || combined.includes('win') || combined.includes('dell') || combined.includes('hpe')) {
      return ROLE_COLORS.server;
    }
    return ROLE_COLORS.switch;
  }

  if (combined.includes('server') || combined.includes('srv') || combined.includes('host') || 
      combined.includes('blade') || combined.includes('compute') || combined.includes('node') || 
      combined.includes('vm') || combined.includes('esxi') || combined.includes('ubuntu') || 
      combined.includes('linux') || combined.includes('centos') || combined.includes('windows') || 
      combined.includes('poweredge') || combined.includes('proliant')) {
    return ROLE_COLORS.server;
  }

  if (combined.includes('router') || combined.includes('rtr') || combined.includes('gateway') || 
      combined.includes('isr') || combined.includes('asr') || combined.includes('wan') || 
      combined.includes('border')) {
    return ROLE_COLORS.router;
  }

  if (combined.includes('firewall') || combined.includes('fw') || combined.includes('security') || 
      combined.includes('sec') || combined.includes('usg') || combined.includes('asa') || 
      combined.includes('forti') || combined.includes('palo')) {
    return ROLE_COLORS.firewall;
  }

  if (combined.includes('storage') || combined.includes('san') || combined.includes('nas') || combined.includes('disk')) {
    return ROLE_COLORS.storage;
  }

  if (combined.includes('pdu') || combined.includes('power')) return ROLE_COLORS.pdu;
  if (combined.includes('ups') || combined.includes('battery') || combined.includes('apc')) return ROLE_COLORS.ups;
  if (combined.includes('patch') || combined.includes('panel') || combined.includes('pp')) return ROLE_COLORS.patch_panel;
  if (combined.includes('load') || combined.includes('balancer') || combined.includes('lb')) return ROLE_COLORS.switch;

  return ROLE_COLORS.other;
}

export function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('netops_token') || '';
  return { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };
}

export function formatErrorDetail(detail: any): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((err: any) => {
      if (typeof err === 'object' && err.msg) {
        const field = Array.isArray(err.loc) ? err.loc[err.loc.length - 1] : 'field';
        return `${field}: ${err.msg}`;
      }
      return String(err);
    }).join('; ');
  }
  if (typeof detail === 'object') return JSON.stringify(detail);
  return 'Request failed';
}

export async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: authHeaders() });
  const json = await res.json();
  if (!res.ok || !json.success) {
    const detail = formatErrorDetail(json.detail || json.message || 'Request failed');
    throw new Error(detail);
  }
  return json.data;
}

export async function postJson<T>(url: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(url, { method: 'POST', headers: authHeaders(), body: JSON.stringify(body) });
  const json = await res.json();
  if (!res.ok || !json.success) {
    const detail = formatErrorDetail(json.detail || json.message || 'Request failed');
    throw new Error(detail);
  }
  return json.data;
}

export async function putJson<T>(url: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(url, { method: 'PUT', headers: authHeaders(), body: JSON.stringify(body) });
  const json = await res.json();
  if (!res.ok || !json.success) {
    const detail = formatErrorDetail(json.detail || json.message || 'Request failed');
    throw new Error(detail);
  }
  return json.data;
}

export async function patchJson<T>(url: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(url, { method: 'PATCH', headers: authHeaders(), body: JSON.stringify(body) });
  const json = await res.json();
  if (!res.ok || !json.success) {
    const detail = formatErrorDetail(json.detail || json.message || 'Request failed');
    throw new Error(detail);
  }
  return json.data;
}

export async function deleteJson(url: string): Promise<void> {
  const res = await fetch(url, { method: 'DELETE', headers: authHeaders() });
  const json = await res.json();
  if (!res.ok || !json.success) {
    const detail = formatErrorDetail(json.detail || json.message || 'Request failed');
    throw new Error(detail);
  }
}

export function matchDeviceTypeId(
  asset: { vendor: string; model: string; u_height?: number },
  types: DeviceType[],
): string {
  if (!types.length) return '';
  const norm = (s: string) => (s || '').trim().toLowerCase().replace(/\s+/g, ' ');
  const av = norm(asset.vendor);
  const am = norm(asset.model);
  if (!am && !av) return '';

  const exacts = types.filter(dt => norm(dt.vendor) === av && norm(dt.model) === am);
  if (exacts.length === 1) return exacts[0].id;
  if (exacts.length > 1 && asset.u_height != null && asset.u_height > 0) {
    const byH = exacts.find(dt => dt.u_height === asset.u_height);
    if (byH) return byH.id;
  }
  if (exacts.length > 0) return exacts[0].id;

  const modelOnly = types.filter(dt => norm(dt.model) === am);
  if (modelOnly.length === 1) return modelOnly[0].id;

  const vendorLoose = types.filter(
    dt => av && norm(dt.vendor) === av && am && (norm(dt.model).includes(am) || am.includes(norm(dt.model))),
  );
  if (vendorLoose.length === 1) return vendorLoose[0].id;

  const fuzzy = types.filter(dt => am && (am.includes(norm(dt.model)) || norm(dt.model).includes(am)));
  if (fuzzy.length === 1) return fuzzy[0].id;

  return '';
}

export function uToY(uNumber: number, totalU: number): number {
  return (totalU - uNumber) * U_PX;
}

export function yToU(y: number, totalU: number): number {
  const u = totalU - Math.floor(y / U_PX);
  return Math.max(1, Math.min(totalU, u));
}

export function hasConflict(
  targetU: number,
  uHeight: number,
  totalU: number,
  devices: RackDevice[],
  excludeId?: string,
): boolean {
  if (targetU < 1 || targetU + uHeight - 1 > totalU) return true;
  const tTop = targetU + uHeight - 1;
  for (const d of devices) {
    if (d.id === excludeId) continue;
    // Non-U/unknown placements do not participate in standard U-slot
    // collision checks. The backend applies the same rule transactionally.
    if ((d.mount_kind || 'u_mount') !== 'u_mount' || d.start_u == null) continue;
    const dHeight = d.height_u ?? d.u_height ?? 0;
    if (dHeight < 1) continue;
    const dTop = d.start_u + dHeight - 1;
    if (targetU <= dTop && tTop >= d.start_u) return true;
  }
  return false;
}

export function findFirstFreeStartU(
  totalU: number,
  uHeight: number,
  onSideDevices: RackDevice[],
  strategy?: 'bottom_first' | 'top_first',
): number | null {
  if (uHeight < 1 || totalU < 1) return null;
  if (strategy === 'top_first') {
    for (let u = totalU - uHeight + 1; u >= 1; u--) {
      if (!hasConflict(u, uHeight, totalU, onSideDevices)) return u;
    }
  } else {
    for (let u = 1; u <= totalU - uHeight + 1; u++) {
      if (!hasConflict(u, uHeight, totalU, onSideDevices)) return u;
    }
  }
  return null;
}

export function pickStartUForAsset(
  layout: RackLayout,
  position: string,
  uH: number,
  asset: { planned_start_u?: number | null; rack_unit?: string },
): number {
  const side = layout.devices.filter(d => d.position === position);
  let candidate: number | null = null;
  if (asset.planned_start_u != null && asset.planned_start_u >= 1) {
    candidate = asset.planned_start_u;
  } else {
    const ru = String(asset.rack_unit || '').trim();
    if (/^\d+$/.test(ru)) {
      const n = parseInt(ru, 10);
      if (n >= 1 && n <= layout.total_u) candidate = n;
    }
  }
  if (candidate != null && !hasConflict(candidate, uH, layout.total_u, side)) {
    return candidate;
  }
  return findFirstFreeStartU(layout.total_u, uH, side, layout.placement_strategy) ?? 1;
}

