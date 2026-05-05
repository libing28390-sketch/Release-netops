import React, { useEffect, useRef } from 'react';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import 'xterm/css/xterm.css';

interface TerminalWindowProps {
  deviceId: string;
  role: string;
  hostname: string;
}

const API_BASE = import.meta.env.VITE_API_BASE || '';
const WS_BASE = API_BASE.replace('http', 'ws');

export default function TerminalWindow({ deviceId, role, hostname }: TerminalWindowProps) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!terminalRef.current) return;

    // 1. Initialize Xterm
    const term = new Terminal({
      cursorBlink: true,
      fontFamily: '"Cascadia Code", Menlo, monospace',
      fontSize: 13,
      theme: {
        background: '#000000',
        foreground: '#cccccc',
        cursor: '#00ff00',
      }
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(terminalRef.current);
    fitAddon.fit();
    xtermRef.current = term;

    term.writeln(`\x1b[1;36m>>> Connecting to ${hostname} (${role})...\x1b[0m`);

    // 2. Establish WebSocket
    const wsUrl = `${WS_BASE}/api/access/terminal/${deviceId}?role=${role}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      // Send initial resize
      const { cols, rows } = term;
      ws.send(JSON.stringify({ type: 'resize', cols, rows }));
    };

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === 'output') {
        term.write(msg.data);
      } else if (msg.type === 'error') {
        term.writeln(`\r\n\x1b[1;31m[ERROR] ${msg.message}\x1b[0m`);
      }
    };

    ws.onclose = () => {
      term.writeln('\r\n\x1b[1;33m[Disconnected]\x1b[0m');
    };

    // 3. Handle Input
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'input', data }));
      }
    });

    // 4. Handle Resize
    const handleResize = () => {
      fitAddon.fit();
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ 
          type: 'resize', 
          cols: term.cols, 
          rows: term.rows 
        }));
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      ws.close();
      term.dispose();
    };
  }, [deviceId, role, hostname]);

  return (
    <div className="w-full h-full bg-black">
      <div ref={terminalRef} className="w-full h-full p-2" />
    </div>
  );
}
