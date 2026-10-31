import { useState } from "react";
import type { ModelInfo, ModelRole, ModelsResponse } from "../api";
import { api } from "../api";
import { formatBytes, percent } from "../lib/bytes";

interface Props {
  data: ModelsResponse | null;
  onChanged: () => void;
  error?: string | null;
}

const STATUS_LABEL: Record<ModelInfo["status"], string> = {
  recommended: "Recommended",
  available: "Available",
  experimental: "Experimental",
  not_recommended: "Not recommended",
  custom: "Added by you",
};

const FIT_CLASS: Record<string, string> = {
  ok: "chip chip-ok",
  cpu: "chip",
  partial: "chip chip-warn",
  too_big: "chip chip-warn",
  no_gpu: "chip chip-warn",
};

const FIT_LABEL: Record<string, string> = {
  ok: "Fits your graphics card",
  cpu: "Runs on the processor",
  partial: "Only partly fits your card",
  too_big: "Too big for your card",
  no_gpu: "No NVIDIA card found",
};

function Progress({ m }: { m: ModelInfo }) {
  const d = m.download;
  if (!d || (d.status !== "queued" && d.status !== "running" && d.status !== "error")) return null;
  const pct = percent(d.done, d.total);
  return (
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
          data-state={d.status === "error" ? "failed" : undefined}
          data-live={d.status === "running"}
          style={{ width: `${d.status === "error" ? 100 : pct}%` }}
        />
      </div>
      {d.status === "error" ? (
        <p className="mt-1 text-sm text-bad" role="alert">
          {d.error}
        </p>
      ) : (
        <p className="mt-1 text-xs text-muted">
          {d.status === "queued"
            ? "Waiting for the previous download…"
            : d.show_bytes === false
              ? `${pct}%`
              : `${pct}% · ${formatBytes(d.done)} of ${formatBytes(d.total)}`}
          {d.message && d.status === "running" ? ` · ${d.message}` : ""}
        </p>
      )}
    </div>
  );
}

function Details({ m }: { m: ModelInfo }) {
  const r = m.requirements;
  return (
    <details className="mt-2 text-sm">
      <summary className="cursor-pointer text-muted">Details: who it is for, what it needs</summary>
      <div className="mt-2 space-y-2">
        {m.choose_if.length > 0 && (
          <div>
            <p className="font-medium">Choose it if</p>
            <ul className="list-disc pl-5 text-muted">
              {m.choose_if.map((t) => (
                <li key={t}>{t}</li>
              ))}
            </ul>
          </div>
        )}
        {m.avoid_if.length > 0 && (
          <div>
            <p className="font-medium">Skip it if</p>
            <ul className="list-disc pl-5 text-muted">
              {m.avoid_if.map((t) => (
                <li key={t}>{t}</li>
              ))}
            </ul>
          </div>
        )}
        <p className="text-muted">
          <span className="font-medium text-ink">Needs:</span> about {formatBytes(m.size_bytes)} download,{" "}
          {r.disk_gb} GB on disk
          {r.vram_gb !== null ? `, about ${r.vram_gb} GB of graphics memory` : ", no graphics memory"}.
          {r.note ? ` ${r.note}` : ""}
          {r.needs_packages ? " Needs the optional packages." : ""}
        </p>
        <p className="text-muted">
          <span className="font-medium text-ink">This computer:</span> {m.fits.text}
        </p>
        {m.languages && (
          <p className="text-muted">
            <span className="font-medium text-ink">Languages:</span> {m.languages}
          </p>
        )}
        <p className="text-muted">
          <span className="font-medium text-ink">Measured here:</span>{" "}
          {m.measured ?? "Not measured yet. Treat the description as the maker's claim, not our result."}
        </p>
        <p className="text-muted">
          <span className="font-medium text-ink">Licence:</span>{" "}
          <a href={m.license.url} target="_blank" rel="noreferrer noopener" className="underline">
            {m.license.name}
          </a>
          {m.pinned ? ` · ${m.pinned}` : ""}
        </p>
        {m.installed && (m.locations.length > 0 || m.store_note) && (
          <p className="break-all font-mono text-xs text-muted">
            {m.locations.length > 0 ? m.locations.join("\n") : m.store_note}
            {m.size_on_disk !== null ? ` · ${formatBytes(m.size_on_disk)} on disk` : ""}
          </p>
        )}
      </div>
    </details>
  );
}

function Card({
  m,
  role,
  data,
  onAction,
}: {
  m: ModelInfo;
  role: ModelRole | undefined;
  data: ModelsResponse;
  onAction: (fn: () => Promise<unknown>) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const d = m.download;
  const active = d?.status === "queued" || d?.status === "running";
  const shared = m.store_note !== null;
  const lastOfRequired =
    m.required && data.models.filter((x) => x.role === m.role && x.installed).length === 1;
  return (
    <li className="rounded-md border border-line p-3" data-testid={`model-${m.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium">{m.title}</p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            <span className={`chip ${m.status === "recommended" ? "chip-ok" : m.status === "not_recommended" ? "chip-warn" : ""}`}>
              {STATUS_LABEL[m.status]}
            </span>
            {m.installed && <span className="chip chip-ok">✓ installed</span>}
            {m.selected && role?.selectable && <span className="chip chip-ok">In use for new dubs</span>}
            {m.update.available && <span className="chip chip-warn">Update available</span>}
            <span className={FIT_CLASS[m.fits.level] ?? "chip"} title={m.fits.text}>
              {FIT_LABEL[m.fits.level] ?? m.fits.level}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!m.installed && !m.available && (
            <button disabled={active} className="btn-primary btn-sm" onClick={() => onAction(() => api.downloadModels(["packages", m.id]))}>
              {active ? "Downloading…" : "Download with the optional packages"}
            </button>
          )}
          {!m.installed && m.available && (
            <button disabled={active} className="btn-primary btn-sm" onClick={() => onAction(() => api.downloadModels([m.id]))}>
              {active ? "Downloading…" : d?.status === "error" ? "Try again" : `Download (${formatBytes(m.size_bytes)})`}
            </button>
          )}
          {m.installed && role?.selectable && !m.selected && (
            <button className="btn-secondary btn-sm" onClick={() => onAction(() => api.selectModel(m.id))}>
              Use for new dubs
            </button>
          )}
          {m.installed && m.update.available && (
            <button disabled={active} className="btn-primary btn-sm" onClick={() => onAction(() => api.modelAction(m.id, "update"))}>
              Update
            </button>
          )}
          {m.installed && m.can_open_folder && (
            <button className="btn-ghost btn-sm" onClick={() => onAction(() => api.openModelsFolder(m.id))}>
              Open folder
            </button>
          )}
          {m.installed && (
            <button disabled={active} className="btn-ghost btn-sm" onClick={() => onAction(() => api.modelAction(m.id, "repair"))}>
              Re-download
            </button>
          )}
          {m.installed && m.can_delete && !confirming && (
            <button disabled={active} className="btn-ghost btn-sm" onClick={() => setConfirming(true)}>
              Delete
            </button>
          )}
        </div>
      </div>
      <p className="mt-2 text-sm text-muted">{m.summary}</p>
      {confirming && (
        <div className="alert mt-2 space-y-2 text-sm" role="alertdialog" aria-label={`Delete ${m.title}`}>
          <p>
            Delete <strong>{m.title}</strong> from this computer? You can download it again later.
          </p>
          {shared && <p>Ollama keeps its models for every program on this PC; other programs lose this model too.</p>}
          {lastOfRequired && <p>It is the only one installed for this step, so dubbing will not work until you download one again.</p>}
          <div className="flex gap-2">
            <button
              className="btn-primary btn-sm"
              onClick={() => {
                setConfirming(false);
                onAction(() => api.deleteModel(m.id));
              }}
            >
              Yes, delete
            </button>
            <button className="btn-ghost btn-sm" onClick={() => setConfirming(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      <Progress m={m} />
      <Details m={m} />
    </li>
  );
}

export function ModelsPanel({ data, onChanged, error }: Props) {
  const [message, setMessage] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [tag, setTag] = useState("");
  const [sizes, setSizes] = useState<ModelsResponse | null>(null);
  if (!data) return <p className="text-muted">Loading…</p>;
  const view = sizes ? { ...data, models: data.models.map((m) => ({ ...m, size_on_disk: sizes.models.find((x) => x.id === m.id)?.size_on_disk ?? m.size_on_disk })) } : data;
  const missing = data.models.filter((m) => m.required && data.required_missing.includes(m.id));
  const total = missing.reduce((a, m) => a + m.size_bytes, 0);
  const hw = data.hardware;

  const run = (fn: () => Promise<unknown>, after?: (r: unknown) => void) => {
    setProblem(null);
    setMessage(null);
    fn()
      .then((r) => {
        after?.(r);
        onChanged();
      })
      .catch((e: unknown) => {
        setProblem(e instanceof Error ? e.message : String(e));
        onChanged();
      });
  };

  const checkUpdates = () =>
    run(api.checkModelUpdates, (r) => {
      const res = r as { checked: number; updates: string[]; errors: Record<string, string> };
      const failed = Object.keys(res.errors).length;
      setMessage(
        `${res.checked} installed model${res.checked === 1 ? "" : "s"} checked: ` +
          (res.updates.length > 0 ? `${res.updates.length} can be updated.` : "all up to date.") +
          (failed > 0 ? ` ${failed} could not be checked (offline?).` : ""),
      );
    });

  const roles: ModelRole[] = data.roles?.length
    ? data.roles
    : Array.from(new Set(data.models.map((m) => m.role))).map((id) => ({
        id, title: id, description: "", required: true, selectable: false, selected_id: null,
      }));
  return (
    <div className="card space-y-5">
      <div>
        <p className="eyebrow mb-1.5">Setup</p>
        <h2 className="font-display text-[30px] font-semibold leading-tight">AI models</h2>
        <p className="text-sm text-muted">
          Everything runs on this computer. Models are downloaded once, you decide which ones, and you can update or
          delete them here. Dubbing needs one model for each of the three required steps.
        </p>
      </div>

      {hw && (
        <div className="rounded-md border border-line p-3 text-sm" aria-label="This computer">
          <p>
            <span className="font-medium">Graphics card:</span>{" "}
            {hw.gpu ? `${hw.gpu.name}, ${hw.gpu.vram_gb} GB` : "no NVIDIA card found (models run on the processor, slowly)"}
            {" · "}
            <span className="font-medium">Memory:</span> {hw.ram_gb ?? "?"} GB
            {" · "}
            <span className="font-medium">Free disk:</span> {formatBytes(hw.disk_free_bytes)}
          </p>
          {data.paths && (
            <p className="mt-1 break-all font-mono text-xs text-muted">Models folder: {data.paths.models}</p>
          )}
          <div className="mt-2 flex flex-wrap gap-2">
            <button className="btn-secondary btn-sm" onClick={() => run(() => api.openModelsFolder())}>
              Open models folder
            </button>
            <button className="btn-secondary btn-sm" onClick={checkUpdates}>
              Check for updates
            </button>
            <button
              className="btn-ghost btn-sm"
              onClick={() => run(() => api.models(true), (r) => setSizes(r as ModelsResponse))}
            >
              Measure disk usage
            </button>
          </div>
          {sizes && typeof sizes.models_bytes === "number" && (
            <p className="mt-1 text-xs text-muted">Models folder in total: {formatBytes(sizes.models_bytes)} (Ollama's own store is separate).</p>
          )}
        </div>
      )}

      {(error || problem) && (
        <p className="alert alert-bad" role="alert">
          {error ?? problem}
        </p>
      )}
      {message && (
        <p className="alert" role="status">
          {message}
        </p>
      )}
      {missing.length > 0 && (
        <button onClick={() => run(() => api.downloadModels())} disabled={data.busy} className="btn-primary">
          {data.busy ? "Downloading…" : `Download the required models (${formatBytes(total)})`}
        </button>
      )}

      {roles.map((role) => {
        const rows = view.models.filter((m) => m.role === role.id);
        if (rows.length === 0) return null;
        return (
          <section key={role.id} aria-label={role.title} className="space-y-2">
            <div>
              <h3 className="font-display text-xl font-semibold">
                {role.title}{" "}
                {!role.required && <span className="chip">optional</span>}
              </h3>
              <p className="text-sm text-muted">{role.description}</p>
            </div>
            <ul className="space-y-2">
              {rows.map((m) => (
                <Card key={m.id} m={m} role={role} data={view} onAction={run} />
              ))}
            </ul>
            {role.id === "translation" && (
              <form
                className="flex flex-wrap items-center gap-2 text-sm"
                onSubmit={(e) => {
                  e.preventDefault();
                  const t = tag.trim();
                  if (!t) return;
                  run(() => api.addOllamaModel(t), () => {
                    setTag("");
                    setMessage(`Added ${t}. Download it from the list above.`);
                  });
                }}
              >
                <label className="flex items-center gap-2">
                  Add an Ollama model by name
                  <input
                    className="field w-56"
                    placeholder="for example gemma3:12b"
                    value={tag}
                    onChange={(e) => setTag(e.target.value)}
                  />
                </label>
                <button type="submit" className="btn-secondary btn-sm" disabled={!tag.trim()}>
                  Add
                </button>
                <span className="text-xs text-muted">Found on ollama.com. LocalDub has not tested it for Slovak.</span>
              </form>
            )}
          </section>
        );
      })}

      {data.catalog_version && (
        <p className="text-xs text-muted">
          Model list version {data.catalog_version}. New models arrive with program updates; nothing is checked
          online until you press “Check for updates”.
        </p>
      )}
    </div>
  );
}
