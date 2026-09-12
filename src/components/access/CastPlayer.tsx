import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Terminal as XTerm } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import { authHeaders } from '../../api/http';
import { 
  Play, 
  Pause, 
  RotateCcw, 
  X, 
  Clock, 
  User, 
  Monitor, 
  Download, 
  AlertCircle, 
  Loader2,
  Maximize2,
  Minimize2,
  Terminal as TerminalIcon,
  Gauge
} from 'lucide-react';
import 'xterm/css/xterm.css';
import { ActionIconButton } from '../ui/ActionIconButton';

interface SessionMeta {
  hostname?: string;
  ip?: string;
  loginUser?: string;
  requester?: string;
  connectedAt?: string | null;
}

interface CastPlayerProps {
  sessionId: string;
  totalDuration: number;
  sessionMeta?: SessionMeta;
  onClose: () => void;
  isZh?: boolean;
}

interface CastEvent {
  time: number;
  data: string;
}

const SPEED_OPTIONS = [0.5, 1.0, 2.0, 4.0, 8.0];

export default function CastPlayer({
  sessionId,
  totalDuration,
  sessionMeta,
  onClose,
  isZh = true,
}: CastPlayerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<XTerm | null>(null);
  const fitAddonRef  = useRef<FitAddon | null>(null);
  const playerRef    = useRef<HTMLDivElement>(null);

  const [isPlaying, setIsPlaying]   = useState(false);
  const [progress, setProgress]     = useState(0);
  const [duration, setDuration]     = useState(Math.max(totalDuration || 0, 1));
  const [loadState, setLoadState]   = useState<'loading' | 'ready' | 'error'>('loading');
  const [errorMsg, setErrorMsg]     = useState('');
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [playbackSpeed, setPlaybackSpeed] = useState(1.0);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const eventsRef      = useRef<CastEvent[]>([]);
  const currentIdxRef  = useRef(0);
  const rafRef         = useRef<number | null>(null);
  const startTimeRef   = useRef(0);
  const pauseOffsetRef = useRef(0);
  const speedRef       = useRef(1.0);

  // Sync speedRef with state for tick function
  useEffect(() => {
    speedRef.current = playbackSpeed;
    if (isPlaying) {
      // Re-calculate startTimeRef to avoid jump when speed changes during play
      const now = performance.now();
      startTimeRef.current = now - (pauseOffsetRef.current * 1000) / speedRef.current;
    }
  }, [playbackSpeed, isPlaying]);

  // ── Fullscreen Logic ────────────────────────────────────────────────
  useEffect(() => {
    const handleFsChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
      // Refit terminal after layout change
      setTimeout(() => {
        try { fitAddonRef.current?.fit(); } catch (_) {}
      }, 100);
    };
    document.addEventListener('fullscreenchange', handleFsChange);
    return () => document.removeEventListener('fullscreenchange', handleFsChange);
  }, []);

  const toggleFullscreen = () => {
    if (!playerRef.current) return;
    if (!document.fullscreenElement) {
      playerRef.current.requestFullscreen().catch(err => {
        console.error(`Error attempting to enable full-screen mode: ${err.message}`);
      });
    } else {
      document.exitFullscreen();
    }
  };

  // ── Step 1: init xterm after mount ──────────────────────────────────
  useEffect(() => {
    const node = containerRef.current;
    if (!node || xtermRef.current) return;

    const term = new XTerm({
      cursorBlink: false,
      fontFamily: '"Cascadia Code", "JetBrains Mono", Menlo, monospace',
      fontSize: 13,
      theme: {
        background: '#0f172a',
        foreground: '#e2e8f0',
        cursor: '#22d3ee',
        selectionBackground: '#22d3ee33',
      },
      scrollback: 10000,
      convertEol: false,
    });

    const fitAddon = new FitAddon();
    fitAddonRef.current = fitAddon;
    term.loadAddon(fitAddon);
    term.open(node);

    // Fit after a frame so the container has its final CSS size
    requestAnimationFrame(() => {
      try { fitAddon.fit(); } catch (_) {}
    });

    xtermRef.current = term;

    // Resize observer
    const ro = new ResizeObserver(() => {
      try { fitAddon.fit(); } catch (_) {}
    });
    ro.observe(node);

    return () => {
      ro.disconnect();
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      term.dispose();
      xtermRef.current = null;
    };
  }, []); // run once on mount

  // ── Step 2: load recording ───────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoadState('loading');
      setErrorMsg('');
      try {
        const res = await fetch(`/api/pam/sessions/${sessionId}/recording`, {
          headers: authHeaders(),
        });
        if (!res.ok) {
          const body = await res.text().catch(() => '');
          if (res.status === 401) {
            throw new Error(isZh ? '登录会话已过期，请重新登录后重试回放。' : 'Your login session has expired. Sign in again and retry playback.');
          }
          throw new Error(`HTTP ${res.status}${body ? ': ' + body.slice(0, 120) : ''}`);
        }

        const text = await res.text();
        if (cancelled) return;

        const lines = text.split('\n').filter(l => l.trim());
        if (lines.length < 2) throw new Error('Recording has no events (only header line found)');

        // Parse Asciinema v2 — line 0 is the JSON header, rest are events
        const events: CastEvent[] = [];
        let maxTime = 0;

        for (let i = 1; i < lines.length; i++) {
          try {
            const parsed = JSON.parse(lines[i]);
            if (Array.isArray(parsed) && parsed[1] === 'o') {
              const t = Number(parsed[0]);
              const d = String(parsed[2]);
              events.push({ time: t, data: d });
              if (t > maxTime) maxTime = t;
            }
          } catch (_) { /* skip malformed lines */ }
        }

        if (events.length === 0) throw new Error('No output events found in recording');

        eventsRef.current = events;
        currentIdxRef.current = 0;
        pauseOffsetRef.current = 0;
        const effectiveDuration = Math.max(totalDuration || 0, maxTime, 0.5);
        setDuration(effectiveDuration);
        setLoadState('ready');

        // Write first frame — wait until xterm is initialised
        const writeFirst = () => {
          if (xtermRef.current) {
            xtermRef.current.clear();
            xtermRef.current.write(events[0].data);
            // The first frame is already on screen; do not render it twice
            // when the animation loop starts.
            currentIdxRef.current = 1;
          } else {
            requestAnimationFrame(writeFirst);
          }
        };
        writeFirst();

      } catch (err: any) {
        if (!cancelled) {
          setErrorMsg(err.message || 'Unknown error');
          setLoadState('error');
        }
      }
    };

    load();
    return () => { cancelled = true; };
  }, [isZh, loadAttempt, sessionId, totalDuration]);

  // ── Playback controls ────────────────────────────────────────────────
  const doReset = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    setIsPlaying(false);
    currentIdxRef.current = 0;
    pauseOffsetRef.current = 0;
    setProgress(0);
    xtermRef.current?.clear();
    const events = eventsRef.current;
    if (events.length > 0) {
      xtermRef.current?.write(events[0].data);
      currentIdxRef.current = 1;
    }
  }, []);

  const play = useCallback(() => {
    if (isPlaying || loadState !== 'ready') return;
    if (pauseOffsetRef.current >= duration) {
      doReset();
      return;
    }
    setIsPlaying(true);
    
    // Adjust startTimeRef based on current pauseOffset and current speed
    startTimeRef.current = performance.now() - (pauseOffsetRef.current * 1000) / speedRef.current;

    const tick = () => {
      const now = performance.now();
      const elapsed = ((now - startTimeRef.current) / 1000) * speedRef.current;
      const events = eventsRef.current;

      while (
        currentIdxRef.current < events.length &&
        events[currentIdxRef.current].time <= elapsed
      ) {
        xtermRef.current?.write(events[currentIdxRef.current].data);
        currentIdxRef.current++;
      }

      const clamped = Math.min(elapsed, duration);
      setProgress(clamped);
      pauseOffsetRef.current = clamped;

      if (elapsed < duration) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        setIsPlaying(false);
        pauseOffsetRef.current = duration;
        setProgress(duration);
      }
    };

    rafRef.current = requestAnimationFrame(tick);
  }, [isPlaying, loadState, duration, doReset]);

  const pause = useCallback(() => {
    if (!isPlaying) return;
    setIsPlaying(false);
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    pauseOffsetRef.current = progress;
  }, [isPlaying, progress]);

  const handleSeek = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const target = ratio * duration;

    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    setIsPlaying(false);

    xtermRef.current?.clear();
    const events = eventsRef.current;
    let idx = 0;
    while (idx < events.length && events[idx].time <= target) {
      xtermRef.current?.write(events[idx].data);
      idx++;
    }
    currentIdxRef.current = idx;
    pauseOffsetRef.current = target;
    setProgress(target);
  }, [duration]);

  const fmtTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, '0')}`;
  };

  const pct = duration > 0 ? Math.min(100, (progress / duration) * 100) : 0;

  const [commands, setCommands] = useState<{time: number, text: string}[]>([]);
  const [commandsLoading, setCommandsLoading] = useState(false);
  const [commandsError, setCommandsError] = useState('');
  const [showCommands, setShowCommands] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setCommandsLoading(true);
    setCommandsError('');
    fetch(`/api/pam/sessions/${sessionId}/commands`, { headers: authHeaders() })
      .then(async (response) => {
        if (!response.ok) {
          if (response.status === 401) {
            throw new Error(isZh ? '登录会话已过期，无法读取命令索引。' : 'Your login session has expired; the command index cannot be loaded.');
          }
          throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
      })
      .then(data => {
        if (!cancelled) setCommands(Array.isArray(data?.commands) ? data.commands : []);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setCommands([]);
          setCommandsError(error instanceof Error ? error.message : (isZh ? '命令索引加载失败。' : 'Command index failed to load.'));
        }
      })
      .finally(() => {
        if (!cancelled) setCommandsLoading(false);
      });
    return () => { cancelled = true; };
  }, [isZh, sessionId]);

  const handleDownloadRecording = useCallback(async () => {
    try {
      const response = await fetch(`/api/pam/sessions/${sessionId}/recording`, {
        headers: authHeaders(),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${sessionId}.cast`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error: unknown) {
      alert(error instanceof Error ? error.message : (isZh ? '下载录像失败。' : 'Failed to download recording.'));
    }
  }, [isZh, sessionId]);

  const jumpTo = (time: number) => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    setIsPlaying(false);

    xtermRef.current?.clear();
    const events = eventsRef.current;
    let idx = 0;
    while (idx < events.length && events[idx].time <= time) {
      xtermRef.current?.write(events[idx].data);
      idx++;
    }
    currentIdxRef.current = idx;
    pauseOffsetRef.current = time;
    setProgress(time);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/85 backdrop-blur-sm p-4">
      <div
        ref={playerRef}
        className={`bg-slate-800 shadow-2xl border border-slate-700 w-full flex flex-col overflow-hidden transition-all duration-300 ${
          isFullscreen ? 'max-w-none h-screen rounded-none' : 'max-w-6xl rounded-2xl'
        }`}
        style={isFullscreen ? {} : { maxHeight: '90vh' }}
      >
        {/* ── Header ── */}
        <div className={`px-6 py-4 border-b border-slate-700 flex items-center justify-between bg-slate-900/60 shrink-0 ${isFullscreen ? 'py-3' : ''}`}>
          <div className="flex items-center gap-3 min-w-0">
            <div className="p-2 bg-cyan-500/20 rounded-lg shrink-0">
              <Clock className="w-5 h-5 text-cyan-400" />
            </div>
            <div className="min-w-0">
              <h3 className="text-white font-bold text-sm">
                {isZh ? '会话回溯播放' : 'Session Playback'}
              </h3>
              <div className="flex items-center gap-3 mt-0.5 flex-wrap">
                {sessionMeta?.hostname && (
                  <span className="flex items-center gap-1 text-[11px] text-slate-400">
                    <Monitor className="w-3 h-3" />
                    {sessionMeta.hostname}
                    {sessionMeta.ip && (
                      <span className="text-slate-500 font-mono ml-1">({sessionMeta.ip})</span>
                    )}
                  </span>
                )}
                {sessionMeta?.loginUser && (
                  <span className="flex items-center gap-1 text-[11px] text-slate-400">
                    <User className="w-3 h-3" />
                    {sessionMeta.loginUser}
                  </span>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={() => setShowCommands(!showCommands)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                showCommands ? 'bg-cyan-500 text-white' : 'bg-slate-700 text-slate-300 hover:text-white'
              }`}
            >
              <TerminalIcon size={14} />
              {isZh ? '命令索引' : 'Commands'}
              {commands.length > 0 && <span className="bg-white/20 px-1.5 py-0.5 rounded-md ml-1">{commands.length}</span>}
            </button>

            <button
              onClick={async () => {
                const res = await fetch(`/api/pam/sessions/${sessionId}/export`, {
                  method: 'POST',
                  headers: authHeaders(),
                });
                const data = await res.json().catch(() => ({}));
                if (res.ok && data.success) {
                  alert(isZh ? '导出任务已启动，完成后将自动下载' : 'Export started, download will begin when ready');
                } else {
                  alert(isZh ? `导出失败: ${data.error}` : `Export failed: ${data.error}`);
                }
              }}
              className="p-2 hover:bg-slate-700 rounded-lg text-slate-400 hover:text-cyan-400 transition-colors"
              title={isZh ? '导出为视频 (MP4)' : 'Export to Video (MP4)'}
            >
              <Monitor size={18} />
            </button>

            <ActionIconButton
              icon={Download}
              label={isZh ? '下载录像文件' : 'Download .cast file'}
              variant="accent"
              onClick={() => void handleDownloadRecording()}
              className="text-slate-400 hover:text-cyan-400 hover:bg-slate-700"
            />
            <button
              onClick={onClose}
              className="p-2 hover:bg-slate-700 rounded-full text-slate-400 hover:text-white transition-colors"
            >
              <X size={20} />
            </button>
          </div>
        </div>

        <div className="flex-1 flex overflow-hidden">
          {/* ── Terminal Area ── */}
          <div className="flex-1 bg-[#0f172a] relative overflow-hidden" style={{ minHeight: '320px' }}>
            <div ref={containerRef} className="absolute inset-0 p-2" />

            {loadState === 'error' && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#0f172a]/95 z-10 gap-3 px-6 text-center">
                <AlertCircle className="w-8 h-8 text-rose-400" />
                <p className="text-rose-200 text-sm font-semibold">{isZh ? '回放加载失败' : 'Playback could not be loaded'}</p>
                <p className="max-w-lg text-slate-400 text-xs break-words">{errorMsg}</p>
                <button
                  type="button"
                  onClick={() => setLoadAttempt((value) => value + 1)}
                  className="rounded-lg bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-cyan-500"
                >
                  {isZh ? '重新加载' : 'Retry'}
                </button>
              </div>
            )}

            {loadState === 'loading' && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#0f172a]/95 z-10 gap-3">
                <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
                <p className="text-slate-400 text-sm">{isZh ? '加载录像中...' : 'Loading recording...'}</p>
              </div>
            )}
          </div>

          {/* ── Command Sidebar ── */}
          {showCommands && (
            <div className="w-72 bg-slate-900/50 border-l border-slate-700 flex flex-col shrink-0">
              <div className="p-4 border-b border-slate-700 flex items-center justify-between">
                <h4 className="text-xs font-bold text-slate-300 uppercase tracking-widest">{isZh ? '会话指令流' : 'Command Stream'}</h4>
                <div className="px-2 py-0.5 bg-slate-800 text-slate-500 text-[10px] rounded font-mono">INDEX v1</div>
              </div>
              <div className="flex-1 overflow-y-auto custom-scrollbar p-2 space-y-1">
                {commandsLoading ? (
                  <div className="py-20 text-center text-slate-500 text-xs">
                    <Loader2 className="mx-auto mb-2 h-4 w-4 animate-spin text-cyan-400" />
                    {isZh ? '正在加载命令索引…' : 'Loading command index...'}
                  </div>
                ) : commandsError ? (
                  <div className="py-16 px-3 text-center text-rose-300 text-xs">
                    <AlertCircle className="mx-auto mb-2 h-4 w-4" />
                    <p>{commandsError}</p>
                  </div>
                ) : commands.length === 0 ? (
                  <div className="py-20 text-center text-slate-600 text-xs italic">
                    {isZh ? '未检测到具体指令' : 'No commands detected'}
                  </div>
                ) : (
                  commands.map((c: any, i) => {
                    const isHigh = c.risk_level === 2;
                    const isMed = c.risk_level === 1;
                    return (
                      <button
                        key={i}
                        onClick={() => jumpTo(c.time)}
                        className={`w-full text-left p-3 rounded-xl transition-all group border border-transparent hover:border-slate-700 ${
                          isHigh ? 'bg-rose-500/10 hover:bg-rose-500/20' : 
                          isMed ? 'bg-amber-500/10 hover:bg-amber-500/20' : 
                          'hover:bg-slate-800/50'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1.5">
                          <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                            isHigh ? 'text-rose-400 bg-rose-400/10' :
                            isMed ? 'text-amber-400 bg-amber-400/10' :
                            'text-cyan-500 bg-cyan-500/10'
                          }`}>
                            {fmtTime(c.time)}
                          </span>
                          <Play size={8} className={`${isHigh ? 'text-rose-400' : isMed ? 'text-amber-400' : 'text-slate-600'} opacity-0 group-hover:opacity-100`} />
                        </div>
                        <p className={`text-xs font-mono break-all line-clamp-2 ${
                          isHigh ? 'text-rose-200' : 
                          isMed ? 'text-amber-200' : 
                          'text-slate-300 group-hover:text-white'
                        }`}>
                          {c.text}
                        </p>
                      </button>
                    );
                  })
                )}
              </div>
            </div>
          )}
        </div>

        {/* ── Controls ── */}
        <div className={`px-6 py-4 bg-slate-900/70 border-t border-slate-700 shrink-0 ${isFullscreen ? 'pb-6' : ''}`}>
          <div
            className="relative w-full h-2 bg-slate-700 rounded-full overflow-visible cursor-pointer mb-4 group"
            onClick={handleSeek}
          >
            <div
              className="absolute top-0 left-0 h-full bg-cyan-500 rounded-full pointer-events-none"
              style={{ width: `${pct}%` }}
            />
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                {isPlaying ? (
                  <button onClick={pause} className="w-10 h-10 flex items-center justify-center bg-slate-700 hover:bg-slate-600 text-white rounded-full">
                    <Pause size={18} fill="currentColor" />
                  </button>
                ) : (
                  <button
                    onClick={play}
                    disabled={loadState !== 'ready'}
                    className={`w-10 h-10 flex items-center justify-center text-white rounded-full ${loadState === 'ready' ? 'bg-cyan-600 hover:bg-cyan-500' : 'cursor-not-allowed bg-slate-600 opacity-50'}`}
                    title={loadState === 'error' ? errorMsg : undefined}
                  >
                    <Play size={18} fill="currentColor" className="ml-0.5" />
                  </button>
                )}
                <button onClick={doReset} className="p-2 text-slate-400 hover:text-white rounded-lg"><RotateCcw size={18} /></button>
              </div>
              <div className="flex items-center gap-1 bg-slate-800/50 p-1 rounded-lg border border-slate-700/50">
                {SPEED_OPTIONS.map(s => (
                  <button key={s} onClick={() => setPlaybackSpeed(s)} className={`px-2 py-0.5 text-[10px] font-bold rounded ${playbackSpeed === s ? 'bg-cyan-500 text-white' : 'text-slate-400'}`}>{s}x</button>
                ))}
              </div>
              <span className="text-sm font-mono text-slate-300 select-none ml-2">{fmtTime(progress)} / {fmtTime(duration)}</span>
            </div>
            <button onClick={toggleFullscreen} className="flex items-center gap-2 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg border border-slate-700 text-xs">
              {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
              {isFullscreen ? (isZh ? '退出全屏' : 'Exit') : (isZh ? '全屏查看' : 'Fullscreen')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
