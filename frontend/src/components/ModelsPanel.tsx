import { useEffect, useState } from "react";
import type { ModelInfo, ModelRole, ModelsResponse } from "../api";
import { api } from "../api";
import { useT } from "../i18n";
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

/** On an Apple Silicon Mac the GPU has no card of its own: say "Mac" and "memory". */
const FIT_LABEL_MAC: Record<string, string> = {
  ok: "Fits your Mac",
  partial: "Only partly fits your Mac",
  too_big: "Too big for your Mac",
  no_gpu: "No Apple Silicon chip found",
};

const FIT_LABEL: Record<string, string> = {
  ok: "Fits your graphics card",
  cpu: "Runs on the processor",
  partial: "Only partly fits your card",
  too_big: "Too big for your card",
  no_gpu: "No NVIDIA card found",
};

function Progress({ m }: { m: ModelInfo }) {
  const t = useT();
  const d = m.download;
  if (d?.status === "cancelled") return <p className="mt-2 text-xs text-muted">{t("Download cancelled. Nothing was kept.")}</p>;
  if (!d || (d.status !== "queued" && d.status !== "running" && d.status !== "error")) return null;
  const pct = percent(d.done, d.total);
  return (
    <div className="mt-2">
      <div
        role="progressbar"
        aria-label={t("Download of {name}", { name: m.title })}
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
            ? t("Waiting for the previous download…")
            : d.show_bytes === false
              ? `${pct}%`
              : `${pct}% · ${t("{a} of {b}", { a: formatBytes(d.done), b: formatBytes(d.total) })}`}
          {d.message && d.status === "running" ? ` · ${t(d.message)}` : ""}
        </p>
      )}
    </div>
  );
}

function Details({ m, mac }: { m: ModelInfo; mac: boolean }) {
  const t = useT();
  const r = m.requirements;
  return (
    <details className="mt-2 text-sm">
      <summary className="cursor-pointer text-muted">{t("Details: who it is for, what it needs")}</summary>
      <div className="mt-2 space-y-2">
        {m.choose_if.length > 0 && (
          <div>
            <p className="font-medium">{t("Choose it if")}</p>
            <ul className="list-disc pl-5 text-muted">
              {m.choose_if.map((t) => (
                <li key={t}>{t}</li>
              ))}
            </ul>
          </div>
        )}
        {m.avoid_if.length > 0 && (
          <div>
            <p className="font-medium">{t("Skip it if")}</p>
            <ul className="list-disc pl-5 text-muted">
              {m.avoid_if.map((t) => (
                <li key={t}>{t}</li>
              ))}
            </ul>
          </div>
        )}
        <p className="text-muted">
          <span className="font-medium text-ink">{t("Needs:")}</span>{" "}
          {t("about {size} download, {disk} GB on disk", { size: formatBytes(m.size_bytes), disk: r.disk_gb })}
          {r.vram_gb !== null
            ? `, ${t(mac ? "about {gb} GB of the Mac's memory" : "about {gb} GB of graphics memory", { gb: r.vram_gb })}`
            : `, ${t(mac ? "no extra memory" : "no graphics memory")}`}.
          {r.note ? ` ${r.note}` : ""}
          {r.needs_packages ? ` ${t("Needs the optional packages.")}` : ""}
        </p>
        <p className="text-muted">
          <span className="font-medium text-ink">{t("This computer:")}</span> {m.fits.text}
        </p>
        {m.languages && (
          <p className="text-muted">
            <span className="font-medium text-ink">{t("Languages:")}</span> {m.languages}
          </p>
        )}
        <p className="text-muted">
          <span className="font-medium text-ink">{t("Measured here:")}</span>{" "}
          {m.measured ?? t("Not measured yet. Treat the description as the maker's claim, not our result.")}
        </p>
        <p className="text-muted">
          <span className="font-medium text-ink">{t("Licence:")}</span>{" "}
          <a href={m.license.url} target="_blank" rel="noreferrer noopener" className="underline">
            {m.license.name}
          </a>
          {m.pinned ? ` · ${m.pinned}` : ""}
        </p>
        {m.installed && (m.locations.length > 0 || m.store_note) && (
          <p className="break-all font-mono text-xs text-muted">
            {m.locations.length > 0 ? m.locations.join("\n") : m.store_note}
            {m.size_on_disk !== null ? ` · ${t("{size} on disk", { size: formatBytes(m.size_on_disk) })}` : ""}
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
  const t = useT();
  const [confirming, setConfirming] = useState(false);
  const d = m.download;
  const active = d?.status === "queued" || d?.status === "running";
  const shared = m.store_note !== null;
  const mac = data.hardware?.gpu?.unified === true;
  const lastOfRequired =
    m.required && data.models.filter((x) => x.role === m.role && x.installed).length === 1;
  return (
    <li className="rounded-md border border-line p-3" data-testid={`model-${m.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium">{m.title}</p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {m.required && m.default ? (
              <span className="chip chip-accent" title={t("Dubbing needs one model for this step; this is the one the required download fetches.")}>
                {t("Required")}
              </span>
            ) : (
              <span className={`chip ${m.status === "recommended" ? "chip-ok" : m.status === "not_recommended" ? "chip-warn" : ""}`}>
                {t(STATUS_LABEL[m.status])}
              </span>
            )}
            {m.installed && <span className="chip chip-ok">{t("✓ installed")}</span>}
            {m.installed && m.size_on_disk !== null && <span className="chip">{formatBytes(m.size_on_disk)}</span>}
            {m.selected && role?.selectable && <span className="chip chip-ok">{t("In use for new dubs")}</span>}
            {m.update.available && <span className="chip chip-warn">{t("Update available")}</span>}
            <span className={FIT_CLASS[m.fits.level] ?? "chip"} title={m.fits.text}>
              {t((mac ? FIT_LABEL_MAC[m.fits.level] : undefined) ?? FIT_LABEL[m.fits.level] ?? m.fits.level)}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!m.installed && !m.available && !active && (
            <button disabled={active} className="btn-primary btn-sm" onClick={() => onAction(() => api.downloadModels(["packages", m.id]))}>
              {active ? t("Downloading…") : t("Download with the optional packages")}
            </button>
          )}
          {active && (
            <button
              className="btn-secondary btn-sm"
              disabled={d?.cancelling || d?.cancellable === false}
              title={d?.cancellable === false ? t("This step can no longer be cancelled") : undefined}
              onClick={() => onAction(() => api.cancelModel(m.id))}
            >
              {d?.cancelling ? t("Cancelling…") : t("Cancel")}
            </button>
          )}
          {!m.installed && m.available && !active && (
            <button disabled={active} className="btn-primary btn-sm" onClick={() => onAction(() => api.downloadModels([m.id]))}>
              {active ? t("Downloading…") : d?.status === "error" ? t("Try again") : t("Download ({size})", { size: formatBytes(m.size_bytes) })}
            </button>
          )}
          {m.installed && role?.selectable && !m.selected && (
            <button className="btn-secondary btn-sm" onClick={() => onAction(() => api.selectModel(m.id))}>
              {t("Use for new dubs")}
            </button>
          )}
          {m.installed && m.update.available && (
            <button disabled={active} className="btn-primary btn-sm" onClick={() => onAction(() => api.modelAction(m.id, "update"))}>
              {t("Update")}
            </button>
          )}
          {m.installed && m.can_open_folder && (
            <button className="btn-ghost btn-sm" onClick={() => onAction(() => api.openModelsFolder(m.id))}>
              {t("Open folder")}
            </button>
          )}
          {m.installed && (
            <button disabled={active} className="btn-ghost btn-sm" onClick={() => onAction(() => api.modelAction(m.id, "repair"))}>
              {t("Re-download")}
            </button>
          )}
          {m.installed && m.can_delete && !confirming && (
            <button disabled={active} className="btn-ghost btn-sm" onClick={() => setConfirming(true)}>
              {t("Delete")}
            </button>
          )}
        </div>
      </div>
      <p className="mt-2 text-sm text-muted">{m.summary}</p>
      {confirming && (
        <div className="alert mt-2 space-y-2 text-sm" role="alertdialog" aria-label={t("Delete {name}", { name: m.title })}>
          <p>
            {t("Delete")} <strong>{m.title}</strong> {t("from this computer? You can download it again later.")}
          </p>
          {shared && <p>{t("Ollama keeps its models for every program on this PC; other programs lose this model too.")}</p>}
          {lastOfRequired && <p>{t("It is the only one installed for this step, so dubbing will not work until you download one again.")}</p>}
          <div className="flex gap-2">
            <button
              className="btn-primary btn-sm"
              onClick={() => {
                setConfirming(false);
                onAction(() => api.deleteModel(m.id));
              }}
            >
              {t("Yes, delete")}
            </button>
            <button className="btn-ghost btn-sm" onClick={() => setConfirming(false)}>
              {t("Cancel")}
            </button>
          </div>
        </div>
      )}
      <Progress m={m} />
      <Details m={m} mac={mac} />
    </li>
  );
}

export function ModelsPanel({ data, onChanged, error }: Props) {
  const t = useT();
  const [message, setMessage] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [tag, setTag] = useState("");
  const [sizes, setSizes] = useState<ModelsResponse | null>(null);
  // measured automatically, again whenever the set of installed models or a download changes
  const installedKey = data ? data.models.filter((m) => m.installed).map((m) => m.id).join(",") + (data.busy ? "!" : "") : "";
  useEffect(() => {
    if (!data || data.busy) return;
    let alive = true;
    api.models(true).then((r) => alive && Array.isArray(r?.models) && setSizes(r)).catch(() => undefined);
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [installedKey]);
  if (!data) return <p className="text-muted">{t("Loading…")}</p>;
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
        `${t(res.checked === 1 ? "{n} installed model checked:" : "{n} installed models checked:", { n: res.checked })} ` +
          (res.updates.length > 0 ? t("{n} can be updated.", { n: res.updates.length }) : t("all up to date.")) +
          (failed > 0 ? ` ${t("{n} could not be checked (offline?).", { n: failed })}` : ""),
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
        <p className="eyebrow mb-1.5">{t("Setup")}</p>
        <h2 className="font-display text-[30px] font-semibold leading-tight">{t("AI models")}</h2>
        <p className="text-sm text-muted">
          {t("Everything runs on this computer. Models are downloaded once, you decide which ones, and you can update or delete them here. Dubbing needs one model for each of the three required steps.")}
        </p>
      </div>

      {hw && (
        <div className="rounded-md border border-line p-3 text-sm" aria-label={t("This computer")}>
          <p>
            <span className="font-medium">{t(hw.gpu?.unified ? "Chip:" : "Graphics card:")}</span>{" "}
            {hw.gpu
              ? hw.gpu.unified
                ? t("{name}, {gb} GB usable by the GPU", { name: hw.gpu.name, gb: hw.gpu.vram_gb })
                : `${hw.gpu.name}, ${hw.gpu.vram_gb} GB`
              : t("no NVIDIA card found (models run on the processor, slowly)")}
            {" · "}
            <span className="font-medium">{t("Memory:")}</span> {hw.ram_gb ?? "?"} GB
            {" · "}
            <span className="font-medium">{t("Free disk:")}</span> {formatBytes(hw.disk_free_bytes)}
          </p>
          {data.paths && (
            <p className="mt-1 break-all font-mono text-xs text-muted">{t("Models folder:")} {data.paths.models}</p>
          )}
          <div className="mt-2 flex flex-wrap gap-2">
            <button className="btn-secondary btn-sm" onClick={() => run(() => api.openModelsFolder())}>
              {t("Open models folder")}
            </button>
            <button className="btn-secondary btn-sm" onClick={checkUpdates}>
              {t("Check for updates")}
            </button>
            <button
              className="btn-ghost btn-sm"
              onClick={() => run(() => api.models(true), (r) => setSizes(r as ModelsResponse))}
            >
              {t("Measure disk usage again")}
            </button>
          </div>
          {sizes && (
            <p className="mt-1 text-xs text-muted">
              {t("All installed models together: {size}.", {
                size: formatBytes(view.models.reduce((a, m) => a + (m.installed ? (m.size_on_disk ?? 0) : 0), 0)),
              })}
              {typeof sizes.models_bytes === "number" &&
                ` ${t("Models folder in total: {size} (Ollama's own store is separate).", { size: formatBytes(sizes.models_bytes) })}`}
            </p>
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
          {data.busy ? t("Downloading…") : t("Download the required models ({size})", { size: formatBytes(total) })}
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
                {!role.required && <span className="chip">{t("optional")}</span>}
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
                  const added = tag.trim();
                  if (!added) return;
                  run(() => api.addOllamaModel(added), () => {
                    setTag("");
                    setMessage(t("Added {tag}. Download it from the list above.", { tag: added }));
                  });
                }}
              >
                <label className="flex items-center gap-2">
                  {t("Add an Ollama model by name")}
                  <input
                    className="field w-56"
                    placeholder={t("for example gemma3:12b")}
                    value={tag}
                    onChange={(e) => setTag(e.target.value)}
                  />
                </label>
                <button type="submit" className="btn-secondary btn-sm" disabled={!tag.trim()}>
                  {t("Add")}
                </button>
                <span className="text-xs text-muted">{t("Found on ollama.com. LocalDub has not tested it for Slovak.")}</span>
              </form>
            )}
          </section>
        );
      })}

      {data.catalog_version && (
        <p className="text-xs text-muted">
          {t("Model list version {v}. New models arrive with program updates; nothing is checked online until you press “Check for updates”.", { v: data.catalog_version })}
        </p>
      )}
    </div>
  );
}
