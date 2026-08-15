import React from 'react';

interface PowerLedProps {
  status: string;
  size?: number;
}

export const PowerLed: React.FC<PowerLedProps> = ({ status, size = 8 }) => {
  const color = status === 'active' ? '#4ade80' : status === 'planned' ? '#fbbf24' : '#ef4444';
  return (
    <span
      className="inline-block rounded-full flex-shrink-0"
      style={{
        width: size,
        height: size,
        background: color,
        boxShadow: status === 'active' ? `0 0 6px ${color}80` : 'none',
      }}
    />
  );
};

export default PowerLed;
