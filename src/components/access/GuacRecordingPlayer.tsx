import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, Download, Loader2, Maximize2, Pause, Play, X, Minimize2 } from 'lucide-react';
import { authHeaders } from '../../api/http';
import { loadGuacamole, type GuacDisplay, type GuacSessionRecording } from './RemoteDesktopClient';
import { useEscapeClose } from '../../hooks/useEscapeClose';

interface GuacRecordingPlayerProps {
  sessionId: string;
  protocol: string;
  accessLevel: 'normal' | 'admin';
  sessionMeta?: {
    hostname?: string;
    ip?: string;
    loginUser?: string;
    requester?: string;
    connectedAt?: string | null;
  };
  isZh: boolean;
  onClose: () => void;
}

type RecordingFitMode = 'fit' | 'width';

function formatTime(milliseconds: number): string {
  const totalSeconds = Math.floor(Math.max(0, milliseconds) / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

function formatAspectRatio(width: number, height: number): string {
  const ratio = width / height;
  if (Math.abs(ratio - 16 / 9) < 0.025) return '16:9';
  if (Math.abs(ratio - 16 / 10) < 0.025) return '16:10';
  if (Math.abs(ratio - 4 / 3) < 0.025) return '4:3';
  if (Math.abs(ratio - 3 / 2) < 0.025) return '3:2';
  return `${ratio.toFixed(2)}:1`;
}

function recordingErrorMessage(status: number, isZh: boolean): string {
  if (status === 401) return isZh ? '登录状态已失效，请重新登录后重试回放。' : 'Your login session has expired. Sign in again and retry playback.';
  if (status === 403) return isZh ? '你没有权限读取此会话录像。' : 'You do not have permission to read this session recording.';
  if (status === 404) return isZh ? '录像文件不可用，可能仍在归档或已被清理。' : 'The recording is unavailable. It may still be archiving or may have been removed.';
  return isZh ? `录像加载失败（HTTP ${status}）。` : `Recording could not be loaded (HTTP ${status}).`;
}

export default function GuacRecordingPlayer({ sessionId, protocol, accessLevel, sessionMeta, isZh, onClose }: GuacRecordingPlayerProps) {
  useEscapeClose(true, onClose);
  const rootRef = useRef<HTMLDivElement>(null);
  const surfaceRef = useRef<HTMLDivElement>(null);
  const recordingRef = useRef<GuacSessionRecording | null>(null);
  const displayRef = useRef<GuacDisplay | null>(null);
  const blobRef = useRef<Blob | null>(null);
  const fitModeRef = useRef<RecordingFitMode>('fit');
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [errorMessage, setErrorMessage] = useState('');
  const [retryCount, setRetryCount] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [fitMode, setFitMode] = useState<RecordingFitMode>('fit');
  const [displaySize, setDisplaySize] = useState({ width: 0, height: 0 });
  const [duration, setDuration] = useState(0);
  const [position, setPosition] = useState(0);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const applyScale = useCallback(() => {
    const surface = surfaceRef.current;
    const display = displayRef.current;
    if (!surface || !display) return;
    const width = display.getWidth();
    const height = display.getHeight();
    if (!width || !height) return;
    setDisplaySize(current => current.width === width && current.height === height ? current : { width, height });
    const widthScale = surface.clientWidth / width;
    const fitScale = Math.min(widthScale, surface.clientHeight / height);
    const scale = fitModeRef.current === 'width' ? Math.min(2, widthScale) : Math.min(2, fitScale);
    display.scale(scale);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    let recording: GuacSessionRecording | null = null;
    let resizeObserver: ResizeObserver | null = null;
    setLoadState('loading');
    setErrorMessage('');
    setIsPlaying(false);
    setDisplaySize({ width: 0, height: 0 });
    setPosition(0);
    setDuration(0);

    const load = async () => {
      try {
        const response = await fetch(`/api/pam/sessions/${encodeURIComponent(sessionId)}/recording`, {
          headers: authHeaders(),
          signal: controller.signal,
          cache: 'no-store',
        });
        if (!response.ok) {
          setErrorMessage(recordingErrorMessage(response.status, isZh));
          setLoadState('error');
          return;
        }
        const blob = await response.blob();
        if (!active) return;
        if (blob.size === 0) {
          setErrorMessage(isZh ? '录像文件为空或尚未完成归档。' : 'The recording is empty or has not finished archiving.');
          setLoadState('error');
          return;
        }
        blobRef.current = blob;
        const Guac = await loadGuacamole();
        if (!active) return;
        const surface = surfaceRef.current;
        if (!surface) return;

        recording = new Guac.SessionRecording(blob, 250);
        recordingRef.current = recording;
        const display = recording.getDisplay();
        displayRef.current = display;
        const displayElement = display.getElement();
        displayElement.style.margin = 'auto';
        surface.replaceChildren(displayElement);
        display.onresize = applyScale;
        recording.onerror = message => {
          if (!active) return;
          setErrorMessage(message || (isZh ? '录像格式无效或无法解码。' : 'The recording is invalid or could not be decoded.'));
          setLoadState('error');
        };
        recording.onload = () => {
          if (!active) return;
          const recordingDuration = recording?.getDuration() || 0;
          if (recordingDuration <= 0) {
            setErrorMessage(isZh ? '录像中没有可播放的图形帧。' : 'The recording contains no playable display frames.');
            setLoadState('error');
            return;
          }
          setDuration(recordingDuration);
          setLoadState('ready');
          applyScale();
        };
        recording.onprogress = recordingDuration => {
          if (active && recordingDuration > 0) {
            setDuration(recordingDuration);
            setLoadState(current => current === 'loading' ? 'ready' : current);
          }
        };
        recording.onseek = playbackPosition => {
          if (active) setPosition(playbackPosition);
        };
        recording.onplay = () => { if (active) setIsPlaying(true); };
        recording.onpause = () => { if (active) setIsPlaying(false); };

        resizeObserver = new ResizeObserver(applyScale);
        resizeObserver.observe(surface);
      } catch (error) {
        if (!active || (error instanceof DOMException && error.name === 'AbortError')) return;
        setErrorMessage(error instanceof Error ? error.message : (isZh ? '录像读取失败。' : 'The recording could not be read.'));
        setLoadState('error');
      }
    };

    void load();
    return () => {
      active = false;
      controller.abort();
      resizeObserver?.disconnect();
      if (recording) {
        recording.onplay = null;
        recording.onpause = null;
        recording.onseek = null;
        recording.onprogress = null;
        recording.onload = null;
        recording.onerror = null;
        recording.abort();
      }
      if (displayRef.current) displayRef.current.onresize = null;
      surfaceRef.current?.replaceChildren();
      recordingRef.current = null;
      displayRef.current = null;
      blobRef.current = null;
    };
  }, [applyScale, isZh, retryCount, sessionId]);

  useEffect(() => {
    fitModeRef.current = fitMode;
    applyScale();
  }, [applyScale, fitMode]);

  useEffect(() => {
    const handleFullscreenChange = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
  }, []);

  const togglePlayback = () => {
    const recording = recordingRef.current;
    if (!recording || loadState !== 'ready') return;
    if (recording.isPlaying()) recording.pause();
    else recording.play();
  };

  const seekTo = (event: React.ChangeEvent<HTMLInputElement>) => {
    const target = Number(event.target.value);
    setPosition(target);
    recordingRef.current?.seek(target);
  };

  const toggleFullscreen = async () => {
    try {
      if (!document.fullscreenElement) await rootRef.current?.requestFullscreen();
      else await document.exitFullscreen();
    } catch {
      setErrorMessage(isZh ? '浏览器未允许切换全屏。' : 'The browser did not allow fullscreen mode.');
    }
  };

  const downloadRecording = () => {
    const blob = blobRef.current;
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${sessionId}.guac`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div ref={rootRef} className="fixed inset-0 z-[200] flex flex-col bg-slate-950 text-white">
      <header className="flex min-h-14 shrink-0 items-center gap-3 border-b border-white/10 bg-slate-900 px-4 py-3 sm:px-6">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-bold">{isZh ? '图形会话录像' : 'Graphical session recording'} <span className="ml-1 text-[10px] font-black uppercase text-violet-300">{protocol.toUpperCase()}</span></h2>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-slate-400">
            {sessionMeta?.hostname && <span>{sessionMeta.hostname}</span>}
            {sessionMeta?.ip && <span className="font-mono">{sessionMeta.ip}</span>}
            {sessionMeta?.loginUser && <span>{isZh ? '账号' : 'Account'}: {sessionMeta.loginUser}</span>}
            <span>{accessLevel === 'admin' ? (isZh ? '管理员访问' : 'Administrator access') : (isZh ? '普通访问' : 'Normal access')}</span>
            {displaySize.width > 0 && displaySize.height > 0 && (
              <span className="font-mono text-slate-500">
                {isZh ? '源画面' : 'Source'} {displaySize.width}×{displaySize.height} · {formatAspectRatio(displaySize.width, displaySize.height)}
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={() => setFitMode('fit')}
            aria-pressed={fitMode === 'fit'}
            aria-label={isZh ? '完整适配录像画面' : 'Fit the complete recording display'}
            className={`rounded-lg px-2 py-2 text-[10px] font-bold transition ${fitMode === 'fit' ? 'bg-cyan-600 text-white' : 'bg-white/10 text-slate-300 hover:bg-white/15'}`}
          >{isZh ? '适配窗口' : 'Fit'}</button>
          <button
            type="button"
            onClick={() => setFitMode('width')}
            aria-pressed={fitMode === 'width'}
            aria-label={isZh ? '按播放器宽度放大录像画面' : 'Scale recording to player width'}
            className={`rounded-lg px-2 py-2 text-[10px] font-bold transition ${fitMode === 'width' ? 'bg-cyan-600 text-white' : 'bg-white/10 text-slate-300 hover:bg-white/15'}`}
          >{isZh ? '适配宽度' : 'Fit width'}</button>
          <button type="button" onClick={downloadRecording} disabled={!blobRef.current} aria-label={isZh ? '下载录像' : 'Download recording'} className="rounded-lg bg-white/10 p-2 text-slate-300 hover:bg-white/15 disabled:opacity-40"><Download size={15} /></button>
          <button type="button" onClick={() => void toggleFullscreen()} aria-label={isFullscreen ? (isZh ? '退出全屏' : 'Exit fullscreen') : (isZh ? '全屏' : 'Fullscreen')} className="rounded-lg bg-white/10 p-2 text-slate-300 hover:bg-white/15">{isFullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}</button>
          <button type="button" onClick={onClose} aria-label={isZh ? '关闭播放器' : 'Close player'} className="rounded-lg bg-white/10 p-2 text-slate-300 hover:bg-white/15"><X size={15} /></button>
        </div>
      </header>

      <main className="relative min-h-0 flex-1 overflow-hidden bg-black">
        <div ref={surfaceRef} className={`flex h-full w-full overflow-auto ${fitMode === 'fit' ? 'items-center justify-center' : 'items-start justify-start'}`} />
        {loadState === 'loading' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/75 text-center">
            <Loader2 size={28} className="animate-spin text-cyan-400" />
            <p className="text-sm text-slate-300">{isZh ? '正在读取并解析 .guac 录像…' : 'Reading and parsing .guac recording…'}</p>
          </div>
        )}
        {loadState === 'error' && (
          <div role="alert" className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/85 px-6 text-center">
            <AlertCircle size={28} className="text-rose-400" />
            <p className="text-sm font-bold">{isZh ? '图形录像不可播放' : 'Graphical recording could not be played'}</p>
            <p className="max-w-xl break-words text-xs text-slate-400">{errorMessage}</p>
            <button type="button" onClick={() => setRetryCount(count => count + 1)} className="rounded-lg bg-slate-700 px-4 py-2 text-xs font-bold hover:bg-slate-600">{isZh ? '重试' : 'Retry'}</button>
          </div>
        )}
      </main>

      <footer className="shrink-0 border-t border-white/10 bg-slate-900 px-4 py-3 sm:px-6">
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" onClick={togglePlayback} disabled={loadState !== 'ready'} aria-label={isPlaying ? (isZh ? '暂停' : 'Pause') : (isZh ? '播放' : 'Play')} className="flex h-9 w-9 items-center justify-center rounded-full bg-cyan-600 text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-40">
            {isPlaying ? <Pause size={15} fill="currentColor" /> : <Play size={15} fill="currentColor" className="ml-0.5" />}
          </button>
          <span className="min-w-[82px] text-xs font-mono text-slate-300">{formatTime(position)} / {formatTime(duration)}</span>
          <input
            type="range"
            min={0}
            max={Math.max(duration, 1)}
            step={100}
            value={Math.min(position, duration)}
            onChange={seekTo}
            disabled={loadState !== 'ready' || duration <= 0}
            aria-label={isZh ? '录像进度' : 'Recording progress'}
            className="min-w-[150px] flex-1 accent-cyan-500 disabled:opacity-40"
          />
          <span className="ml-auto text-[10px] text-slate-500">{isZh ? '原生 Guacamole 会话录像' : 'Native Guacamole session recording'}</span>
        </div>
      </footer>
    </div>
  );
}
