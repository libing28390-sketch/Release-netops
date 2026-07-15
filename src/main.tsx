import React, { StrictMode } from 'react';
import {createRoot} from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App.tsx';
import './index.css';
import { I18nProvider } from './i18n.tsx';

interface RootErrorBoundaryState {
  hasError: boolean;
  errorMessage: string;
}

class RootErrorBoundary extends React.Component<{ children: React.ReactNode }, RootErrorBoundaryState> {
  declare props: Readonly<{ children: React.ReactNode }>;
  state: RootErrorBoundaryState = { hasError: false, errorMessage: '' };

  static getDerivedStateFromError(error: Error): RootErrorBoundaryState {
    return { hasError: true, errorMessage: error?.message || 'Unknown runtime error' };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    console.error('Root runtime crash:', error, errorInfo);
  }

  render() {
    if (!this.state.hasError) return this.props.children;

    const isZh = navigator.language?.toLowerCase().includes('zh');
    return (
      <div style={{ minHeight: '100vh', background: '#061324', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <div style={{ maxWidth: 760, width: '100%', border: '1px solid rgba(255,255,255,0.18)', borderRadius: 16, padding: 20, background: 'rgba(255,255,255,0.06)' }}>
          <h2 style={{ margin: 0, fontSize: 22 }}>{isZh ? '应用崩溃已拦截（避免白屏）' : 'Application crash intercepted (white screen prevented)'}</h2>
          <p style={{ marginTop: 10, opacity: 0.86, lineHeight: 1.6 }}>
            {isZh
              ? '页面发生运行时错误，请点击重新加载。若问题持续，请把下方错误文本发给我继续修复。'
              : 'A runtime error occurred. Click Reload. If it persists, share the error text below for further fixing.'}
          </p>
          <pre style={{ marginTop: 14, padding: 12, borderRadius: 10, background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.12)', color: '#fecaca', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {this.state.errorMessage}
          </pre>
          <button
            onClick={() => window.location.reload()}
            style={{ marginTop: 14, padding: '9px 14px', borderRadius: 8, border: 'none', background: '#00bceb', color: '#fff', fontWeight: 700, cursor: 'pointer' }}
          >
            {isZh ? '重新加载' : 'Reload'}
          </button>
        </div>
      </div>
    );
  }
}

const savedThemeMode = localStorage.getItem('netops_theme_mode') as 'light' | 'dark' | null;
const initialResolvedTheme = savedThemeMode || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
document.documentElement.setAttribute('data-theme', initialResolvedTheme);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RootErrorBoundary>
      <I18nProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </I18nProvider>
    </RootErrorBoundary>
  </StrictMode>,
);
