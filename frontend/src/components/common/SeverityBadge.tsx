export function SeverityBadge({ severity }: { severity: string | null }) {
  const normalized = severity?.toUpperCase() ?? "UNSET";
  return <span className={`severity severity-${normalized.toLowerCase()}`}>{normalized}</span>;
}
