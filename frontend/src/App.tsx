import { useCallback, useEffect, useState } from "react";
import { api, type Health, type ModelsResponse, type Options, type Project } from "./api";
import { ModelsPanel } from "./components/ModelsPanel";
import { NewProject } from "./components/NewProject";
import { ProjectList } from "./components/ProjectList";
import { ProjectView } from "./components/ProjectView";

type Selection = number | "new" | "models";

function selectionFromHash(hash: string): Selection {
  const m = /^#\/project\/(\d+)$/.exec(hash);
  if (hash === "#/models") return "models";
  return m?.[1] ? Number(m[1]) : "new";
}

export default function App() {
  const [options, setOptions] = useState<Options | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelectedState] = useState<Selection>(() => selectionFromHash(window.location.hash));
  const setSelected = useCallback((s: Selection) => {
    window.location.hash = s === "new" ? "" : s === "models" ? "/models" : `/project/${s}`;
    setSelectedState(s);
  }, []);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [models, setModels] = useState<ModelsResponse | null>(null);

  const refreshOptions = useCallback(() => {
    api.options().then(setOptions).catch(() => undefined);
  }, []);

  const refreshModels = useCallback(() => {
    api.models().then(setModels).catch(() => undefined);
  }, []);

  const refreshProjects = useCallback(async () => {
    try {
      setProjects(await api.projects());
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const refreshHealth = useCallback(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    api.options().then(setOptions).catch((e: unknown) => setLoadError(String(e)));
    void refreshProjects();
    refreshHealth();
    refreshModels();
  }, [refreshProjects, refreshHealth, refreshModels]);

  // Poll while a download runs so the progress bars move.
  const downloading = models?.busy ?? false;
  useEffect(() => {
    if (!downloading) return;
    const t = window.setInterval(refreshModels, 1000);
    return () => window.clearInterval(t);
  }, [downloading, refreshModels]);

  useEffect(() => {
    const onHash = () => setSelectedState(selectionFromHash(window.location.hash));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const ollamaOk = health?.ollama.reachable ?? false;

  return (
    <div className="mx-auto flex min-h-screen max-w-7xl flex-col gap-4 p-4 lg:flex-row">
      <aside className="w-full shrink-0 lg:w-72">
        <h1 className="text-xl font-semibold">LocalDub Studio</h1>
        <p className="mb-3 text-xs text-slate-500 dark:text-slate-400">
          English → Slovak dubbing. Everything runs on this computer.
        </p>
        <div
          className={`mb-3 rounded-md border px-3 py-2 text-xs ${
            health === null
              ? "border-slate-300 text-slate-500 dark:border-slate-700"
              : ollamaOk
                ? "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
                : "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200"
          }`}
          role="status"
        >
          {health === null
            ? "Cannot reach the LocalDub server."
            : ollamaOk
              ? `Ollama connected (${health.ollama.models.length} models)`
              : "Ollama is not running. Translation will fail until you start it."}
          <button className="ml-2 underline" onClick={refreshHealth}>
            recheck
          </button>
        </div>
        <button
          onClick={() => setSelected("models")}
          className={`mb-2 w-full rounded-md border px-3 py-2 text-left text-sm ${
            selected === "models" ? "border-indigo-500 bg-white dark:bg-slate-900" : "border-slate-300 dark:border-slate-700"
          }`}
        >
          AI models
          {models && models.required_missing.length > 0 && (
            <span className="ml-2 rounded bg-amber-100 px-1.5 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-200">
              {models.busy ? "downloading…" : "download needed"}
            </span>
          )}
        </button>
        <ProjectList
          projects={projects}
          selected={selected}
          onSelect={setSelected}
          onNew={() => setSelected("new")}
        />
      </aside>
      <main className="min-w-0 flex-1">
        {loadError && (
          <p className="mb-3 rounded-md bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950 dark:text-red-200" role="alert">
            {loadError}
          </p>
        )}
        {models && models.required_missing.length > 0 && selected !== "models" && (
          <div
            className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100"
            role="status"
          >
            <span>
              {models.busy
                ? "Downloading the AI models… dubbing starts when they are ready."
                : "The AI models are not downloaded yet. They are needed before the first dub."}
            </span>
            <button onClick={() => setSelected("models")} className="rounded-md bg-amber-600 px-3 py-1 text-white">
              {models.busy ? "Show progress" : "Download models"}
            </button>
          </div>
        )}
        {options === null ? (
          <p className="text-slate-500">Loading…</p>
        ) : selected === "models" ? (
          <ModelsPanel data={models} onChanged={refreshModels} />
        ) : selected === "new" ? (
          <NewProject
            options={options}
            health={health}
            modelsMissing={(models?.required_missing.length ?? 0) > 0}
            onOptionsChanged={refreshOptions}
            onCreated={(p) => {
              void refreshProjects();
              setSelected(p.id);
            }}
          />
        ) : (
          <ProjectView
            key={selected}
            projectId={selected}
            options={options}
            health={health}
            onChanged={refreshProjects}
            onOptionsChanged={refreshOptions}
            onDeleted={() => {
              void refreshProjects();
              setSelected("new");
            }}
          />
        )}
      </main>
    </div>
  );
}
