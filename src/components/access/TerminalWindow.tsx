import React, { useEffect, useRef } from 'react';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import 'xterm/css/xterm.css';

interface TerminalWindowProps {
  sessionToken: string;
  hostname: string;
  language?: string;
}

const API_BASE = import.meta.env.VITE_API_BASE || '';
const WS_BASE = API_BASE
  ? API_BASE.replace('http', 'ws')
  : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`;

// Translate server-side error messages and WebSocket close reasons into
// human-friendly guidance. Returns { title, detail, hint? } for rendering.
function humanizeError(raw: string, isZh: boolean): { title: string; detail?: string; hint?: string } {
  const s = String(raw || '').toLowerCase();
  if (!s) {
    return isZh ? { title: '连接出错' } : { title: 'Connection error' };
  }
  if (s.includes('invalid') && s.includes('token')) {
    if (isZh) {
      return {
        title: '\u4f1a\u8bdd\u4ee4\u724c\u65e0\u6548\u6216\u5df2\u8fc7\u671f',
        detail: '\u4ee4\u724c\u4ec5\u4e00\u6b21\u6027\u6709\u6548\uff08\u9ed8\u8ba4 20 \u5206\u949f\uff09\uff0c\u6216\u8fde\u63a5\u5df2\u5728\u5176\u4ed6\u9875\u9762\u6253\u5f00\u3002',
        hint: '\u8bf7\u56de\u5230\u8bbe\u5907\u5217\u8868\u91cd\u65b0\u7533\u8bf7\u4e00\u4e2a\u65b0\u4f1a\u8bdd\u518d\u8bd5\u3002',
      };
    }
    return isZh
      ? {
          title: '会话令牌无效或已过期',
          detail: '令牌仅一次性有效（默认 5 分钟），或连接已在其他页面打开。',
          hint: '请回到设备列表重新申请一个新会话再试。',
        }
      : {
          title: 'Session token is invalid or expired',
          detail: 'Session tokens are single-use and expire after 20 minutes, or the session is already open in another tab.',
          hint: 'Please return to the device list and request a new session.',
        };
  }
  if (s.includes('superseded')) {
    return isZh
      ? {
          title: '该会话已在另一处接管',
          detail: '同一个令牌被另一个连接使用，当前窗口已被自动关闭以保障审计合规。',
          hint: '如需继续操作，请申请一个新会话。',
        }
      : {
          title: 'This session was taken over elsewhere',
          detail: 'The same token was consumed by another connection; this window was closed for audit integrity.',
          hint: 'Request a new session to continue.',
        };
  }
  if (s.includes('idle_timeout') || s.includes('idle timeout')) {
    return isZh
      ? {
          title: '会话已因超过空闲时长被自动断开',
          detail: '连续 5 分钟没有键盘输入，系统已按策略自动结束该会话。',
          hint: '如需继续，请重新申请一个新会话。',
        }
      : {
          title: 'Session auto-disconnected due to idle timeout',
          detail: 'No keyboard input for 5 minutes; the session was ended by policy.',
          hint: 'Request a new session to continue.',
        };
  }
  if (s.includes('admin_kill') || s.includes('terminated by administrator')) {
    return isZh
      ? {
          title: '会话已被管理员强制断开',
          detail: '管理员在受控审计页面手动终止了该会话。',
        }
      : {
          title: 'Session was force-terminated by an administrator',
          detail: 'An administrator ended this session from the PAM audit page.',
        };
  }
  if (s.includes('missing_credentials') || s.includes('missing ssh credentials')) {
    return isZh
      ? {
          title: '凭据缺失',
          detail: '无法找到该设备的登录账号或密码。',
          hint: '请联系管理员在 PAM 凭据库中补齐账号信息。',
        }
      : {
          title: 'Credentials missing',
          detail: 'No login account or password is configured for this device.',
          hint: 'Ask an administrator to populate the PAM credential vault.',
        };
  }
  if (s.includes('ssh_authentication_failed') || s.includes('all authentication methods failed')) {
    return isZh
      ? {
          title: 'SSH 账号认证失败',
          detail: raw,
          hint: '当前 Web 会话使用的是资产配置的账号，请核对用户名、密码及设备 AAA/VTY 策略。',
        }
      : {
          title: 'SSH account authentication failed',
          detail: raw,
          hint: 'The Web session uses the asset-configured account. Verify its username, password, and AAA/VTY policy.',
        };
  }
  if (s.includes('ssh_error') || s.includes('ssh connection failed') || s.includes('authentication failed')) {
    return isZh
      ? {
          title: 'SSH 连接失败',
          detail: raw,
          hint: '请确认设备在线、账号密码正确，并检查目标端口（默认 22）是否可达。',
        }
      : {
          title: 'SSH connection failed',
          detail: raw,
          hint: 'Verify the device is online, credentials are correct, and port 22 is reachable.',
        };
  }
  return { title: raw };
}

// Human-friendly mapping for WebSocket close codes.
function explainClose(code: number, reason: string, isZh: boolean): { title: string; detail?: string } {
  const reasonLower = reason.toLowerCase();
  if (reasonLower.includes('superseded')) {
    return humanizeError('superseded', isZh);
  }
  if (code === 1000) {
    return isZh
      ? { title: '会话已正常结束', detail: reason || undefined }
      : { title: 'Session ended normally', detail: reason || undefined };
  }
  if (code === 1008) {
    return humanizeError(reason || 'invalid token', isZh);
  }
  if (code === 1011) {
    return humanizeError(reason || 'ssh_error', isZh);
  }
  if (code === 1006) {
    return isZh
      ? { title: '与网关失去连接', detail: '浏览器、代理或后端进程可能已异常关闭。' }
      : { title: 'Lost connection to the gateway', detail: 'The browser, proxy, or backend process may have closed unexpectedly.' };
  }
  return isZh
    ? { title: `会话已关闭 (代码 ${code})`, detail: reason || undefined }
    : { title: `Session closed (code ${code})`, detail: reason || undefined };
}

export default function TerminalWindow({ sessionToken, hostname, language }: TerminalWindowProps) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const isZh = (language || 'zh') === 'zh';

  useEffect(() => {
    if (!terminalRef.current) return;

    // 1. Initialize Xterm
    const term = new Terminal({
      cursorBlink: true,
      // Match the AWS/VM terminal style used by the asset access console.
      fontFamily: 'JetBrains Mono, Menlo, Monaco, Consolas, "Courier New", monospace',
      fontSize: 15,
      lineHeight: 1.25,
      letterSpacing: 0.15,
      fontWeight: 400,
      fontWeightBold: 600,
      scrollback: 5000,
      theme: {
        background: '#050505',
        foreground: '#e5e7eb',
        cursor: '#22d3ee',
        cursorAccent: '#050505',
        selectionBackground: 'rgba(34, 211, 238, 0.28)',
        black: '#111827',
        brightBlack: '#4b5563',
        white: '#e5e7eb',
        brightWhite: '#ffffff',
      },
      rightClickSelectsWord: true,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(terminalRef.current);
    fitAddon.fit();
    term.focus();

    const sendInput = (data: string) => {
      const socket = wsRef.current;
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      socket.send(JSON.stringify({ type: 'input', data }));
    };

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
      if (text) sendInput(text);
    };

    term.writeln(`\x1b[1;36m>>> ${isZh ? '正在连接' : 'Connecting to'} ${hostname}...\x1b[0m`);

    // Render a multi-line error card into the xterm terminal using ANSI colors.
    const writeErrorCard = (kind: 'error' | 'warning' | 'info', title: string, detail?: string, hint?: string) => {
      const color = kind === 'error' ? '\x1b[1;31m' : kind === 'warning' ? '\x1b[1;33m' : '\x1b[1;36m';
      const icon = kind === 'error' ? '✗' : kind === 'warning' ? '⚠' : 'ℹ';
      term.writeln('');
      term.writeln(`${color}${'─'.repeat(60)}\x1b[0m`);
      term.writeln(`${color}${icon} ${title}\x1b[0m`);
      if (detail) {
        term.writeln(`\x1b[37m  ${detail}\x1b[0m`);
      }
      if (hint) {
        term.writeln(`\x1b[36m  ${isZh ? '建议' : 'Hint'}: ${hint}\x1b[0m`);
      }
      term.writeln(`${color}${'─'.repeat(60)}\x1b[0m`);
    };

    // 2. Establish WebSocket
    const wsUrl = `${WS_BASE}/api/pam/ws/${sessionToken}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;
    let closeCardRendered = false;

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
        } else if (msg.type === 'notice') {
          // Backend emits human-readable terminal notices (e.g. idle warning, timeout).
          // The message is already ANSI-colored; just forward it.
          if (msg.message) term.write(msg.message);
        } else if (msg.type === 'error') {
          const h = humanizeError(msg.message || '', isZh);
          if (!closeCardRendered) {
            closeCardRendered = true;
            writeErrorCard('error', h.title, h.detail, h.hint);
          }
        }
      } catch (err) {
        console.error('Failed to parse WS message', err);
      }
    };

    ws.onerror = (err) => {
      if (closeCardRendered) return;
      writeErrorCard(
        'error',
        isZh ? '无法连接到受控网关' : 'Unable to reach the controlled gateway',
        isZh ? '请检查网络连接或代理配置，然后重试。' : 'Check your network connection or proxy settings, then retry.'
      );
      closeCardRendered = true;
      console.error('WS Error:', err);
    };

    ws.onclose = (event) => {
      if (event.code === 1000 || closeCardRendered) return;
      closeCardRendered = true;
      const h = explainClose(event.code, event.reason || '', isZh);
      // Friendly-close codes render as info/warning; 1011/1008 stay as error.
      const kind = event.code === 1000 ? 'info' : (event.code === 1008 || event.code === 1011 || event.code === 1006) ? 'error' : 'warning';
      writeErrorCard(kind, h.title, h.detail);
    };

    // 3. Handle Input
    term.onData((data) => {
      sendInput(data);
    });

    // 4. Handle Keyboard Shortcuts (Paste)
    term.attachCustomKeyEventHandler((e) => {
      // Ctrl+V or Shift+Insert
      if ((e.ctrlKey && e.key === 'v') || (e.shiftKey && e.key === 'Insert')) {
        if (e.type === 'keydown') {
            navigator.clipboard.readText().then(text => {
            if (text) sendInput(text);
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
    <div className="netops-terminal-shell w-full h-full bg-[#050505]">
      <div ref={terminalRef} className="w-full h-full px-4 py-3" />
    </div>
  );
}
