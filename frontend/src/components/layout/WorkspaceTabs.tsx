import type { WorkspaceTab } from "../../stores/workspaceStore";

interface WorkspaceTabsProps {
  selected: WorkspaceTab;
  timelineCount: number | null;
  runbookCount: number | null;
  traceCount: number | null;
  postmortemCount: number | null;
  onSelect: (tab: WorkspaceTab) => void;
}

export function WorkspaceTabs({ selected, timelineCount, runbookCount, traceCount, postmortemCount, onSelect }: WorkspaceTabsProps) {
  const tabs: Array<{ id: WorkspaceTab; label: string; count: number | null }> = [
    { id: "conversation", label: "Conversation", count: null },
    { id: "timeline", label: "Timeline", count: timelineCount },
    { id: "runbooks", label: "Runbooks", count: runbookCount },
    { id: "trace", label: "Agent Trace", count: traceCount },
    { id: "postmortem", label: "Postmortem", count: postmortemCount },
  ];
  return (
    <div className="workspace-tabs" role="tablist" aria-label="Incident workspace views">
      {tabs.map((tab) => <button key={tab.id} type="button" role="tab" aria-selected={selected === tab.id} aria-controls={`${tab.id}-panel`} id={`${tab.id}-tab`} onClick={() => onSelect(tab.id)}>{tab.label}{tab.count === null ? "" : ` (${tab.count})`}</button>)}
    </div>
  );
}
