import { create } from "zustand";

import type { StreamEvent } from "../api/stream";

export interface StreamState {
  requestId: string | null;
  status: "idle" | "streaming" | "completed" | "error";
  text: string;
  lastSequence: number;
  error: string | null;
  workflowState: string | null;
  agents: Record<string, AgentActivity>;
}

export interface AgentActivity {
  name: string;
  status: "running" | "completed" | "failed";
  durationMs: number | null;
  sequence: number;
}

export const initialStreamState: StreamState = {
  requestId: null,
  status: "idle",
  text: "",
  lastSequence: -1,
  error: null,
  workflowState: null,
  agents: {},
};

export function reduceStreamState(state: StreamState, event: StreamEvent): StreamState {
  if (event.sequence <= state.lastSequence) return state;
  const next = { ...state, lastSequence: event.sequence };
  if (event.type === "message.delta") return { ...next, text: state.text + event.payload.text };
  if (event.type === "message.completed") return { ...next, text: event.payload.text };
  if (event.type === "workflow.state_changed") return { ...next, workflowState: event.payload.to };
  if (event.type === "agent.started" || event.type === "agent.completed") {
    return {
      ...next,
      agents: {
        ...state.agents,
        [event.payload.agent]: {
          name: event.payload.agent,
          status: event.type === "agent.started" ? "running" : "completed",
          durationMs: event.payload.duration_ms ?? null,
          sequence: event.sequence,
        },
      },
    };
  }
  if (event.type === "request.completed") return { ...next, status: "completed", error: null };
  if (event.type === "error") {
    const agents = Object.fromEntries(Object.entries(state.agents).map(([name, activity]) => [name, activity.status === "running" ? { ...activity, status: "failed" as const } : activity]));
    return { ...next, status: "error", error: event.payload.message, agents };
  }
  return next;
}

interface WorkspaceState {
  sidebarCollapsed: boolean;
  selectedWorkspaceTab: "conversation" | "timeline";
  streams: Record<string, StreamState>;
  toggleSidebar: () => void;
  selectWorkspaceTab: (tab: "conversation" | "timeline") => void;
  startStream: (incidentId: string, requestId: string) => void;
  applyStreamEvent: (incidentId: string, event: StreamEvent) => void;
  failStream: (incidentId: string, message: string) => void;
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  sidebarCollapsed: false,
  selectedWorkspaceTab: "conversation",
  streams: {},
  toggleSidebar: () =>
    set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
  selectWorkspaceTab: (selectedWorkspaceTab) => set({ selectedWorkspaceTab }),
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
