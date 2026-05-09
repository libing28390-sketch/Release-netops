import React, { useEffect, useRef } from 'react';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import 'xterm/css/xterm.css';

interface TerminalWindowProps {
  sessionToken: string;
  hostname: string;
}

const API_BASE = import.meta.env.VITE_API_BASE || '';
const WS_BASE = API_BASE.replace('http', 'ws');

export default function TerminalWindow({ sessionToken, hostname }: TerminalWindowProps) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!terminalRef.current) return;

    // 1. Initialize Xterm
    const term = new Terminal({
      cursorBlink: true,
      fontFamily: '"Cascadia Code", Menlo, monospace',
      fontSize: 14,
      theme: {
        background: '#000000',
        foreground: '#cccccc',
        cursor: '#00ff00',
      },
      rightClickSelectsWord: true,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(terminalRef.current);
    fitAddon.fit();
    term.focus();
    xtermRef.current = term;

    // Putty-style: Copy on select (Works fine on HTTP)
    term.onSelectionChange(() => {
      if (term.hasSelection()) {
        const text = term.getSelection();
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).catch(() => {});
        } else {
          try {
            const textArea = document.createElement("textarea");
            textArea.value = text;
            document.body.appendChild(textArea);
            textArea.select();
            document.execCommand("copy");
            document.body.removeChild(textArea);
          } catch (err) {}
        }
      }
    });

    // Native Paste Helper: Focus the hidden textarea on right-click 
    // to ensure "Paste" appears in the browser's native context menu.
    terminalRef.current.onmousedown = (e) => {
      if (e.button === 2) { // Right click
        const textarea = terminalRef.current?.querySelector('textarea');
        if (textarea) {
          textarea.focus();
        }
      }
    };

    // Global Paste Interceptor (Captures native paste commands)
    terminalRef.current.onpaste = (e) => {
      e.preventDefault();
      const text = e.clipboardData?.getData('text');
      if (text && wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'input', data: text }));
      }
    };

    term.writeln(`\x1b[1;36m>>> Connecting to ${hostname}...\x1b[0m`);

    // 2. Establish WebSocket
    const wsUrl = `${WS_BASE}/api/pam/ws/${sessionToken}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      // Send initial resize
      const { cols, rows } = term;
      ws.send(JSON.stringify({ type: 'resize', cols, rows }));
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'output') {
          term.write(msg.data);
        } else if (msg.type === 'error') {
          term.writeln(`\r\n\x1b[1;31m[ERROR] ${msg.message}\x1b[0m`);
        }
      } catch (err) {
        console.error('Failed to parse WS message', err);
      }
    };

    ws.onerror = (err) => {
      term.writeln(`\r\n\x1b[1;31m[WebSocket Error] Failed to connect to gateway.\x1b[0m`);
      console.error('WS Error:', err);
    };

    ws.onclose = (event) => {
      const reason = event.reason ? `: ${event.reason}` : '';
      term.writeln(`\r\n\x1b[1;33m[Disconnected] Session closed${reason} (Code: ${event.code})\x1b[0m`);
    };

    // 3. Handle Input
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'input', data }));
      }
    });

    // 4. Handle Keyboard Shortcuts (Paste)
    term.attachCustomKeyEventHandler((e) => {
      // Ctrl+V or Shift+Insert
      if ((e.ctrlKey && e.key === 'v') || (e.shiftKey && e.key === 'Insert')) {
        if (e.type === 'keydown') {
          navigator.clipboard.readText().then(text => {
            if (text && wsRef.current?.readyState === WebSocket.OPEN) {
              wsRef.current.send(JSON.stringify({ type: 'input', data: text }));
            }
          }).catch(() => {
            // If API blocked, let the browser handle it naturally or ignore
          });
        }
        return false; // Prevent default
      }
      return true;
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
  }, [sessionToken, hostname]);

  return (
    <div className="w-full h-full bg-black">
      <div ref={terminalRef} className="w-full h-full p-2" />
    </div>
  );
}
