export type TerminalPlatform = 'windows' | 'ubuntu';

export type TerminalApp =
  | 'standard'
  | 'xshell'
  | 'putty'
  | 'securecrt'
  | 'mobaxterm';

export const WINDOWS_TERMINAL_APPS = [
  'xshell',
  'putty',
  'securecrt',
  'mobaxterm',
] as const;

export const TERMINAL_APP_LABELS: Record<TerminalApp, string> = {
  standard: 'Ubuntu / Linux terminal',
  xshell: 'Xshell',
  putty: 'PuTTY',
  securecrt: 'SecureCRT',
  mobaxterm: 'MobaXterm',
};

type BrowserNavigator = Navigator & {
  userAgentData?: {
    platform?: string;
  };
};

function readLocalStorage(key: string): string {
  if (typeof window === 'undefined') return '';

  try {
    return window.localStorage.getItem(key) || '';
  } catch {
    return '';
  }
}

function writeLocalStorage(key: string, value: string): void {
  if (typeof window === 'undefined') return;

  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Local storage may be unavailable in private or restricted browser contexts.
  }
}

/**
 * Detect the workstation running the browser. The remote device's operating
 * system must not affect which local Agent package is offered or launched.
 */
export function detectTerminalPlatform(): TerminalPlatform {
  if (typeof navigator === 'undefined') return 'windows';

  const browserNavigator = navigator as BrowserNavigator;
  const signature = [
    browserNavigator.userAgentData?.platform,
    browserNavigator.platform,
    browserNavigator.userAgent,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();

  return /windows|win32|win64|wow64/.test(signature) ? 'windows' : 'ubuntu';
}

export function getDefaultTerminalApp(platform: TerminalPlatform): TerminalApp {
  return platform === 'windows' ? 'xshell' : 'standard';
}

export interface LocalTerminalConfig {
  platform: TerminalPlatform;
  app: TerminalApp;
  path: string;
}

/**
 * Read and normalize the local terminal settings for the current browser
 * workstation. Older Windows settings using the removed System SSH option are
 * migrated to the default Windows desktop client.
 */
export function getLocalTerminalConfig(platform = detectTerminalPlatform()): LocalTerminalConfig {
  const savedApp = readLocalStorage('terminal_app');
  const isValidApp = platform === 'windows'
    ? WINDOWS_TERMINAL_APPS.includes(savedApp as (typeof WINDOWS_TERMINAL_APPS)[number])
    : savedApp === 'standard';
  const app = isValidApp ? savedApp as TerminalApp : getDefaultTerminalApp(platform);

  if (savedApp !== app) {
    writeLocalStorage('terminal_app', app);
  }

  return {
    platform,
    app,
    path: platform === 'windows' ? readLocalStorage('local_terminal_path') : '',
  };
}

/**
 * Turn a local-agent failure into a message that distinguishes transport
 * failures from errors returned after the Agent has already been reached.
 */
export function formatTerminalAgentError(error: unknown, isZh: boolean): string {
  const detail = error instanceof Error ? error.message : String(error || 'Unknown error');
  const normalized = detail.toLowerCase();

  if (/backend origin is not allowed|origin is not trusted|launch origin does not match/.test(normalized)) {
    return isZh
      ? 'Terminal Agent 已运行，但未允许当前 Nexora 页面来源。请将当前页面地址加入 NEXORA_AGENT_ALLOWED_ORIGINS 后重启 Agent。'
      : 'Terminal Agent is running, but the current Nexora page origin is not allowed. Add the page origin to NEXORA_AGENT_ALLOWED_ORIGINS and restart the Agent.';
  }

  if (
    error instanceof TypeError
    || /failed to fetch|networkerror|network request failed|load failed/.test(normalized)
  ) {
    return isZh
      ? '无法连接 Terminal Agent。请确认本机 Agent 正在运行（http://127.0.0.1:17890），并检查当前页面来源是否已获允许。'
      : 'Unable to reach the Terminal Agent. Confirm it is running at http://127.0.0.1:17890 and that the current page origin is allowed.';
  }

  if (/terminal executable not found|executable not found/.test(normalized)) {
    return isZh
      ? `Terminal Agent 已连接，但找不到本机终端程序，请检查个人设置中的程序路径：${detail}`
      : `The Terminal Agent is reachable, but the local terminal executable was not found. Check the path in Profile: ${detail}`;
  }

  if (/invalid session token|token already consumed|session token.*(expired|invalid)|session.*expired/.test(normalized)) {
    return isZh
      ? 'Terminal Agent 会话已过期，请重新发起连接。'
      : 'The Terminal Agent session expired. Start the connection again.';
  }

  if (/credential|password.*not found|device\/asset|urlopen error|connection refused|timed out|timeout|network is unreachable|name or service not known|getaddrinfo failed/.test(normalized)) {
    return isZh
      ? 'Terminal Agent 或后端会话连接失败，请确认 Agent 正在运行并重新发起连接。'
      : 'The Terminal Agent or backend session failed. Confirm the Agent is running and start the connection again.';
  }

  return isZh
    ? 'Terminal Agent 会话启动失败，请确认 Agent 正在运行后重试。'
    : 'Terminal Agent session failed to start. Confirm the Agent is running and try again.';
}
