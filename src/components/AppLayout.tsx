import React from 'react';
import { useLocation } from 'react-router-dom';
import CommandPalette from './CommandPalette';
import ModuleSubNav from './ModuleSubNav';
import TopHeader from './TopHeader';
import ToastNotification, { type ToastState } from './ToastNotification';
import type { NotificationItem, ThemeMode, User as UserType } from '../types';

interface CommandItem {
  path: string;
  label: string;
  group: string;
}

interface AppLayoutProps {
  language: 'zh' | 'en';
  resolvedTheme: string;
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
  children,
}) => {
  const location = useLocation();

  return (
    <div className="app-shell flex h-screen text-[#141414] font-sans overflow-hidden">
      <div className="flex-1 flex flex-col overflow-hidden">
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
          onLogout={onLogout}
          onMarkAllNotificationsRead={onMarkAllNotificationsRead}
          onMarkNotificationRead={onMarkNotificationRead}
          onNotificationClick={onNotificationClick}
          onNavigate={onNavigate}
        />

        <div className="flex flex-1 overflow-hidden">
          {activeTab !== 'dashboard' && !sidebarCollapsed && (
            <ModuleSubNav language={language} userRole={currentUserRole} />
          )}
          <div className="flex-1 overflow-hidden">{children}</div>
        </div>

        <footer className={`h-10 px-8 border-t flex items-center justify-between text-[11px] ${resolvedTheme === 'dark' ? 'border-white/10 text-white/45 bg-[#0b1320]' : 'border-black/8 text-black/45 bg-white/70'}`}>
          <span>Copyright (c) {new Date().getFullYear()} Nexora. All rights reserved.</span>
          <span className="font-mono">NOC v2.0</span>
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

      <ToastNotification toast={toast} />
    </div>
  );
};

export default AppLayout;
