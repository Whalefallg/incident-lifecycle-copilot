import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import { queryClient } from "./app/queryClient";
import { router } from "./app/router";
import { QueryClientProvider } from "@tanstack/react-query";
import "./styles/global.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Application root element was not found");
}

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
