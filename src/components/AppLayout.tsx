import React from 'react';
import { useLocation } from 'react-router-dom';
import CommandPalette from './CommandPalette';
import ModuleSubNav from './ModuleSubNav';
import TopHeader from './TopHeader';
import VersionBanner from './VersionBanner';
import VersionUpdateNotifier from './VersionUpdateNotifier';
import ToastNotification, { type ToastState } from './ToastNotification';
import type { NotificationItem, ThemeMode, User as UserType } from '../types';
import { useSystem } from '../hooks/useSystem';

interface CommandItem {
  path: string;
  label: string;
  group: string;
}

interface AppLayoutProps {
  language: 'zh' | 'en';
  resolvedTheme: 'light' | 'dark';
  themeMode: ThemeMode;
  sidebarCollapsed: boolean;
  activeTab: string;
  pageTitle: string;
  currentUser: UserType;
  currentUserRole: string;
  currentAvatar: string;
  currentUserLastLogin?: string;
  unreadNotificationCount: number;
  unreadNotifications: NotificationItem[];
  showNotifications: boolean;
  showUserMenu: boolean;
  userMenuRef: React.RefObject<HTMLDivElement | null>;
  renderAvatarContent: (avatarValue: string, fallbackIconSize: number) => React.ReactNode;
  onToggleSidebar: () => void;
  onToggleNotifications: () => void;
  onToggleUserMenu: () => void;
  onOpenProfile: () => void;
  onOpenDashboard: () => void;
  onOpenMonitoring: () => void;
  onOpenHealth: () => void;
  onOpenHistory: () => void;
  onThemeModeChange: (mode: ThemeMode) => void;
  onLanguageChange: (language: 'zh' | 'en') => void;
  onSwitchUser: (username: string) => void;
  availableUsers?: any[];
  onLogout: () => void;
  onMarkAllNotificationsRead: () => void;
  onMarkNotificationRead: (id: string) => void;
  onNotificationClick: (item: NotificationItem) => void;
  onNavigate: (path: string) => void;
  cmdPaletteOpen: boolean;
  cmdPaletteQuery: string;
  cmdPaletteFiltered: CommandItem[];
  pinnedPaths: string[];
  setCmdPaletteOpen: (open: boolean) => void;
  setCmdPaletteQuery: (query: string) => void;
  togglePin: (path: string) => void;
  toast: ToastState | null;
  onCloseToast: () => void;
  children?: React.ReactNode;
}

const AppLayout: React.FC<AppLayoutProps> = ({
  language,
  resolvedTheme,
  themeMode,
  sidebarCollapsed,
  activeTab,
  pageTitle,
  currentUser,
  currentUserRole,
  currentAvatar,
  currentUserLastLogin,
  unreadNotificationCount,
  unreadNotifications,
  showNotifications,
  showUserMenu,
  userMenuRef,
  renderAvatarContent,
  onToggleSidebar,
  onToggleNotifications,
  onToggleUserMenu,
  onOpenProfile,
  onOpenDashboard,
  onOpenMonitoring,
  onOpenHealth,
  onOpenHistory,
  onThemeModeChange,
  onLanguageChange,
  onSwitchUser,
  availableUsers,
  onLogout,
  onMarkAllNotificationsRead,
  onMarkNotificationRead,
  onNotificationClick,
  onNavigate,
  cmdPaletteOpen,
  cmdPaletteQuery,
  cmdPaletteFiltered,
  pinnedPaths,
  setCmdPaletteOpen,
  setCmdPaletteQuery,
  togglePin,
  toast,
  onCloseToast,
  children,
}) => {
  const location = useLocation();
  const { systemInfo } = useSystem();

  React.useEffect(() => {
    const baseTitle = systemInfo?.system_name || 'Nexora';
    document.title = pageTitle ? `${pageTitle} | ${baseTitle}` : baseTitle;
  }, [systemInfo?.system_name, pageTitle]);

  return (
    <div className="app-shell flex h-screen overflow-hidden">
      <div className="flex-1 flex flex-col overflow-hidden">
        <VersionBanner />
        <TopHeader
          language={language}
          resolvedTheme={resolvedTheme}
          themeMode={themeMode}
          sidebarCollapsed={sidebarCollapsed}
          isHomePage={activeTab === 'dashboard'}
          pageTitle={pageTitle}
          currentUser={currentUser}
          currentAvatar={currentAvatar}
          currentUserLastLogin={currentUserLastLogin}
          unreadNotificationCount={unreadNotificationCount}
          unreadNotifications={unreadNotifications}
          showNotifications={showNotifications}
          showUserMenu={showUserMenu}
          userMenuRef={userMenuRef}
          renderAvatarContent={renderAvatarContent}
          onToggleSidebar={onToggleSidebar}
          onToggleNotifications={onToggleNotifications}
          onToggleUserMenu={onToggleUserMenu}
          onOpenProfile={onOpenProfile}
          onOpenDashboard={onOpenDashboard}
          onOpenMonitoring={onOpenMonitoring}
          onOpenHealth={onOpenHealth}
          onOpenHistory={onOpenHistory}
          onThemeModeChange={onThemeModeChange}
          onLanguageChange={onLanguageChange}
          onSwitchUser={onSwitchUser}
          availableUsers={availableUsers}
          onLogout={onLogout}
          onMarkAllNotificationsRead={onMarkAllNotificationsRead}
          onMarkNotificationRead={onMarkNotificationRead}
          onNotificationClick={onNotificationClick}
          onNavigate={onNavigate}
        />

        <div className="flex flex-1 overflow-hidden min-h-0">
          {activeTab !== 'dashboard' && !sidebarCollapsed && (
            <ModuleSubNav language={language} userRole={currentUserRole} currentUser={currentUser} />
          )}
          <div className="flex-1 overflow-hidden flex flex-col min-h-0">{children}</div>
        </div>

        <footer className="h-10 px-8 border-t flex items-center justify-between nx-micro-text border-[var(--header-border)] text-[var(--muted-text)] bg-[var(--sidebar-bg)]">
          <span>Copyright (c) {new Date().getFullYear()} {systemInfo?.system_name || 'Nexora'}. All rights reserved.</span>
          <span className="font-mono">{systemInfo?.version || 'v1.0.7'}</span>
        </footer>
      </div>

      <CommandPalette
        open={cmdPaletteOpen}
        language={language}
        query={cmdPaletteQuery}
        items={cmdPaletteFiltered}
        pinnedPaths={pinnedPaths}
        currentPath={location.pathname}
        onClose={() => setCmdPaletteOpen(false)}
        onQueryChange={setCmdPaletteQuery}
        onNavigate={(path) => {
          onNavigate(path);
          setCmdPaletteOpen(false);
        }}
        onTogglePin={togglePin}
      />

      <ToastNotification toast={toast} onClose={onCloseToast} />
      <VersionUpdateNotifier language={language} />
    </div>
  );
};

export default AppLayout;
