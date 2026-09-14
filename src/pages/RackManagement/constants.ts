export const ROLE_COLORS: Record<string, { bg: string; border: string; text: string; label: string; labelZh: string }> = {
  switch:      { bg: '#10b981', border: '#059669', text: '#ffffff', label: 'Switch',      labelZh: '交换机' },
  router:      { bg: '#3b82f6', border: '#2563eb', text: '#ffffff', label: 'Router',      labelZh: '路由器' },
  firewall:    { bg: '#ef4444', border: '#dc2626', text: '#ffffff', label: 'Firewall',    labelZh: '防火墙' },
  server:      { bg: '#6366f1', border: '#4f46e5', text: '#ffffff', label: 'Server',      labelZh: '服务器' },
  storage:     { bg: '#a855f7', border: '#9333ea', text: '#ffffff', label: 'Storage',     labelZh: '存储' },
  pdu:         { bg: '#f59e0b', border: '#d97706', text: '#000000', label: 'PDU',         labelZh: 'PDU' },
  ups:         { bg: '#eab308', border: '#ca8a04', text: '#000000', label: 'UPS',         labelZh: 'UPS' },
  patch_panel: { bg: '#64748b', border: '#475569', text: '#ffffff', label: 'Patch Panel', labelZh: '配线架' },
  other:       { bg: '#94a3b8', border: '#64748b', text: '#ffffff', label: 'Other',       labelZh: '其他' },
};

/** Pixels per rack unit */
export const U_PX = 26;
/** Width of the rack content area in px */
export const RACK_W = 400;
/** Width of each U-number label column */
export const LABEL_W = 28;

export const API = '/api';

export const INSTALL_ASSET_PAGE_SIZE = 500;

export const STATUS_LABEL: Record<string, { zh: string; en: string }> = {
  active:  { zh: '通电运行', en: 'Powered On' },
  offline: { zh: '已断电',   en: 'Powered Off' },
  planned: { zh: '规划中',   en: 'Planned' },
};
