import { create } from "zustand";

interface WorkspaceState {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  sidebarCollapsed: false,
  toggleSidebar: () =>
    set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
}));
