import { Navigate, createBrowserRouter } from "react-router-dom";

import { AppShell } from "../components/layout/AppShell";
import { IncidentListPage } from "../pages/IncidentListPage";
import { IncidentWorkspacePage } from "../pages/IncidentWorkspacePage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { KnowledgePage } from "../pages/KnowledgePage";
import { ObservabilityPage } from "../pages/ObservabilityPage";

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/incidents" replace /> },
      { path: "/incidents", element: <IncidentListPage /> },
      { path: "/incidents/:incidentId", element: <IncidentWorkspacePage /> },
      { path: "/knowledge", element: <KnowledgePage /> },
      { path: "/observability", element: <ObservabilityPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
