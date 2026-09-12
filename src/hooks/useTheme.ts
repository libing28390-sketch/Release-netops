import { useState, useEffect } from 'react';
import type { ThemeMode } from '../types';

export const useTheme = () => {
  const getResolvedTheme = (mode: ThemeMode): 'light' | 'dark' => {
    return mode;
  };

  const [themeMode, setThemeMode] = useState<ThemeMode>(() => {
    const saved = localStorage.getItem('netops_theme_mode') as ThemeMode | null;
    if (!saved || (saved !== 'light' && saved !== 'dark')) {
      return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    return saved;
  });

  const [resolvedTheme, setResolvedTheme] = useState<'light' | 'dark'>(() => 
    getResolvedTheme(
      ((localStorage.getItem('netops_theme_mode') as ThemeMode | null) || 
      (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')) as ThemeMode
    )
  );

  useEffect(() => {
    localStorage.setItem('netops_theme_mode', themeMode);
    const next = getResolvedTheme(themeMode);
    setResolvedTheme(next);
    document.documentElement.setAttribute('data-theme', next);
  }, [themeMode]);

  return {
    themeMode,
    setThemeMode,
    resolvedTheme
  };
};
