import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, Loader2, Maximize2, Minimize2, Minus, Plus, X } from 'lucide-react';
import type { PamRemoteDesktopSession } from '../../api/pamRemoteDesktop';
import type { RemoteDesktopProtocol } from '../../pages/AssetManagement/types';

interface GuacStatus {
  code?: number;
  message?: string;
}

export interface GuacDisplay {
  getElement(): HTMLElement;
  getWidth(): number;
  getHeight(): number;
  scale(value: number): void;
  onresize: ((width: number, height: number) => void) | null;
}

interface GuacClient {
  getDisplay(): GuacDisplay;
  connect(data?: string): void;
  disconnect(): void;
  sendKeyEvent(pressed: boolean, keysym: number): void;
  sendMouseState(mouseState: unknown, applyDisplayScale?: boolean): void;
  sendSize(width: number, height: number): void;
  onstatechange: ((state: number) => void) | null;
  onerror: ((status: GuacStatus) => void) | null;
}

interface GuacKeyboard {
  onkeydown: ((keysym: number) => void) | null;
  onkeyup: ((keysym: number) => void) | null;
  reset(): void;
}

interface GuacMouse {
  onmousedown: ((state: unknown) => void) | null;
  onmouseup: ((state: unknown) => void) | null;
  onmousemove: ((state: unknown) => void) | null;
}

export interface GuacSessionRecording {
  getDisplay(): GuacDisplay;
  getDuration(): number;
  getPosition(): number;
  isPlaying(): boolean;
  play(): void;
  pause(): void;
  seek(position: number, callback?: () => void): void;
  abort(): void;
  onerror: ((message: string) => void) | null;
  onload: (() => void) | null;
  onplay: (() => void) | null;
  onpause: (() => void) | null;
  onprogress: ((duration: number, parsedSize: number) => void) | null;
  onseek: ((position: number, current: number, total: number) => void) | null;
}

export interface GuacamoleNamespace {
  WebSocketTunnel: new (url: string) => unknown;
  Client: {
    new (tunnel: unknown): GuacClient;
    State: Record<string, number>;
  };
  Keyboard: new (element: HTMLElement) => GuacKeyboard;
  Mouse: new (element: HTMLElement) => GuacMouse;
  SessionRecording: new (source: Blob, refreshInterval?: number) => GuacSessionRecording;
}

declare global {
  interface Window {
    Guacamole?: GuacamoleNamespace;
  }
}

interface RemoteDesktopClientProps {
  session: PamRemoteDesktopSession;
  protocol: RemoteDesktopProtocol;
  hostname: string;
  language: string;
  onClose: () => void;
}

type ConnectionState = 'loading' | 'connecting' | 'connected' | 'closed' | 'error';
type ZoomMode = 'fit' | '100' | '75' | '50';

const REMOTE_DISPLAY_ASPECT_RATIO = 16 / 9;
const MAX_REMOTE_DISPLAY_WIDTH = 1920;
const MAX_REMOTE_DISPLAY_HEIGHT = 1080;

function getPreferredDisplaySize(viewportWidth: number, viewportHeight: number): { width: number; height: number } | null {
  if (viewportWidth <= 0 || viewportHeight <= 0) return null;

  let width = viewportWidth;
  let height = viewportHeight;
  if (width / height > REMOTE_DISPLAY_ASPECT_RATIO) width = height * REMOTE_DISPLAY_ASPECT_RATIO;
  else height = width / REMOTE_DISPLAY_ASPECT_RATIO;

  const resolutionScale = Math.min(1, MAX_REMOTE_DISPLAY_WIDTH / width, MAX_REMOTE_DISPLAY_HEIGHT / height);
  return {
    width: Math.max(1, Math.round(width * resolutionScale)),
    height: Math.max(1, Math.round(height * resolutionScale)),
  };
}

let guacScriptPromise: Promise<GuacamoleNamespace> | null = null;

export function loadGuacamole(): Promise<GuacamoleNamespace> {
  if (window.Guacamole) return Promise.resolve(window.Guacamole);
  if (guacScriptPromise) return guacScriptPromise;

  guacScriptPromise = new Promise<GuacamoleNamespace>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = '/vendor/guacamole/1.6.0/all.min.js';
    script.async = true;
    script.onload = () => window.Guacamole
      ? resolve(window.Guacamole)
      : reject(new Error('Apache Guacamole client library did not initialize.'));
    script.onerror = () => reject(new Error('Apache Guacamole client library could not be loaded.'));
    document.head.appendChild(script);
  }).catch(error => {
    guacScriptPromise = null;
    throw error;
  });
  return guacScriptPromise;
}

function toSameOriginWebSocketUrl(path: string): string {
  const url = new URL(path, window.location.href);
  if (url.origin !== window.location.origin) throw new Error('Remote desktop must use the same-origin gateway.');
  url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}

function connectionLabel(state: ConnectionState, isZh: boolean): string {
  if (state === 'loading') return isZh ? '加载客户端' : 'Loading client';
  if (state === 'connecting') return isZh ? '连接中' : 'Connecting';
  if (state === 'connected') return isZh ? '已连接' : 'Connected';
  if (state === 'closed') return isZh ? '连接已关闭' : 'Disconnected';
  return isZh ? '连接错误' : 'Connection error';
}

export default function RemoteDesktopClient({ session, protocol, hostname, language, onClose }: RemoteDesktopClientProps) {
  const isZh = language === 'zh';
  const rootRef = useRef<HTMLDivElement>(null);
  const surfaceRef = useRef<HTMLDivElement>(null);
  const clientRef = useRef<GuacClient | null>(null);
  const keyboardRef = useRef<GuacKeyboard | null>(null);
  const displayRef = useRef<GuacDisplay | null>(null);
  const connectedRef = useRef(false);
  const zoomModeRef = useRef<ZoomMode>('fit');
  const [state, setState] = useState<ConnectionState>('loading');
  const [error, setError] = useState('');
  const [zoomMode, setZoomMode] = useState<ZoomMode>('fit');
  const [isFullscreen, setIsFullscreen] = useState(false);

  const applyScale = useCallback(() => {
    const surface = surfaceRef.current;
    const display = displayRef.current;
    if (!surface || !display) return;
    const width = display.getWidth();
    const height = display.getHeight();
    if (!width || !height) return;

    const mode = zoomModeRef.current;
    const fixedScale = mode === '100' ? 1 : mode === '75' ? 0.75 : mode === '50' ? 0.5 : null;
    const fitScale = Math.min(surface.clientWidth / width, surface.clientHeight / height);
    display.scale(fixedScale ?? Math.max(0.1, Math.min(2, fitScale)));
  }, []);

  useEffect(() => {
    let active = true;
    let resizeObserver: ResizeObserver | null = null;
    let client: GuacClient | null = null;
    let keyboard: GuacKeyboard | null = null;
    let display: GuacDisplay | null = null;
    let displayElement: HTMLElement | null = null;
    let resizeTimer: number | undefined;
    setState('loading');
    setError('');

    const start = async () => {
      try {
        const Guac = await loadGuacamole();
        if (!active) return;
        const surface = surfaceRef.current;
        if (!surface) return;
        const tunnel = new Guac.WebSocketTunnel(toSameOriginWebSocketUrl(session.connect.ws_url));
        client = new Guac.Client(tunnel);
        clientRef.current = client;
        display = client.getDisplay();
        displayRef.current = display;
        displayElement = display.getElement();
        displayElement.style.margin = 'auto';
        surface.replaceChildren(displayElement);

        const mouse = new Guac.Mouse(displayElement);
        mouse.onmousedown = mouse.onmouseup = mouse.onmousemove = mouseState => client?.sendMouseState(mouseState, true);
        keyboard = new Guac.Keyboard(surface);
        keyboardRef.current = keyboard;
        keyboard.onkeydown = keysym => client?.sendKeyEvent(true, keysym);
        keyboard.onkeyup = keysym => client?.sendKeyEvent(false, keysym);

        const stateValues = Guac.Client.State;
        client.onstatechange = connectionState => {
          if (!active) return;
          if (connectionState === stateValues?.CONNECTED) {
            connectedRef.current = true;
            setState('connected');
            const bounds = surface.getBoundingClientRect();
            const displaySize = getPreferredDisplaySize(bounds.width, bounds.height);
            if (displaySize) client?.sendSize(displaySize.width, displaySize.height);
            applyScale();
            surface.focus({ preventScroll: true });
          } else if (connectionState === stateValues?.CONNECTING || connectionState === stateValues?.WAITING) {
            setState('connecting');
          } else if (connectionState === stateValues?.DISCONNECTED) {
            connectedRef.current = false;
            setState('closed');
          }
        };
        client.onerror = status => {
          if (!active) return;
          connectedRef.current = false;
          setState('error');
          setError(status?.code != null ? `Gateway status ${status.code}` : (isZh ? '网关连接失败。' : 'The gateway connection failed.'));
        };

        resizeObserver = new ResizeObserver(() => {
          if (!connectedRef.current || !client) return;
          if (resizeTimer) window.clearTimeout(resizeTimer);
          resizeTimer = window.setTimeout(() => {
            const bounds = surface.getBoundingClientRect();
            const displaySize = getPreferredDisplaySize(bounds.width, bounds.height);
            if (displaySize) client?.sendSize(displaySize.width, displaySize.height);
            applyScale();
          }, 120);
        });
        resizeObserver.observe(surface);
        display.onresize = applyScale;
        setState('connecting');
        client.connect();
      } catch (connectError) {
        if (!active) return;
        setState('error');
        setError(connectError instanceof Error ? connectError.message : (isZh ? '无法加载远程桌面客户端。' : 'Unable to load the remote desktop client.'));
      }
    };

    void start();
    return () => {
      active = false;
      connectedRef.current = false;
      if (resizeTimer) window.clearTimeout(resizeTimer);
      resizeObserver?.disconnect();
      if (keyboard) {
        keyboard.reset();
        keyboard.onkeydown = null;
        keyboard.onkeyup = null;
      }
      if (display) display.onresize = null;
      if (client) {
        client.onstatechange = null;
        client.onerror = null;
        client.disconnect();
      }
      displayElement?.remove();
      clientRef.current = null;
      keyboardRef.current = null;
      displayRef.current = null;
    };
  }, [applyScale, isZh, session.connect.ws_url]);

  useEffect(() => {
    zoomModeRef.current = zoomMode;
    applyScale();
  }, [applyScale, zoomMode]);

  useEffect(() => {
    const handleFullscreenChange = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
  }, []);

  const toggleFullscreen = async () => {
    try {
      if (!document.fullscreenElement) await rootRef.current?.requestFullscreen();
      else await document.exitFullscreen();
    } catch {
      setError(isZh ? '浏览器未允许切换全屏。' : 'The browser did not allow fullscreen mode.');
    }
  };

  const changeZoom = (direction: -1 | 1) => {
    setZoomMode(current => {
      const modes: ZoomMode[] = ['50', '75', '100'];
      if (current === 'fit') return direction > 0 ? '100' : '75';
      const index = modes.indexOf(current);
      return modes[Math.max(0, Math.min(modes.length - 1, index + direction))];
    });
  };

  return (
    <div ref={rootRef} className="fixed inset-0 z-[180] flex flex-col bg-slate-950 text-white">
      <header className="flex min-h-14 shrink-0 items-center gap-3 border-b border-white/10 bg-slate-900 px-3 py-2 sm:px-5">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-bold">{hostname} <span className="ml-1 text-[10px] font-black uppercase text-violet-300">{protocol}</span></p>
          <p className="mt-0.5 text-[10px] text-slate-400">{connectionLabel(state, isZh)}{state === 'connected' ? ` · ${isZh ? '按需点击画面聚焦键盘输入' : 'Click the display to focus keyboard input'}` : ''}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <button type="button" onClick={() => setZoomMode('fit')} className={`rounded-lg px-2.5 py-1.5 text-[10px] font-bold ${zoomMode === 'fit' ? 'bg-cyan-500 text-white' : 'bg-white/10 text-slate-300 hover:bg-white/15'}`}>{isZh ? '适配' : 'Fit'}</button>
          <button type="button" onClick={() => changeZoom(-1)} aria-label={isZh ? '缩小' : 'Zoom out'} className="rounded-lg bg-white/10 p-1.5 text-slate-300 hover:bg-white/15"><Minus size={14} /></button>
          <button type="button" onClick={() => changeZoom(1)} aria-label={isZh ? '放大' : 'Zoom in'} className="rounded-lg bg-white/10 p-1.5 text-slate-300 hover:bg-white/15"><Plus size={14} /></button>
          <span className="hidden min-w-10 text-center text-[10px] text-slate-400 sm:inline">{zoomMode === 'fit' ? (isZh ? '适配' : 'Fit') : `${zoomMode}%`}</span>
          <button type="button" onClick={() => void toggleFullscreen()} aria-label={isFullscreen ? (isZh ? '退出全屏' : 'Exit fullscreen') : (isZh ? '全屏' : 'Fullscreen')} className="rounded-lg bg-white/10 p-1.5 text-slate-300 hover:bg-white/15">
            {isFullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
          </button>
          <button type="button" onClick={onClose} aria-label={isZh ? '断开会话' : 'Disconnect session'} className="rounded-lg bg-rose-500/15 p-1.5 text-rose-300 hover:bg-rose-500/25"><X size={16} /></button>
        </div>
      </header>
      <main className="relative min-h-0 flex-1 overflow-hidden bg-black">
        <div
          ref={surfaceRef}
          tabIndex={0}
          role="application"
          aria-label={isZh ? `${protocol.toUpperCase()} 远程桌面` : `${protocol.toUpperCase()} remote desktop`}
          onPointerDown={() => surfaceRef.current?.focus({ preventScroll: true })}
          onBlur={() => keyboardRef.current?.reset()}
          className="flex h-full w-full items-center justify-center overflow-auto outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyan-500"
        />
        {(state === 'loading' || state === 'connecting') && (
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/60 text-center">
            <Loader2 size={28} className="animate-spin text-cyan-400" />
            <p className="text-sm text-slate-200">{state === 'loading' ? (isZh ? '正在加载远程桌面客户端…' : 'Loading remote desktop client…') : (isZh ? '正在建立受控会话…' : 'Connecting to the controlled session…')}</p>
          </div>
        )}
        {(state === 'error' || state === 'closed') && (
          <div role="alert" className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/85 px-6 text-center">
            <AlertCircle size={28} className="text-rose-400" />
            <p className="text-sm font-bold text-white">{state === 'closed' ? (isZh ? '远程会话已断开' : 'Remote session disconnected') : (isZh ? '远程桌面连接失败' : 'Remote desktop connection failed')}</p>
            {error && <p className="max-w-lg break-words text-xs text-slate-400">{error}</p>}
            <p className="max-w-lg text-[10px] leading-4 text-slate-500">{isZh ? '关闭此窗口后，请重新提交访问申请以创建新会话。' : 'Close this window and submit a new access request to create another session.'}</p>
            <button type="button" onClick={onClose} className="mt-1 rounded-lg bg-slate-700 px-4 py-2 text-xs font-bold text-white hover:bg-slate-600">{isZh ? '关闭' : 'Close'}</button>
          </div>
        )}
      </main>
      <footer className="shrink-0 border-t border-white/10 bg-slate-900 px-4 py-2 text-[10px] text-slate-500">
        {isZh ? '图形会话操作以录像审计，不提供 SSH 命令解析或命令拦截。' : 'Graphical actions are audited through session recording; SSH command parsing and filtering do not apply.'}
      </footer>
    </div>
  );
}
