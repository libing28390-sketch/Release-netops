import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface TerminalSession {
  id: string; // deviceId
  hostname: string;
  ip: string;
  role: 'normal' | 'admin';
  connectedAt: string;
}

interface AccessState {
  sessions: TerminalSession[];
  activeSessionId: string | null;
  sidebarCollapsed: boolean;
  
  // Actions
  addSession: (session: TerminalSession) => void;
  removeSession: (id: string) => void;
  setActiveSession: (id: string | null) => void;
  toggleSidebar: () => void;
}

export const useAccessStore = create<AccessState>()(
  persist(
    (set) => ({
      sessions: [],
      activeSessionId: null,
      sidebarCollapsed: false,

      addSession: (session) => set((state) => {
        const exists = state.sessions.find(s => s.id === session.id);
        if (exists) return { activeSessionId: session.id };
        return { 
          sessions: [...state.sessions, session],
          activeSessionId: session.id 
        };
      }),

      removeSession: (id) => set((state) => {
        const newSessions = state.sessions.filter(s => s.id !== id);
        let nextActive = state.activeSessionId;
        if (state.activeSessionId === id) {
          nextActive = newSessions.length > 0 ? newSessions[newSessions.length - 1].id : null;
        }
        return { sessions: newSessions, activeSessionId: nextActive };
      }),

      setActiveSession: (id) => set({ activeSessionId: id }),
      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
    }),
    {
      name: 'netops-access-center',
      partialize: (state) => ({ sidebarCollapsed: state.sidebarCollapsed }), // Only persist UI prefs
    }
  )
);
