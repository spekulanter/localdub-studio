import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Health, type ModelsResponse, type Options, type Project } from "./api";
import { Cpu, Plus } from "lucide-react";
import { Logo } from "./components/Logo";
import { ModelsPanel } from "./components/ModelsPanel";
import { NewProject } from "./components/NewProject";
import { ProjectList } from "./components/ProjectList";
import { ProjectView } from "./components/ProjectView";
import { LANGS, useI18n, type Lang } from "./i18n";
import { useTheme, type ThemePref } from "./i18n/theme";

type Selection = number | "new" | "models";

function selectionFromHash(hash: string): Selection {
  const m = /^#\/project\/(\d+)$/.exec(hash);
  if (hash === "#/models") return "models";
  return m?.[1] ? Number(m[1]) : "new";
}

export default function App() {
  const { t, lang, setLang } = useI18n();
  const { pref: theme, setPref: setTheme } = useTheme();
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
  }, [refreshProjects, refreshHealth, refreshModels, lang]);

  // Poll while a download runs so the progress bars move.
  const downloading = models?.busy ?? false;
  // The pickers in the dub forms list which models are downloaded: reload them when a download ends and
  // whenever another page is opened, so "(not downloaded)" never outlives the download.
  const wasDownloading = useRef(false);
  useEffect(() => {
    if (wasDownloading.current && !downloading) refreshOptions();
    wasDownloading.current = downloading;
  }, [downloading, refreshOptions]);
  useEffect(() => {
    refreshOptions();
  }, [selected, refreshOptions]);
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

  const [startingOllama, setStartingOllama] = useState(false);
  const ollamaOk = health?.ollama.reachable ?? false;
  const modelsNeeded = (models?.required_missing.length ?? 0) > 0;

  return (
    <div className="grid min-h-screen lg:grid-cols-[304px_minmax(0,1fr)]">
      <aside className="flex flex-col gap-5 border-b border-line bg-surface/70 p-5 backdrop-blur lg:sticky lg:top-0 lg:h-screen lg:overflow-y-auto lg:border-b-0 lg:border-r">
        <header className="flex items-center gap-3">
          <Logo size={40} />
          <div className="leading-tight">
            <h1 className="font-display text-[22px] font-semibold">LocalDub</h1>
            <p className="eyebrow">Studio</p>
          </div>
        </header>
        <p className="-mt-2 text-[13px] leading-snug text-muted">{t("English → Slovak dubbing. Everything runs on this computer.")}</p>

        <div className="space-y-1.5">
          <button onClick={() => setSelected("new")} className={`${selected === "new" ? "btn-primary" : "btn-secondary"} w-full justify-start`}>
            <Plus className="size-4" /> {t("New dub")}
          </button>
          <button
            onClick={() => setSelected("models")}
            aria-current={selected === "models"}
            className={`${selected === "models" ? "btn-primary" : "btn-ghost"} w-full justify-start`}
          >
            <Cpu className="size-4" /> {t("AI models")}
            {modelsNeeded && (
              <span className="chip chip-warn ml-auto">{models?.busy ? t("downloading…") : t("download needed")}</span>
            )}
          </button>
        </div>

        <ProjectList projects={projects} selected={selected} onSelect={setSelected} />

        <div
          className={`mt-auto flex items-center gap-2 rounded-[10px] border px-3 py-2 text-xs ${
            health === null ? "border-line text-muted" : ollamaOk ? "border-ok/30 bg-ok-soft text-ok" : "border-warn/40 bg-warn-soft text-warn"
          }`}
          role="status"
        >
          <span className={`size-2 shrink-0 rounded-full ${health === null ? "bg-line-strong" : ollamaOk ? "bg-ok" : "bg-warn"}`} />
          <span className="min-w-0 flex-1">
            {health === null
              ? t("Cannot reach the LocalDub server.")
              : ollamaOk
                ? t("Ollama connected · {n} models", { n: health.ollama.models.length })
                : health.ollama.installed === false
                  ? t("Ollama is not installed. Install it on the AI models page: one click.")
                  : t("Ollama is not running. Translation will fail until you start it.")}
          </span>
          {health !== null && !ollamaOk && health.ollama.installed !== false && (
            <button
              className="underline underline-offset-2"
              disabled={startingOllama}
              onClick={() => {
                setStartingOllama(true);
                api.startOllama().catch(() => undefined).finally(() => {
                  setStartingOllama(false);
                  refreshHealth();
                });
              }}
            >
              {startingOllama ? t("starting…") : t("Start Ollama")}
            </button>
          )}
          <button className="underline underline-offset-2" onClick={refreshHealth}>
            {t("recheck")}
          </button>
        </div>
        <label className="flex items-center gap-2 text-xs text-muted">
          {t("Language")}
          <select
            className="field !w-auto !py-1 text-xs"
            value={lang}
            onChange={(e) => setLang(e.target.value as Lang)}
            aria-label={t("Language")}
          >
            {LANGS.map((l) => (
              <option key={l.id} value={l.id}>
                {l.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-xs text-muted">
          {t("Theme")}
          <select
            className="field !w-auto !py-1 text-xs"
            value={theme}
            onChange={(e) => setTheme(e.target.value as ThemePref)}
            aria-label={t("Theme")}
          >
            <option value="system">{t("Automatic")}</option>
            <option value="light">{t("Light")}</option>
            <option value="dark">{t("Dark")}</option>
          </select>
        </label>
      </aside>

      <main className="min-w-0 px-5 py-7 lg:px-10">
        <div className="mx-auto max-w-5xl space-y-5">
          {loadError && (
            <p className="alert alert-bad" role="alert">
              {loadError}
            </p>
          )}
          {modelsNeeded && selected !== "models" && (
            <div className="alert alert-warn flex flex-wrap items-center justify-between gap-3" role="status">
              <span>
                {models?.busy
                  ? t("Downloading the AI models… dubbing starts when they are ready.")
                  : t("The AI models are not downloaded yet. They are needed before the first dub.")}
              </span>
              <button onClick={() => setSelected("models")} className="btn-primary btn-sm">
                {models?.busy ? t("Show progress") : t("Download models")}
              </button>
            </div>
          )}
          <div key={String(selected)} className="rise">
            {options === null ? (
              <p className="text-muted">{t("Loading…")}</p>
            ) : selected === "models" ? (
              <ModelsPanel data={models} onChanged={refreshModels} />
            ) : selected === "new" ? (
              <NewProject
                options={options}
                health={health}
                modelsMissing={modelsNeeded}
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
          </div>
        </div>
      </main>
    </div>
  );
}
