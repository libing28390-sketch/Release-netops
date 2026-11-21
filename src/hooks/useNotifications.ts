import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import type { NotificationItem, SessionUser } from '../types';
import { authHeaders } from '../api/http';

interface UseNotificationsProps {
  currentUser: SessionUser;
  language: string;
  isAuthenticated: boolean;
}

const buildNotificationFingerprint = (items: NotificationItem[]): string => (
  items.map((item) => `${item.id}|${item.time}|${item.severity}|${item.read ? '1' : '0'}|${item.title}`).join('\n')
);

export const useNotifications = ({ currentUser, language, isAuthenticated }: UseNotificationsProps) => {
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [notificationReadMap, setNotificationReadMap] = useState<Record<string, boolean>>(() => {
    try {
      const raw = localStorage.getItem('netops_notification_reads');
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      return (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) ? parsed : {};
    } catch {
      return {};
    }
  });
  const readMapRef = useRef(notificationReadMap);
  readMapRef.current = notificationReadMap;
  const lastFingerprintRef = useRef<string>('');
  const inFlightRef = useRef(false);

  const loadNotifications = useCallback(async () => {
    if (!isAuthenticated || !localStorage.getItem('netops_token') || inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      const userId = currentUser.id ? encodeURIComponent(String(currentUser.id)) : '';
      const url = userId ? `/api/notifications?limit=40&user_id=${userId}` : '/api/notifications?limit=40';
      const resp = await fetch(url, { headers: authHeaders() });
      if (!resp.ok) return;
      const data = await resp.json();
      const readMap = readMapRef.current;
      const mapped: NotificationItem[] = (Array.isArray(data) ? data : []).map((n: any) => ({
        id: String(n.id),
        title: n.source === 'system_resource'
          ? (language === 'zh' ? `平台资源告警: ${n.title}` : `Platform Resource Alert: ${n.title}`)
          : n.title,
        message: n.message,
        time: n.time,
        source: n.source,
        severity: n.severity,
        read: !!n.read || !!readMap[String(n.id)],
      }));
      const nextFingerprint = buildNotificationFingerprint(mapped);
      if (nextFingerprint !== lastFingerprintRef.current) {
        lastFingerprintRef.current = nextFingerprint;
        setNotifications(mapped);
      }
    } catch {
      // ignore polling errors
    } finally {
      inFlightRef.current = false;
    }
  }, [currentUser.id, language, isAuthenticated]);

  const markNotificationsAsRead = useCallback(async (ids: string[]) => {
    if (!isAuthenticated || !localStorage.getItem('netops_token') || !ids.length || !currentUser.id) return;
    try {
      await fetch('/api/notifications/read', {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify({ user_id: String(currentUser.id), notification_ids: ids }),
      });
      // Optimistically update local map
      setNotificationReadMap(prev => {
        const next = { ...prev };
        ids.forEach(id => { next[id] = true; });
        return next;
      });
      setNotifications(prev => {
        const next = prev.map(n => ids.includes(n.id) ? { ...n, read: true } : n);
        lastFingerprintRef.current = buildNotificationFingerprint(next);
        return next;
      });
    } catch {
      // keep optimistic local UI state even on transient API errors
    }
  }, [currentUser.id, isAuthenticated]);

  const markAllNotificationsRead = useCallback(async () => {
    const unreadIds = notifications.filter(n => !n.read).map(n => n.id);
    if (unreadIds.length > 0) {
      await markNotificationsAsRead(unreadIds);
    }
  }, [notifications, markNotificationsAsRead]);

  useEffect(() => {
    localStorage.setItem('netops_notification_reads', JSON.stringify(notificationReadMap));
  }, [notificationReadMap]);

  useEffect(() => {
    if (!isAuthenticated) {
      lastFingerprintRef.current = '';
      return;
    }
    void loadNotifications();
    const timer = window.setInterval(() => {
      if (typeof document === 'undefined' || document.visibilityState === 'visible') {
        void loadNotifications();
      }
    }, 15000);
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        void loadNotifications();
      }
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [isAuthenticated, loadNotifications]);

  const unreadNotifications = useMemo(
    () => notifications.filter(n => !n.read),
    [notifications],
  );
  const unreadCount = unreadNotifications.length;

  return {
    notifications,
    setNotifications,
    notificationReadMap,
    setNotificationReadMap,
    unreadNotifications,
    unreadCount,
    loadNotifications,
    markNotificationsAsRead,
    markAllNotificationsRead,
  };
};
