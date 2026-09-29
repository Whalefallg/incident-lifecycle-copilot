interface WorkspaceTabsProps {
  selected: "conversation" | "timeline";
  timelineCount: number | null;
  onSelect: (tab: "conversation" | "timeline") => void;
}

export function WorkspaceTabs({ selected, timelineCount, onSelect }: WorkspaceTabsProps) {
  return (
    <div className="workspace-tabs" role="tablist" aria-label="Incident workspace views">
      <button type="button" role="tab" aria-selected={selected === "conversation"} aria-controls="conversation-panel" id="conversation-tab" onClick={() => onSelect("conversation")}>Conversation</button>
      <button type="button" role="tab" aria-selected={selected === "timeline"} aria-controls="timeline-panel" id="timeline-tab" onClick={() => onSelect("timeline")}>Timeline{timelineCount === null ? "" : ` (${timelineCount})`}</button>
    </div>
  );
}
