import { useState, useEffect, useCallback } from 'react';
import type { SessionUser } from '../types';
import { resetSystemInfoCache } from './useSystem';
import { resetInventoryDeviceCache } from './useInventory';

const SESSION_SNAPSHOT_KEY = 'netops_session_snapshot';

const readSessionSnapshot = (): SessionUser | null => {
  try {
    if (typeof sessionStorage === 'undefined' || typeof localStorage === 'undefined') return null;
    if (!localStorage.getItem('netops_token')) return null;
    const raw = sessionStorage.getItem(SESSION_SNAPSHOT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object' && typeof parsed.username === 'string' && parsed.username.trim()) {
      return parsed as SessionUser;
    }
  } catch {
    // ignore malformed sessionStorage
  }
  return null;
};

const writeSessionSnapshot = (user: SessionUser | null | undefined) => {
  try {
    if (typeof sessionStorage === 'undefined') return;
    if (!user?.username) {
      sessionStorage.removeItem(SESSION_SNAPSHOT_KEY);
      return;
    }
    sessionStorage.setItem(SESSION_SNAPSHOT_KEY, JSON.stringify({
      id: user.id,
      username: user.username,
      role: user.role,
      role_profile: user.role_profile,
      display_name: user.display_name,
      avatar_url: user.avatar_url,
      preferred_language: user.preferred_language,
    }));
  } catch {
    // ignore storage quota errors
  }
};

interface UseAuthProps {
  language: string;
  setLanguage: (lang: 'en' | 'zh') => void;
  showToast: (msg: string, type?: 'success' | 'error' | 'info') => void;
  setShowSetupWizard: (val: boolean) => void;
  setShowUserMenu: (val: boolean) => void;
  setShowNotifications: (val: boolean) => void;
}

export const useAuth = ({
  language,
  setLanguage,
  showToast,
  setShowSetupWizard,
  setShowUserMenu,
  setShowNotifications,
}: UseAuthProps) => {
  const expireLocalSession = useCallback(() => {
    localStorage.removeItem('netops_token');
    writeSessionSnapshot(null);
    resetSystemInfoCache();
    resetInventoryDeviceCache();
    setShowUserMenu(false);
    setShowNotifications(false);
    setIsAuthenticated(false);
    setAuthChecking(false);
  }, [setShowUserMenu, setShowNotifications]);

  const fetchWithTimeout = useCallback(async (url: string, options: RequestInit = {}, timeoutMs = 12000) => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, { ...options, signal: controller.signal });
    } finally {
      window.clearTimeout(timer);
    }
  }, []);

  const checkSetupStatusInBackground = useCallback((
    token: string,
    role: string | undefined,
    isCurrent: () => boolean = () => true,
  ) => {
    void fetchWithTimeout(
      '/api/setup/status',
      { headers: { Authorization: `Bearer ${token}` } },
      8000,
    ).then(async (response) => {
      if (!response.ok || !isCurrent()) return;
      const data = await response.json();
      if (isCurrent() && !data.setup_completed && role === 'Administrator') {
        setShowSetupWizard(true);
      }
    }).catch(() => {
      // Setup status must not delay an otherwise valid session.
    });
  }, [fetchWithTimeout, setShowSetupWizard]);

  const initialSnapshot = readSessionSnapshot();
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(() => Boolean(initialSnapshot));
  const [authChecking, setAuthChecking] = useState<boolean>(() => !initialSnapshot && Boolean(typeof localStorage !== 'undefined' && localStorage.getItem('netops_token')));
  const [currentUser, setCurrentUser] = useState<SessionUser>(() => initialSnapshot || { username: 'admin' });
  const [isAuthenticating, setIsAuthenticating] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [rememberMe, setRememberMe] = useState(() => localStorage.getItem('netops_remember') === 'true');
  const [showLoginPwd, setShowLoginPwd] = useState(false);
  const [mfaRequired, setMfaRequired] = useState(false);
  const [tempMfaToken, setTempMfaToken] = useState('');
  const [captchaRequired, setCaptchaRequired] = useState(false);
  const [captchaId, setCaptchaId] = useState('');
  const [captchaImage, setCaptchaImage] = useState('');
  const [captchaCode, setCaptchaCode] = useState('');
  const [loadingCaptcha, setLoadingCaptcha] = useState(false);

  const refreshCaptcha = useCallback(async () => {
    setLoadingCaptcha(true);
    try {
      const resp = await fetch('/api/captcha/generate');
      if (resp.ok) {
        const data = await resp.json();
        if (data.captcha_id && data.image) {
          setCaptchaId(data.captcha_id);
          setCaptchaImage(data.image);
          setCaptchaCode('');
        }
      }
    } catch {
      // ignore network errors
    } finally {
      setLoadingCaptcha(false);
    }
  }, []);

  const [loginForm, setLoginForm] = useState(() => {
    const saved = localStorage.getItem('netops_user');
    return { username: saved || '', password: '' };
  });

  useEffect(() => {
    const retryDelays = [1000, 2000, 3000, 5000, 8000];
    const pollInterval = 60000;
    let active = true;
    let timer: number | undefined;
    let retryIndex = 0;
    let checkedToken: string | null = null;
    let verifiedToken: string | null = null;

    async function validateSession() {
      const token = localStorage.getItem('netops_token');
      if (token !== checkedToken) {
        checkedToken = token;
        retryIndex = 0;
      }
      if (!token) {
        setAuthChecking(false);
        return pollInterval;
      }

      const isCurrent = () => active && localStorage.getItem('netops_token') === token;
      try {
        const response = await fetchWithTimeout('/api/session', {
          headers: { Authorization: `Bearer ${token}` },
        }, verifiedToken === token ? 6000 : 10000);
        if (!isCurrent()) return pollInterval;
        if (response.status === 401) {
          expireLocalSession();
          return pollInterval;
        }
        if (response.ok) {
          const { user } = await response.json() as { user?: SessionUser };
          if (!isCurrent()) return pollInterval;
          if (typeof user?.username === 'string' && user.username.trim()) {
            const firstVerification = verifiedToken !== token;
            verifiedToken = token;
            retryIndex = 0;
            setCurrentUser(user);
            writeSessionSnapshot(user);
            setIsAuthenticated(true);
            setAuthChecking(false);
            if (firstVerification) {
              if (user.preferred_language === 'en' || user.preferred_language === 'zh') {
                setLanguage(user.preferred_language);
              }
              void fetchWithTimeout('/api/grafana/session', {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}` },
                credentials: 'same-origin',
              }, 5000).catch(() => {});
              checkSetupStatusInBackground(token, user.role, isCurrent);
            }
            return pollInterval;
          }
        }
      } catch {
        // Retain the token and any confirmed snapshot during temporary outages.
      }
      return isCurrent() && verifiedToken !== token
        ? retryDelays[retryIndex++] ?? pollInterval
        : pollInterval;
    }

    async function checkAndSchedule() {
      const delay = await validateSession();
      if (active) timer = window.setTimeout(checkAndSchedule, delay);
    }

    window.addEventListener('netops:auth-expired', expireLocalSession);
    void checkAndSchedule();
    return () => {
      active = false;
      window.clearTimeout(timer);
      window.removeEventListener('netops:auth-expired', expireLocalSession);
    };
  }, [checkSetupStatusInBackground, expireLocalSession, fetchWithTimeout, setLanguage]);

  const handleLogout = useCallback(() => {
    const token = localStorage.getItem('netops_token');
    if (token) {
      // Revoke the backend session and clear the Grafana-scoped HttpOnly cookie.
      // Keep the normal UI logout immediate even if the network is unavailable.
      void fetchWithTimeout(
        '/api/logout',
        {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          credentials: 'same-origin',
          keepalive: true,
        },
        4000
      ).catch(() => {});
    }
    expireLocalSession();
  }, [expireLocalSession, fetchWithTimeout]);

  const handleLogin = async () => {
    if (!loginForm.username.trim() || !loginForm.password.trim()) {
      setLoginError(language === 'zh' ? '请输入用户名和密码' : 'Enter username and password');
      return;
    }

    if (captchaRequired && !captchaCode.trim()) {
      setLoginError(language === 'zh' ? '请输入图形验证码' : 'Please enter security captcha');
      return;
    }

    setIsAuthenticating(true);
    setLoginError(null);

    try {
      const payload: Record<string, any> = {
        username: loginForm.username.trim(),
        password: loginForm.password,
      };
      if (captchaRequired && captchaId) {
        payload.captcha_id = captchaId;
        payload.captcha_code = captchaCode.trim();
      }

      const response = await fetchWithTimeout(
        '/api/login',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
        12000
      );
      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        let msg = data.detail || (language === 'zh' ? '登录失败，请检查用户名和密码' : 'Login failed');
        if (typeof msg === 'string') {
          if (msg.includes('Invalid credentials') && !msg.includes('连续失败')) {
            msg = language === 'zh' ? '用户名或密码错误，请重新输入' : 'Invalid username or password';
          } else if (msg.includes('Account locked') && !msg.includes('已被锁定')) {
            msg = language === 'zh' ? '密码错误次数过多，账号已被锁定，请稍后再试或联系系统管理员' : msg;
          }
        }
        setLoginError(msg);

        const shouldRequireCaptcha =
          response.headers.get('X-Captcha-Required') === 'true' ||
          Boolean(data.captcha_required) ||
          (typeof msg === 'string' && (msg.includes('验证码') || msg.includes('3 次') || msg.includes('3次')));

        if (shouldRequireCaptcha) {
          setCaptchaRequired(true);
          refreshCaptcha();
        }
        return;
      }

      if (data.mfa_required) {
        setMfaRequired(true);
        setTempMfaToken(data.temp_token);
        return;
      }

      localStorage.setItem('netops_token', data.token);
      if (rememberMe) {
        localStorage.setItem('netops_user', data.user?.username || loginForm.username.trim());
        localStorage.setItem('netops_remember', 'true');
      } else {
        localStorage.removeItem('netops_user');
        localStorage.setItem('netops_remember', 'false');
      }

      const loggedInUser = data.user || { username: loginForm.username.trim() };
      setCurrentUser(loggedInUser);
      writeSessionSnapshot(loggedInUser);
      setIsAuthenticated(true);
      setLoginForm((prev) => ({ ...prev, password: '' }));
      setCaptchaRequired(false);
      setCaptchaId('');
      setCaptchaImage('');
      setCaptchaCode('');
      showToast(language === 'zh' ? '登录成功' : 'Login successful', 'success');

      checkSetupStatusInBackground(
        data.token,
        data.user?.role,
        () => localStorage.getItem('netops_token') === data.token,
      );
    } catch (error: any) {
      if (error?.name === 'AbortError') {
        setLoginError(language === 'zh' ? '登录超时，请检查后端状态后重试' : 'Login timed out. Please verify backend status and retry');
      } else {
        setLoginError(language === 'zh' ? '连接失败，请稍后重试' : 'Connection failed, please try again later');
      }
    } finally {
      setIsAuthenticating(false);
    }
  };

  const handleMfaVerify = async (code: string) => {
    if (!code.trim()) {
      setLoginError(language === 'zh' ? '请输入动态验证码' : 'Enter verification code');
      return;
    }

    setIsAuthenticating(true);
    setLoginError(null);

    try {
      const response = await fetchWithTimeout(
        '/api/mfa/verify',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            temp_token: tempMfaToken,
            code: code.trim(),
          }),
        },
        12000
      );
      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        setLoginError(data.detail || (language === 'zh' ? '验证失败' : 'Verification failed'));
        return;
      }

      localStorage.setItem('netops_token', data.token);
      if (rememberMe) {
        localStorage.setItem('netops_user', data.user?.username || loginForm.username.trim());
        localStorage.setItem('netops_remember', 'true');
      } else {
        localStorage.removeItem('netops_user');
        localStorage.setItem('netops_remember', 'false');
      }

      const mfaUser = data.user || { username: loginForm.username.trim() };
      setCurrentUser(mfaUser);
      writeSessionSnapshot(mfaUser);
      setIsAuthenticated(true);
      setLoginForm((prev) => ({ ...prev, password: '' }));
      setMfaRequired(false);
      setTempMfaToken('');
      showToast(language === 'zh' ? '登录成功' : 'Login successful', 'success');

      checkSetupStatusInBackground(
        data.token,
        data.user?.role,
        () => localStorage.getItem('netops_token') === data.token,
      );
    } catch (error: any) {
      if (error?.name === 'AbortError') {
        setLoginError(language === 'zh' ? '验证超时，请重试' : 'Verification timed out. Please retry');
      } else {
        setLoginError(language === 'zh' ? '连接失败，请稍后重试' : 'Connection failed, please try again later');
      }
    } finally {
      setIsAuthenticating(false);
    }
  };

  const handleLanguagePreferenceChange = useCallback((nextLanguage: 'en' | 'zh') => {
    setLanguage(nextLanguage as never);
    if (currentUser.id) {
      const token = localStorage.getItem('netops_token');
      fetch(`/api/users/${currentUser.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ preferred_language: nextLanguage }),
      }).catch(() => {});
    }
  }, [currentUser.id, setLanguage]);

  const handleSwitchUser = async (targetUsername: string) => {
    const token = localStorage.getItem('netops_token');
    if (!token) return;

    try {
      const resp = await fetch('/api/switch-user', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ username: targetUsername }),
      });

      const data = await resp.json();
      if (resp.ok && data.token) {
        localStorage.setItem('netops_token', data.token);
        writeSessionSnapshot(data.user);
        resetSystemInfoCache();
        resetInventoryDeviceCache();
        setCurrentUser(data.user);
        showToast(language === 'zh' ? `已切换到用户: ${targetUsername}` : `Switched to user: ${targetUsername}`, 'success');
        window.location.reload();
      } else {
        showToast(data.detail || 'Switch failed', 'error');
      }
    } catch {
      showToast('Network error during switch', 'error');
    }
  };

  return {
    isAuthenticated,
    setIsAuthenticated,
    authChecking,
    currentUser,
    setCurrentUser,
    isAuthenticating,
    loginError,
    setLoginError,
    loginForm,
    setLoginForm,
    rememberMe,
    setRememberMe,
    handleLogin,
    handleLogout,
    handleLanguagePreferenceChange,
    handleSwitchUser,
    showLoginPwd,
    setShowLoginPwd,
    mfaRequired,
    setMfaRequired,
    handleMfaVerify,
    captchaRequired,
    setCaptchaRequired,
    captchaImage,
    captchaCode,
    setCaptchaCode,
    loadingCaptcha,
    refreshCaptcha,
  };
};
