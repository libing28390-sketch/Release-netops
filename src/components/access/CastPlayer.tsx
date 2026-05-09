import React, { useEffect, useRef, useState } from 'react';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import { Play, Pause, RotateCcw, X, Clock } from 'lucide-react';
import 'xterm/css/xterm.css';

interface CastPlayerProps {
  sessionId: string;
  totalDuration: number;
  onClose: () => void;
  isZh?: boolean;
}

interface CastEvent {
  time: number;
  type: string;
  data: string;
}

export default function CastPlayer({ sessionId, totalDuration, onClose, isZh = true }: CastPlayerProps) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<Terminal | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(totalDuration || 0);
  const [loading, setLoading] = useState(true);
  
  const eventsRef = useRef<CastEvent[]>([]);
  const currentEventIdxRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const startTimeRef = useRef(0);
  const pauseOffsetRef = useRef(0);

  useEffect(() => {
    const init = async () => {
      try {
        const res = await fetch(`/api/pam/sessions/${sessionId}/recording`);
        if (!res.ok) throw new Error('Failed to fetch recording');
        const text = await res.text();
        const lines = text.trim().split('\n');
        
        // Skip header line [0]
        const header = JSON.parse(lines[0]);
        const events: CastEvent[] = [];
        let maxTime = 0;
        
        for (let i = 1; i < lines.length; i++) {
          try {
            const [time, type, data] = JSON.parse(lines[i]);
            if (type === 'o') {
              events.push({ time, type, data });
              maxTime = Math.max(maxTime, time);
            }
          } catch (e) {}
        }
        
        eventsRef.current = events;
        if (maxTime > duration) {
          setDuration(maxTime);
        }
        setLoading(false);
        
        // Initialize Terminal
        if (terminalRef.current && !xtermRef.current) {
          const term = new Terminal({
            cursorBlink: false,
            fontFamily: '"Cascadia Code", Menlo, monospace',
            fontSize: 14,
            theme: { background: '#1e293b', foreground: '#e2e8f0' },
          });
          const fitAddon = new FitAddon();
          term.loadAddon(fitAddon);
          term.open(terminalRef.current);
          fitAddon.fit();
          xtermRef.current = term;
          
          // Auto play first frame
          if (events.length > 0) term.write(events[0].data);
        }
      } catch (err) {
        console.error(err);
      }
    };
    init();
    
    return () => {
      if (timerRef.current) window.cancelAnimationFrame(timerRef.current);
      xtermRef.current?.dispose();
    };
  }, [sessionId]);

  const play = () => {
    if (isPlaying) return;
    setIsPlaying(true);
    startTimeRef.current = performance.now() - (pauseOffsetRef.current * 1000);
    
    const run = () => {
      const now = performance.now();
      const elapsed = (now - startTimeRef.current) / 1000;
      
      // Find events to render
      while (
        currentEventIdxRef.current < eventsRef.current.length && 
        eventsRef.current[currentEventIdxRef.current].time <= elapsed
      ) {
        xtermRef.current?.write(eventsRef.current[currentEventIdxRef.current].data);
        currentEventIdxRef.current++;
      }
      
      setProgress(elapsed);
      
      if (elapsed < duration) {
        timerRef.current = window.requestAnimationFrame(run);
      } else {
        setIsPlaying(false);
        pauseOffsetRef.current = duration;
      }
    };
    
    timerRef.current = window.requestAnimationFrame(run);
  };

  const pause = () => {
    if (!isPlaying) return;
    setIsPlaying(false);
    if (timerRef.current) window.cancelAnimationFrame(timerRef.current);
    pauseOffsetRef.current = progress;
  };

  const reset = () => {
    pause();
    currentEventIdxRef.current = 0;
    setProgress(0);
    pauseOffsetRef.current = 0;
    xtermRef.current?.clear();
    if (eventsRef.current.length > 0) xtermRef.current?.write(eventsRef.current[0].data);
  };

  const formatTime = (s: number) => {
    const mins = Math.floor(s / 60);
    const secs = Math.floor(s % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/80 backdrop-blur-sm p-4">
      <div className="bg-slate-800 rounded-2xl shadow-2xl border border-slate-700 w-full max-w-4xl overflow-hidden flex flex-col aspect-video">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-700 flex items-center justify-between bg-slate-900/40">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-cyan-500/20 rounded-lg">
              <Clock className="w-5 h-5 text-cyan-400" />
            </div>
            <div>
              <h3 className="text-white font-bold">{isZh ? '会话回溯播放' : 'Session Playback'}</h3>
              <p className="text-xs text-slate-400">ID: {sessionId}</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-700 rounded-full text-slate-400 transition-colors">
            <X size={20} />
          </button>
        </div>

        {/* Terminal Area */}
        <div className="flex-1 bg-slate-900 p-4 overflow-hidden relative">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-900/60 z-10">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-white"></div>
            </div>
          )}
          <div ref={terminalRef} className="w-full h-full" />
        </div>

        {/* Controls */}
        <div className="px-6 py-4 bg-slate-900/60 border-t border-slate-700">
          <div className="flex flex-col gap-4">
            {/* Progress Bar */}
            <div className="relative w-full h-1.5 bg-slate-700 rounded-full overflow-hidden group cursor-pointer">
              <div 
                className="absolute top-0 left-0 h-full bg-cyan-500 transition-all duration-100" 
                style={{ width: `${(progress / duration) * 100}%` }}
              />
            </div>
            
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                {isPlaying ? (
                  <button onClick={pause} className="w-10 h-10 flex items-center justify-center bg-slate-700 hover:bg-slate-600 text-white rounded-full transition-colors">
                    <Pause size={20} fill="currentColor" />
                  </button>
                ) : (
                  <button onClick={play} className="w-10 h-10 flex items-center justify-center bg-cyan-600 hover:bg-cyan-500 text-white rounded-full transition-colors">
                    <Play size={20} fill="currentColor" className="ml-0.5" />
                  </button>
                )}
                <button onClick={reset} className="p-2 text-slate-400 hover:text-white hover:bg-slate-700 rounded-lg transition-colors">
                  <RotateCcw size={20} />
                </button>
                <div className="text-sm font-mono text-slate-300">
                  {formatTime(progress)} / {formatTime(duration)}
                </div>
              </div>

              <div className="text-[11px] text-slate-500 font-medium uppercase tracking-wider">
                Asciinema V2 Format
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
