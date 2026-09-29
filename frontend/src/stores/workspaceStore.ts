import { create } from "zustand";

import type { StreamEvent } from "../api/stream";

export interface StreamState {
  requestId: string | null;
  status: "idle" | "streaming" | "completed" | "error";
  text: string;
  lastSequence: number;
  error: string | null;
}

export const initialStreamState: StreamState = {
  requestId: null,
  status: "idle",
  text: "",
  lastSequence: -1,
  error: null,
};

export function reduceStreamState(state: StreamState, event: StreamEvent): StreamState {
  if (event.sequence <= state.lastSequence) return state;
  const next = { ...state, lastSequence: event.sequence };
  if (event.type === "message.delta") return { ...next, text: state.text + event.payload.text };
  if (event.type === "message.completed") return { ...next, text: event.payload.text };
  if (event.type === "request.completed") return { ...next, status: "completed", error: null };
  if (event.type === "error") return { ...next, status: "error", error: event.payload.message };
  return next;
}

interface WorkspaceState {
  sidebarCollapsed: boolean;
  streams: Record<string, StreamState>;
  toggleSidebar: () => void;
  startStream: (incidentId: string, requestId: string) => void;
  applyStreamEvent: (incidentId: string, event: StreamEvent) => void;
  failStream: (incidentId: string, message: string) => void;
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  sidebarCollapsed: false,
  streams: {},
  toggleSidebar: () =>
    set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
  startStream: (incidentId, requestId) =>
    set((state) => ({
      streams: {
        ...state.streams,
        [incidentId]: { ...initialStreamState, requestId, status: "streaming" },
      },
    })),
  applyStreamEvent: (incidentId, event) =>
    set((state) => ({
      streams: {
        ...state.streams,
        [incidentId]: reduceStreamState(
          state.streams[incidentId] ?? initialStreamState,
          event,
        ),
      },
    })),
  failStream: (incidentId, message) =>
    set((state) => ({
      streams: {
        ...state.streams,
        [incidentId]: {
          ...(state.streams[incidentId] ?? initialStreamState),
          status: "error",
          error: message,
        },
      },
    })),
}));
