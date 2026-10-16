import React from 'react';

interface AppRuntimeBoundaryProps {
  children: React.ReactNode;
  language: string;
}

interface AppRuntimeBoundaryState {
  hasError: boolean;
  errorMessage: string;
}

export class AppRuntimeBoundary extends React.Component<AppRuntimeBoundaryProps, AppRuntimeBoundaryState> {
  declare props: Readonly<AppRuntimeBoundaryProps>;
  state: AppRuntimeBoundaryState = { hasError: false, errorMessage: '' };

  static getDerivedStateFromError(error: Error): AppRuntimeBoundaryState {
    return { hasError: true, errorMessage: error?.message || 'Unknown runtime error' };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    console.error('Runtime error in authenticated app shell:', error, errorInfo);
  }

  handleReload = (): void => {
    window.location.reload();
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    const isZh = this.props.language === 'zh';
    return (
      <div className="min-h-screen bg-[#061324] text-white flex items-center justify-center p-6">
        <div className="max-w-xl w-full rounded-2xl border border-white/15 bg-white/5 backdrop-blur-sm p-6">
          <h2 className="text-xl font-bold">
            {isZh ? '页面运行异常，已阻止白屏' : 'Runtime issue detected, white screen prevented'}
          </h2>
          <p className="mt-3 text-sm text-white/75">
            {isZh
              ? '应用捕获到前端运行时错误。请点击“重新加载”恢复；若仍复现，请把此错误信息发给我继续定位。'
              : 'The app caught a frontend runtime error. Click Reload to recover. If it happens again, share this message for quick diagnosis.'}
          </p>
          <pre className="mt-4 rounded-xl bg-black/35 border border-white/10 p-3 text-xs text-red-200 whitespace-pre-wrap break-all">
            {this.state.errorMessage}
          </pre>
          <div className="mt-5 flex items-center gap-2">
            <button
              onClick={this.handleReload}
              className="px-4 py-2 rounded-lg bg-[#00bceb] text-white text-sm font-semibold hover:bg-[#0096bd] transition-colors"
            >
              {isZh ? '重新加载' : 'Reload'}
            </button>
          </div>
        </div>
      </div>
    );
  }
}
