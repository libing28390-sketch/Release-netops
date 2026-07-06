import { useState, useEffect, useCallback } from 'react';
import type { SessionUser } from '../types';

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
  const fetchWithTimeout = useCallback(async (url: string, options: RequestInit = {}, timeoutMs = 12000) => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, { ...options, signal: controller.signal });
    } finally {
      window.clearTimeout(timer);
    }
  }, []);

  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [authChecking, setAuthChecking] = useState(true);
  const [currentUser, setCurrentUser] = useState<SessionUser>({ username: 'admin' });
  const [isAuthenticating, setIsAuthenticating] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [rememberMe, setRememberMe] = useState(() => localStorage.getItem('netops_remember') === 'true');
  const [showLoginPwd, setShowLoginPwd] = useState(false);

  const [loginForm, setLoginForm] = useState(() => {
    const saved = localStorage.getItem('netops_user');
    return { username: saved || '', password: '' };
  });

  useEffect(() => {
    const token = localStorage.getItem('netops_token');
    if (!token) {
      setAuthChecking(false);
      return;
    }

    fetchWithTimeout('/api/session', { headers: { Authorization: `Bearer ${token}` } }, 10000)
      .then(async (r) => {
        if (r.ok) {
          const data = await r.json();
          setIsAuthenticated(true);
          if (data?.user?.username) {
            setCurrentUser(data.user);
            if (data.user.preferred_language === 'en' || data.user.preferred_language === 'zh') {
              setLanguage(data.user.preferred_language);
            }
          }
          try {
            const sr = await fetchWithTimeout('/api/setup/status', { headers: { Authorization: `Bearer ${token}` } }, 8000);
            if (sr.ok) {
              const sd = await sr.json();
              if (!sd.setup_completed && data?.user?.role === 'Administrator') {
                setShowSetupWizard(true);
              }
            }
          } catch {
            // ignore setup-status errors
          }
        } else {
          localStorage.removeItem('netops_token');
        }
      })
      .catch(() => {
        localStorage.removeItem('netops_token');
      })
      .finally(() => {
        setAuthChecking(false);
      });
  }, [fetchWithTimeout, setLanguage, setShowSetupWizard]);

  const handleLogout = useCallback(() => {
    localStorage.removeItem('netops_token');
    setShowUserMenu(false);
    setShowNotifications(false);
    setIsAuthenticated(false);
  }, [setShowUserMenu, setShowNotifications]);

  const handleLogin = async () => {
    if (!loginForm.username.trim() || !loginForm.password.trim()) {
      setLoginError(language === 'zh' ? '请输入用户名和密码' : 'Enter username and password');
      return;
    }

    setIsAuthenticating(true);
    setLoginError(null);

    try {
      const response = await fetchWithTimeout(
        '/api/login',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username: loginForm.username.trim(),
            password: loginForm.password,
          }),
        },
        12000
      );
      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        setLoginError(data.detail || (language === 'zh' ? '登录失败' : 'Login failed'));
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

      setCurrentUser(data.user || { username: loginForm.username.trim() });
      setIsAuthenticated(true);
      setLoginForm((prev) => ({ ...prev, password: '' }));
      showToast(language === 'zh' ? '登录成功' : 'Login successful', 'success');

      try {
        const sr = await fetchWithTimeout('/api/setup/status', { headers: { Authorization: `Bearer ${data.token}` } }, 8000);
        if (sr.ok) {
          const sd = await sr.json();
          if (!sd.setup_completed && data.user?.role === 'Administrator') {
            setShowSetupWizard(true);
          }
        }
      } catch {
        // ignore setup-status errors
      }
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
  };
};
