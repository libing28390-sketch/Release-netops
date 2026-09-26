import { create } from 'zustand';

type Updater<T> = T | ((prev: T) => T);

interface UiState {
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (val: Updater<boolean>) => void;
  showSetupWizard: boolean;
  setShowSetupWizard: (val: Updater<boolean>) => void;
  showUserMenu: boolean;
  setShowUserMenu: (val: Updater<boolean>) => void;
  showNotifications: boolean;
  setShowNotifications: (val: Updater<boolean>) => void;
  cmdPaletteOpen: boolean;
  setCmdPaletteOpen: (val: Updater<boolean>) => void;
  isMobile: boolean;
  setIsMobile: (val: Updater<boolean>) => void;
  showAddScenarioModal: boolean;
  setShowAddScenarioModal: (val: Updater<boolean>) => void;
}

export const useUiStore = create<UiState>((set) => ({
  sidebarCollapsed: window.innerWidth < 768,
  setSidebarCollapsed: (val) => set((state) => ({ sidebarCollapsed: typeof val === 'function' ? val(state.sidebarCollapsed) : val })),
  showSetupWizard: false,
  setShowSetupWizard: (val) => set((state) => ({ showSetupWizard: typeof val === 'function' ? val(state.showSetupWizard) : val })),
  showUserMenu: false,
  setShowUserMenu: (val) => set((state) => ({ showUserMenu: typeof val === 'function' ? val(state.showUserMenu) : val })),
  showNotifications: false,
  setShowNotifications: (val) => set((state) => ({ showNotifications: typeof val === 'function' ? val(state.showNotifications) : val })),
  cmdPaletteOpen: false,
  setCmdPaletteOpen: (val) => set((state) => ({ cmdPaletteOpen: typeof val === 'function' ? val(state.cmdPaletteOpen) : val })),
  isMobile: window.innerWidth < 768,
  setIsMobile: (val) => set((state) => ({ isMobile: typeof val === 'function' ? val(state.isMobile) : val })),
  showAddScenarioModal: false,
  setShowAddScenarioModal: (val) => set((state) => ({ showAddScenarioModal: typeof val === 'function' ? val(state.showAddScenarioModal) : val })),
}));
