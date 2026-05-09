import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import { Play, Pause, RotateCcw, X, Clock, User, Monitor, Download, AlertCircle, Loader2 } from 'lucide-react';
import 'xterm/css/xterm.css';

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

export default function CastPlayer({
  sessionId,
  totalDuration,
  sessionMeta,
  onClose,
  isZh = true,
}: CastPlayerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const xtermRef     = useRef<Terminal | null>(null);
  const fitAddonRef  = useRef<FitAddon | null>(null);

  const [isPlaying, setIsPlaying]   = useState(false);
  const [progress, setProgress]     = useState(0);
  const [duration, setDuration]     = useState(Math.max(totalDuration || 0, 1));
  const [loadState, setLoadState]   = useState<'loading' | 'ready' | 'error'>('loading');
  const [errorMsg, setErrorMsg]     = useState('');

  const eventsRef      = useRef<CastEvent[]>([]);
  const currentIdxRef  = useRef(0);
  const rafRef         = useRef<number | null>(null);
  const startTimeRef   = useRef(0);
  const pauseOffsetRef = useRef(0);

  // ── Step 1: init xterm after mount ──────────────────────────────────
  useEffect(() => {
    const node = containerRef.current;
    if (!node || xtermRef.current) return;

    const term = new Terminal({
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
        const res = await fetch(`/api/pam/sessions/${sessionId}/recording`);
        if (!res.ok) {
          const body = await res.text().catch(() => '');
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
        const effectiveDuration = Math.max(totalDuration || 0, maxTime, 0.5);
        setDuration(effectiveDuration);
        setLoadState('ready');

        // Write first frame — wait until xterm is initialised
        const writeFirst = () => {
          if (xtermRef.current) {
            xtermRef.current.write(events[0].data);
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
  }, [sessionId, totalDuration]);

  // ── Playback controls ────────────────────────────────────────────────
  const doReset = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    setIsPlaying(false);
    currentIdxRef.current = 0;
    pauseOffsetRef.current = 0;
    setProgress(0);
    xtermRef.current?.clear();
    const events = eventsRef.current;
    if (events.length > 0) xtermRef.current?.write(events[0].data);
  }, []);

  const play = useCallback(() => {
    if (isPlaying || loadState !== 'ready') return;
    if (pauseOffsetRef.current >= duration) {
      doReset();
      return;
    }
    setIsPlaying(true);
    startTimeRef.current = performance.now() - pauseOffsetRef.current * 1000;

    const tick = () => {
      const elapsed = (performance.now() - startTimeRef.current) / 1000;
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/85 backdrop-blur-sm p-4">
      <div
        className="bg-slate-800 rounded-2xl shadow-2xl border border-slate-700 w-full max-w-5xl flex flex-col overflow-hidden"
        style={{ maxHeight: '90vh' }}
      >
        {/* ── Header ── */}
        <div className="px-6 py-4 border-b border-slate-700 flex items-center justify-between bg-slate-900/60 shrink-0">
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
                {sessionMeta?.requester && (
                  <span className="text-[11px] text-slate-500">
                    {isZh ? '操作人' : 'By'}: {sessionMeta.requester}
                  </span>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={() => window.open(`/api/pam/sessions/${sessionId}/recording`, '_blank')}
              className="p-2 hover:bg-slate-700 rounded-lg text-slate-400 hover:text-cyan-400 transition-colors"
              title={isZh ? '下载录像文件' : 'Download .cast file'}
            >
              <Download size={18} />
            </button>
            <button
              onClick={onClose}
              className="p-2 hover:bg-slate-700 rounded-full text-slate-400 hover:text-white transition-colors"
            >
              <X size={20} />
            </button>
          </div>
        </div>

        {/* ── Terminal Area ── */}
        <div className="flex-1 bg-[#0f172a] relative overflow-hidden" style={{ minHeight: '320px' }}>
          {/* xterm mount point — always in DOM so useEffect can open it */}
          <div ref={containerRef} className="absolute inset-0 p-2" />

          {/* Loading overlay */}
          {loadState === 'loading' && (
            <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#0f172a]/95 z-10 gap-3">
              <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
              <p className="text-slate-400 text-sm">{isZh ? '加载录像中...' : 'Loading recording...'}</p>
            </div>
          )}

          {/* Error overlay */}
          {loadState === 'error' && (
            <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#0f172a]/95 z-10 gap-3 px-8">
              <AlertCircle className="w-10 h-10 text-rose-400" />
              <p className="text-rose-400 text-sm font-medium text-center">
                {isZh ? '录像加载失败' : 'Failed to load recording'}
              </p>
              <p className="text-slate-500 text-xs font-mono text-center break-all">{errorMsg}</p>
            </div>
          )}
        </div>

        {/* ── Controls ── */}
        <div className="px-6 py-4 bg-slate-900/70 border-t border-slate-700 shrink-0">
          {/* Seekable progress bar */}
          <div
            className="relative w-full h-2 bg-slate-700 rounded-full overflow-visible cursor-pointer mb-4 group"
            onClick={handleSeek}
          >
            <div
              className="absolute top-0 left-0 h-full bg-cyan-500 rounded-full pointer-events-none"
              style={{ width: `${pct}%` }}
            />
            <div
              className="absolute top-1/2 -translate-y-1/2 w-3.5 h-3.5 bg-white rounded-full shadow-lg pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity"
              style={{ left: `calc(${pct}% - 7px)` }}
            />
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {isPlaying ? (
                <button
                  onClick={pause}
                  className="w-10 h-10 flex items-center justify-center bg-slate-700 hover:bg-slate-600 text-white rounded-full transition-colors"
                >
                  <Pause size={18} fill="currentColor" />
                </button>
              ) : (
                <button
                  onClick={play}
                  disabled={loadState !== 'ready'}
                  className="w-10 h-10 flex items-center justify-center bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-700 disabled:text-slate-500 text-white rounded-full transition-colors"
                >
                  <Play size={18} fill="currentColor" className="ml-0.5" />
                </button>
              )}

              <button
                onClick={doReset}
                disabled={loadState !== 'ready'}
                className="p-2 text-slate-400 hover:text-white hover:bg-slate-700 disabled:opacity-30 rounded-lg transition-colors"
                title={isZh ? '重置' : 'Reset'}
              >
                <RotateCcw size={18} />
              </button>

              <span className="text-sm font-mono text-slate-300 tabular-nums select-none">
                {fmtTime(progress)} / {fmtTime(duration)}
              </span>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-[10px] text-slate-500 font-medium uppercase tracking-wider">
                Asciinema v2
              </span>
              <span className="text-[10px] text-slate-600">·</span>
              <span className="text-[10px] text-slate-500 font-mono">
                {sessionId.slice(0, 20)}…
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
