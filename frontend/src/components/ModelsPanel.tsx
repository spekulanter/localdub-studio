import type { ModelInfo, ModelsResponse } from "../api";
import { api } from "../api";
import { formatBytes, percent } from "../lib/bytes";

interface Props {
  data: ModelsResponse | null;
  onChanged: () => void;
  error?: string | null;
}

function Row({ m, onStart }: { m: ModelInfo; onStart: (ids?: string[]) => void }) {
  const d = m.download;
  const active = d?.status === "queued" || d?.status === "running";
  const pct = d ? percent(d.done, d.total) : 0;
  return (
    <li className="rounded-md border border-line p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium">
            {m.title}{" "}
            {!m.required && (
              <span className="rounded bg-inset px-1.5 text-xs font-normal text-muted">
                optional
              </span>
            )}
          </p>
          <p className="text-xs text-muted">
            {m.description} · about {formatBytes(m.size_bytes)}
          </p>
        </div>
        {m.installed ? (
          <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800">
            ✓ installed
          </span>
        ) : !m.available ? (
          <button
            onClick={() => onStart(["packages", m.id])}
            disabled={active}
            className="btn-primary btn-sm"
          >
            {active ? "Downloading…" : "Download with the optional packages"}
          </button>
        ) : (
          <button
            onClick={() => onStart([m.id])}
            disabled={active}
            className="btn-primary btn-sm"
          >
            {active ? "Downloading…" : d?.status === "error" ? "Try again" : "Download"}
          </button>
        )}
      </div>
      {(active || d?.status === "error") && !m.installed && (
        <div className="mt-2">
          <div
            role="progressbar"
            aria-label={`Download of ${m.title}`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct}
            className="meter"
          >
            <span
              data-state={d?.status === "error" ? "failed" : undefined}
              data-live={d?.status === "running"}
              style={{ width: `${d?.status === "error" ? 100 : pct}%` }}
            />
          </div>
          {d?.status === "error" ? (
            <p className="mt-1 text-sm text-bad" role="alert">
              {d.error}
            </p>
          ) : (
            <p className="mt-1 text-xs text-muted">
              {d?.status === "queued"
                ? "Waiting for the previous download…"
                : d?.show_bytes === false
                  ? `${pct}%`
                  : `${pct}% · ${formatBytes(d?.done ?? 0)} of ${formatBytes(d?.total ?? 0)}`}
              {d?.message ? ` · ${d.message}` : ""}
            </p>
          )}
        </div>
      )}
    </li>
  );
}

export function ModelsPanel({ data, onChanged, error }: Props) {
  if (!data) return <p className="text-muted">Loading…</p>;
  const missing = data.models.filter((m) => m.required && !m.installed);
  const total = missing.reduce((a, m) => a + m.size_bytes, 0);
  const start = (ids?: string[]) => {
    void api.downloadModels(ids).then(onChanged).catch(onChanged);
  };
  return (
    <div className="card space-y-4">
      <div>
        <p className="eyebrow mb-1.5">Setup</p>
        <h2 className="font-display text-[30px] font-semibold leading-tight">AI models</h2>
        <p className="text-sm text-muted">
          The models run on this computer and are downloaded once. Dubbing needs the three required ones.
        </p>
      </div>
      {error && (
        <p className="alert alert-bad" role="alert">
          {error}
        </p>
      )}
      {missing.length > 0 && (
        <button
          onClick={() => start()}
          disabled={data.busy}
          className="btn-primary"
        >
          {data.busy ? "Downloading…" : `Download the required models (${formatBytes(total)})`}
        </button>
      )}
      <ul className="space-y-2">
        {data.models.map((m) => (
          <Row key={m.id} m={m} onStart={(ids) => start(ids)} />
        ))}
      </ul>
    </div>
  );
}
