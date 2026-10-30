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
    <li className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium">
            {m.title}{" "}
            {!m.required && (
              <span className="rounded bg-slate-100 px-1.5 text-xs font-normal text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                optional
              </span>
            )}
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {m.description} · about {formatBytes(m.size_bytes)}
          </p>
        </div>
        {m.installed ? (
          <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
            ✓ installed
          </span>
        ) : !m.available ? (
          <button
            onClick={() => onStart(["packages", m.id])}
            disabled={active}
            className="rounded-md bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50"
          >
            {active ? "Downloading…" : "Download with the optional packages"}
          </button>
        ) : (
          <button
            onClick={() => onStart([m.id])}
            disabled={active}
            className="rounded-md bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50"
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
            className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800"
          >
            <div
              className={`h-full transition-all ${d?.status === "error" ? "bg-red-500" : "bg-indigo-500"}`}
              style={{ width: `${d?.status === "error" ? 100 : pct}%` }}
            />
          </div>
          {d?.status === "error" ? (
            <p className="mt-1 text-sm text-red-700 dark:text-red-300" role="alert">
              {d.error}
            </p>
          ) : (
            <p className="mt-1 text-xs text-slate-500">
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
  if (!data) return <p className="text-slate-500">Loading…</p>;
  const missing = data.models.filter((m) => m.required && !m.installed);
  const total = missing.reduce((a, m) => a + m.size_bytes, 0);
  const start = (ids?: string[]) => {
    void api.downloadModels(ids).then(onChanged).catch(onChanged);
  };
  return (
    <div className="space-y-4 rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
      <div>
        <h2 className="text-lg font-semibold">AI models</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          The models run on this computer and are downloaded once. Dubbing needs the three required ones.
        </p>
      </div>
      {error && (
        <p className="rounded-md bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950 dark:text-red-200" role="alert">
          {error}
        </p>
      )}
      {missing.length > 0 && (
        <button
          onClick={() => start()}
          disabled={data.busy}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
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
