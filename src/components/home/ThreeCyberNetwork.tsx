import React, { useEffect, useRef } from 'react';
import { createLoginParticleRenderer } from './loginParticleRenderer';

export const ThreeCyberNetwork: React.FC = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    try {
      return createLoginParticleRenderer(container);
    } catch {
      // WebGL is decorative; unsupported devices retain a usable login form.
      container.replaceChildren();
    }
  }, []);
  return <div ref={containerRef} aria-hidden="true" className="fixed inset-0 pointer-events-none z-0 overflow-hidden" />;
};

export default ThreeCyberNetwork;
