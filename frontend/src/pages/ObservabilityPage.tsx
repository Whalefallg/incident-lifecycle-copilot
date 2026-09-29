import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "../api/client";
import { AsyncState } from "../components/common/AsyncState";

function value(source: Record<string, unknown> | null | undefined, key: string): string {
  const current = source?.[key];
  return typeof current === "number" || typeof current === "string" || typeof current === "boolean"
    ? String(current)
    : "Unavailable";
}

export function ObservabilityPage() {
  const health = useQuery({ queryKey: ["monitoring", "health"], queryFn: api.getHealth });
  const system = useQuery({ queryKey: ["monitoring", "system"], queryFn: api.getSystemStats });
  const redis = useQuery({ queryKey: ["monitoring", "redis"], queryFn: api.getRedisInfo });

  if (health.isPending) return <AsyncState title="Checking system health" description="Reading the local monitoring endpoints." />;
  if (health.isError) return <AsyncState title="Monitoring unavailable" description={health.error instanceof ApiError ? health.error.message : "Health data could not be loaded."} action={<button type="button" onClick={() => void health.refetch()}>Retry</button>} />;

  const cache = system.data?.cache as Record<string, unknown> | null | undefined;
  const routing = system.data?.model_routing as Record<string, unknown> | null | undefined;
  const distribution = routing?.complexity_distribution as Record<string, unknown> | undefined;
  return (
    <div className="page-stack">
      <header className="page-header"><div><span className="eyebrow">Demo / Local Metrics</span><h1>Observability</h1><p>Runtime signals exposed by this local process and its configured dependencies.</p></div><span className="health-indicator">{health.data.status}</span></header>
      <div className="observability-grid">
        <section className="panel metric-card"><span className="eyebrow">Health</span><h2>{health.data.service}</h2><strong>{health.data.status}</strong><p>This is a process health signal, not an uptime or SLA claim.</p></section>
        <section className="panel metric-card"><span className="eyebrow">Semantic cache</span><h2>Cache activity</h2>{system.isPending ? <p>Loading…</p> : <dl><div><dt>Enabled</dt><dd>{value(cache, "enabled")}</dd></div><div><dt>Hits</dt><dd>{value(cache, "hits")}</dd></div><div><dt>Misses</dt><dd>{value(cache, "misses")}</dd></div><div><dt>Hit rate</dt><dd>{value(cache, "hit_rate_percent")}%</dd></div></dl>}</section>
        <section className="panel metric-card"><span className="eyebrow">Model routing</span><h2>Request distribution</h2>{system.isPending ? <p>Loading…</p> : <dl><div><dt>Enabled</dt><dd>{value(routing, "enabled")}</dd></div><div><dt>Simple</dt><dd>{value(distribution, "simple")}</dd></div><div><dt>Medium</dt><dd>{value(distribution, "medium")}</dd></div><div><dt>Complex</dt><dd>{value(distribution, "complex")}</dd></div></dl>}</section>
        <section className="panel metric-card"><span className="eyebrow">Redis</span><h2>State dependency</h2>{redis.isPending ? <p>Loading…</p> : redis.data?.status === "ok" ? <dl><div><dt>Version</dt><dd>{redis.data.redis_version ?? "Unknown"}</dd></div><div><dt>Uptime</dt><dd>{redis.data.uptime_seconds ?? 0}s</dd></div><div><dt>DB size</dt><dd>{redis.data.db_size ?? 0}</dd></div><div><dt>Memory</dt><dd>{redis.data.used_memory_human ?? "Unknown"}</dd></div></dl> : <p className="metric-unavailable">Not connected in this environment. {redis.data?.error}</p>}</section>
      </div>
      {system.data?.status === "error" ? <div className="stream-error" role="alert">System metrics are unavailable: {system.data.error}</div> : null}
    </div>
  );
}
