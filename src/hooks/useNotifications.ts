import { useState, useEffect, useCallback } from 'react';
import type { NotificationItem, SessionUser } from '../types';

interface UseNotificationsProps {
  currentUser: SessionUser;
  language: string;
  isAuthenticated: boolean;
}

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

  const loadNotifications = useCallback(async () => {
    if (!isAuthenticated) return;
    try {
      const userId = currentUser.id ? encodeURIComponent(String(currentUser.id)) : '';
      const url = userId ? `/api/notifications?limit=40&user_id=${userId}` : '/api/notifications?limit=40';
      const resp = await fetch(url);
      if (!resp.ok) return;
      const data = await resp.json();
      setNotifications((data || []).map((n: any) => ({
        id: String(n.id),
        title: n.source === 'system_resource'
          ? (language === 'zh' ? `平台资源告警: ${n.title}` : `Platform Resource Alert: ${n.title}`)
          : n.title,
        message: n.message,
        time: n.time,
        source: n.source,
        severity: n.severity,
        read: !!n.read || !!notificationReadMap[String(n.id)],
      })));
    } catch {
      // ignore polling errors
    }
  }, [currentUser.id, language, notificationReadMap, isAuthenticated]);

  const markNotificationsAsRead = useCallback(async (ids: string[]) => {
    if (!ids.length || !currentUser.id) return;
    try {
      await fetch('/api/notifications/read', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: String(currentUser.id), notification_ids: ids }),
      });
      // Optimistically update local map
      setNotificationReadMap(prev => {
        const next = { ...prev };
        ids.forEach(id => { next[id] = true; });
        return next;
      });
      setNotifications(prev => prev.map(n => ids.includes(n.id) ? { ...n, read: true } : n));
    } catch {
      // keep optimistic local UI state even on transient API errors
    }
  }, [currentUser.id]);

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
    if (isAuthenticated) {
      loadNotifications();
      const timer = setInterval(loadNotifications, 15000);
      return () => clearInterval(timer);
    }
  }, [isAuthenticated, loadNotifications]);

  const unreadNotifications = notifications.filter(n => !n.read);
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
    markAllNotificationsRead
  };
};
