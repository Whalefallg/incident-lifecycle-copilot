import { NavLink, Outlet } from "react-router-dom";

import { useWorkspaceStore } from "../../stores/workspaceStore";

export function AppShell() {
  const sidebarCollapsed = useWorkspaceStore((state) => state.sidebarCollapsed);
  const toggleSidebar = useWorkspaceStore((state) => state.toggleSidebar);

  return (
    <div className={sidebarCollapsed ? "app-shell is-collapsed" : "app-shell"}>
      <header className="topbar">
        <div>
          <span className="eyebrow">Incident Operations</span>
          <strong>Lifecycle Copilot</strong>
        </div>
        <span className="environment-badge">Local environment</span>
      </header>
      <aside className="sidebar" aria-label="Primary navigation">
        <button
          className="sidebar-toggle"
          type="button"
          onClick={toggleSidebar}
          aria-label={sidebarCollapsed ? "Expand navigation" : "Collapse navigation"}
        >
          {sidebarCollapsed ? "→" : "←"}
        </button>
        <nav>
          <NavLink to="/incidents">{sidebarCollapsed ? "IN" : "Incidents"}</NavLink>
          <NavLink to="/knowledge">{sidebarCollapsed ? "KN" : "Knowledge"}</NavLink>
          <NavLink to="/observability">{sidebarCollapsed ? "OB" : "Observability"}</NavLink>
        </nav>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
