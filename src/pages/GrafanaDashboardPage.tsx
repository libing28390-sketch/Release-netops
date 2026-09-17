import React, { useCallback, useEffect, useState } from 'react';
import { BarChart2, ExternalLink, RefreshCw, ShieldCheck } from 'lucide-react';
import PageHero from '../components/PageHero';

interface GrafanaDashboardPageProps {
  language: 'zh' | 'en';
}

type GrafanaStatus = 'checking' | 'ready' | 'unavailable';

const DASHBOARD_URL = '/grafana/d/nexora-network-overview/nexora-network-overview?orgId=1&refresh=30s&kiosk=tv&theme=light';

const GrafanaDashboardPage: React.FC<GrafanaDashboardPageProps> = ({ language }) => {
  const zh = language === 'zh';
  const [frameKey, setFrameKey] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [status, setStatus] = useState<GrafanaStatus>('checking');

  const checkGrafana = useCallback(async () => {
    setStatus('checking');
    setLoaded(false);
    try {
      // Vite/Nexora's SPA fallback returns index.html for /grafana/* when no
      // Grafana container is present.  Probe the health API first so that we
      // never render the SPA inside its own iframe.
      const response = await fetch('/grafana/api/health?_=' + Date.now(), {
        headers: { Accept: 'application/json' },
        credentials: 'same-origin',
        cache: 'no-store',
      });
      const contentType = response.headers.get('content-type') || '';
      const payload = await response.json().catch(() => null) as { database?: string; version?: string } | null;
      if (!response.ok || !contentType.toLowerCase().includes('json') || !payload || (payload.database !== 'ok' && !payload.version)) {
        throw new Error('Grafana health check failed');
      }
      setStatus('ready');
      setFrameKey(value => value + 1);
    } catch {
      setStatus('unavailable');
    }
  }, []);

  useEffect(() => { void checkGrafana(); }, [checkGrafana]);

  const statusText = status === 'checking'
    ? (zh ? '正在检查 Grafana 服务…' : 'Checking Grafana…')
    : status === 'ready'
      ? (zh ? 'Grafana 已连接' : 'Grafana connected')
      : (zh ? 'Grafana 尚未部署或当前不可用' : 'Grafana is not deployed or unavailable');

  return <div className="flex h-full min-h-0 flex-col overflow-hidden">
    <PageHero
      icon={BarChart2}
      title={zh ? '监控大盘' : 'Monitoring dashboards'}
      subtitle={zh ? 'Grafana 全局趋势、设备排行与采集健康视图' : 'Grafana trends, device rankings, and collection health'}
      actions={<div className="flex items-center gap-2">
        <button type="button" onClick={() => void checkGrafana()} disabled={status === 'checking'} className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm hover:border-cyan-300 disabled:cursor-wait disabled:opacity-60"><RefreshCw size={14} className={status === 'checking' ? 'animate-spin' : ''} />{zh ? '检查并刷新' : 'Check & refresh'}</button>
        {status === 'ready' && <a href="/grafana/" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded-xl bg-cyan-600 px-3 py-2 text-xs font-bold text-white shadow-sm hover:bg-cyan-700"><ExternalLink size={14} />{zh ? '打开 Grafana' : 'Open Grafana'}</a>}
      </div>}
    />
    <div className="min-h-0 flex-1 overflow-auto bg-slate-50 p-4 md:p-6">
      <div className="mx-auto flex min-h-full max-w-[1800px] flex-col gap-4">
        <div className={`flex flex-wrap items-center justify-between gap-2 rounded-xl border px-4 py-3 text-xs ${status === 'ready' ? 'border-emerald-100 bg-emerald-50/80 text-emerald-900' : 'border-amber-100 bg-amber-50/80 text-amber-900'}`}>
          <div className="flex items-center gap-2"><ShieldCheck size={15} className={status === 'ready' ? 'text-emerald-700' : 'text-amber-700'} /><span>{statusText}</span></div>
          <span className="text-[11px] opacity-80">{zh ? '数据源：VictoriaMetrics（Prometheus 兼容 API）· 默认 30 秒刷新' : 'Source: VictoriaMetrics (Prometheus-compatible API) · 30s refresh'}</span>
        </div>

        {status === 'ready' && <div className="relative min-h-[620px] flex-1 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <iframe key={frameKey} title={zh ? 'Grafana 监控大盘' : 'Grafana monitoring dashboard'} src={DASHBOARD_URL} onLoad={() => setLoaded(true)} className="h-full min-h-[620px] w-full border-0" allow="fullscreen" />
          {!loaded && <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-white/85 text-sm text-slate-500"><RefreshCw size={16} className="mr-2 animate-spin" />{zh ? '正在加载 Grafana 大盘…' : 'Loading Grafana dashboard…'}</div>}
        </div>}

        {status !== 'ready' && <section className="flex min-h-[420px] flex-1 items-center justify-center rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="max-w-xl text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-100 text-slate-500"><BarChart2 size={27} /></div>
            <h2 className="mt-4 text-lg font-bold text-slate-900">{status === 'checking' ? (zh ? '正在连接 Grafana' : 'Connecting to Grafana') : (zh ? 'Grafana 大盘暂不可用' : 'Grafana dashboard unavailable')}</h2>
            <p className="mt-2 text-sm leading-6 text-slate-500">{status === 'checking'
              ? (zh ? '正在确认反向代理返回的是 Grafana 服务，而不是 Nexora 的 SPA 页面。' : 'Verifying that the proxy returns Grafana rather than the Nexora SPA fallback.')
              : (zh ? '当前页面不会嵌套错误的 Nexora 页面。部署并启动 Grafana 后点击“检查并刷新”即可加载大盘。' : 'The page will not embed the Nexora SPA fallback. Deploy Grafana, then click “Check & refresh”.')}</p>
            {status === 'unavailable' && <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3 text-left text-xs leading-5 text-slate-600"><p className="font-semibold text-slate-800">{zh ? '部署提示' : 'Deployment note'}</p><p className="mt-1">{zh ? 'Docker Compose 需要同时运行 grafana、victoriametrics 和 nginx；Grafana 数据源会自动指向 VictoriaMetrics。' : 'Docker Compose should run grafana, victoriametrics, and nginx together; the datasource points to VictoriaMetrics automatically.'}</p></div>}
            <button type="button" onClick={() => void checkGrafana()} disabled={status === 'checking'} className="mt-5 inline-flex items-center gap-2 rounded-xl bg-cyan-600 px-4 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-cyan-700 disabled:opacity-60"><RefreshCw size={14} className={status === 'checking' ? 'animate-spin' : ''} />{zh ? '重新检查' : 'Check again'}</button>
          </div>
        </section>}
      </div>
    </div>
  </div>;
};

export default GrafanaDashboardPage;
