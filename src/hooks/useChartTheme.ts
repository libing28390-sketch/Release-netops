import { useState, useEffect, useMemo } from 'react';

export function useChartTheme() {
  const [isDark, setIsDark] = useState(
    () => document.documentElement.getAttribute('data-theme') === 'dark'
  );

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDark(document.documentElement.getAttribute('data-theme') === 'dark');
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => observer.disconnect();
  }, []);

  return useMemo(() => ({
    isDark,
    grid: isDark ? 'rgba(148,163,184,0.10)' : '#f1f5f9',
    gridAlt: isDark ? 'rgba(148,163,184,0.12)' : '#dbe4ee',
    axis: isDark ? '#94a3b8' : '#94a3b8',
    axisAlt: isDark ? '#8899aa' : '#60748a',
    tooltipBg: isDark ? 'rgba(17,27,45,0.96)' : 'rgba(255,255,255,0.96)',
    tooltipBorder: isDark ? 'rgba(148,163,184,0.25)' : '#d9e3ef',
    tooltipText: isDark ? '#e8eef8' : '#334155',
    tooltipShadow: isDark ? '0 12px 28px rgba(0,0,0,0.35)' : '0 12px 28px rgba(15,23,42,0.10)',
    tooltipShadowLg: isDark ? '0 20px 25px -5px rgba(0,0,0,0.4)' : '0 20px 25px -5px rgb(0 0 0 / 0.1)',
    reference: isDark ? '#64748b' : '#94a3b8',
    brushFill: isDark ? '#1e293b' : '#eef2f6',
    cardBg: isDark ? '#111b2d' : '#ffffff',
    text: isDark ? '#e8eef8' : '#00172D',
    textMuted: isDark ? 'rgba(226,232,240,0.55)' : 'rgba(0,0,0,0.4)',
    textSecondary: isDark ? 'rgba(226,232,240,0.72)' : 'rgba(0,0,0,0.6)',
    border: isDark ? 'rgba(148,163,184,0.2)' : 'rgba(0,0,0,0.05)',
  }), [isDark]);
}
