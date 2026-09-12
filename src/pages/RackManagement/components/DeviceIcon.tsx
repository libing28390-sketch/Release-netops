import React from 'react';
import { Layers, ShieldAlert, Server, HardDrive, Zap, Package } from 'lucide-react';

interface DeviceIconProps {
  role?: string;
  name?: string;
  model?: string;
  size?: number;
}

export const DeviceIcon: React.FC<DeviceIconProps> = ({ role, name, model, size = 14 }) => {
  const combined = `${role || ''} ${name || ''} ${model || ''}`.trim().toLowerCase();
  const norm = (role || '').trim().toLowerCase();
  
  if (norm === 'switch') return <Layers size={size} />;
  if (norm === 'router') return <Zap size={size} />;
  if (norm === 'firewall') return <ShieldAlert size={size} />;
  if (norm === 'server') return <Server size={size} />;
  if (norm === 'storage') return <HardDrive size={size} />;
  if (norm === 'ups' || norm === 'pdu') return <Zap size={size} />;

  if (combined.includes('server') || combined.includes('srv') || combined.includes('host') || combined.includes('blade') || combined.includes('ubuntu') || combined.includes('linux')) return <Server size={size} />;
  if (combined.includes('switch') || combined.includes('sw') || combined.includes('tor') || combined.includes('core') || combined.includes('dist') || combined.includes('access') || combined.includes('acc')) return <Layers size={size} />;
  if (combined.includes('router') || combined.includes('rtr') || combined.includes('gateway')) return <Zap size={size} />;
  if (combined.includes('firewall') || combined.includes('fw') || combined.includes('sec')) return <ShieldAlert size={size} />;
  if (combined.includes('storage') || combined.includes('san') || combined.includes('nas')) return <HardDrive size={size} />;
  if (combined.includes('ups') || combined.includes('pdu') || combined.includes('power') || combined.includes('apc')) return <Zap size={size} />;

  return <Package size={size} />;
};

export default DeviceIcon;
