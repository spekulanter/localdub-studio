import { useEffect, useRef, useState } from "react";
import { api, type ModelsResponse } from "../api";
import { formatBytes, percent } from "../lib/bytes";
import { useT } from "../i18n";

interface Props {
  /** What to install, e.g. ["packages", "separation"] or ["youtube"]. */
  ids: string[];
  /** Explains what is downloaded; gets the size, e.g. "3.0 GB". */
  intro: (size: string) => string;
  /** Called once everything in `ids` is installed, so the page can unlock the feature. */
  onInstalled: () => void;
}

const BUSY = ["queued", "running"];

/** One-click installation of optional components (packages, tools, models) with progress. */
export function InstallNotice({ ids, onInstalled, intro }: Props) {
  const t = useT();
  const [data, setData] = useState<ModelsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const notified = useRef(false);

  const rows = (data?.models ?? []).filter((m) => ids.includes(m.id));
  const running = rows.some((m) => m.download && BUSY.includes(m.download.status));
  const failed = rows.find((m) => m.download?.status === "error");
  const allInstalled = rows.length > 0 && rows.every((m) => m.installed);

  const refresh = () => {
    api.models().then(setData).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  };

  useEffect(refresh, []);
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(refresh, 1000);
    return () => window.clearInterval(t);
  }, [running]);
  useEffect(() => {
    if (allInstalled && !notified.current) {
      notified.current = true;
      onInstalled();
    }
  }, [allInstalled, onInstalled]);

  const start = () => {
    setError(null);
    api
      .downloadModels(ids)
      .then(refresh)
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
        refresh();
      });
  };

  if (!data) return <p className="text-xs text-muted">{t("Checking…")}</p>;
  if (allInstalled) {
    return (
      <p className="text-xs text-ok" role="status">
        {t("✓ Installed. This option is ready to use.")}
      </p>
    );
  }

  const size = (m: (typeof rows)[number]) => m.download?.total || m.size_bytes;
  const total = rows.filter((m) => !m.installed).reduce((a, m) => a + size(m), 0);
  const done = rows.filter((m) => !m.installed).reduce((a, m) => a + (m.download?.done ?? 0), 0);
  const pct = percent(done, total);
  const current = rows.find((m) => m.download && BUSY.includes(m.download.status) && m.download.message);
  const problem = error ?? failed?.download?.error ?? null;

  return (
    <div className="mt-1 space-y-1 text-xs text-muted">
      {!running && (
        <p>
          {intro(formatBytes(total))}{" "}
          {t("It is installed into your own user folder; no administrator rights and no commands are needed.")}
        </p>
      )}
      {running && (
        <>
          <div
            role="progressbar"
            aria-label={t("Installing the optional packages")}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct}
            className="meter"
          >
            <span data-live="true" style={{ width: `${pct}%` }} />
          </div>
          <p>
            {pct}%
            {current?.download?.show_bytes === false ? "" : ` · ${t("{a} of {b}", { a: formatBytes(done), b: formatBytes(total) })}`}
            {current?.download?.message ? ` · ${current.download.message}` : ""}
          </p>
        </>
      )}
      {problem && (
        <p className="text-bad" role="alert">
          {problem}
        </p>
      )}
      {running && (
        <button
          type="button"
          className="btn-secondary btn-sm"
          disabled={rows.some((m) => m.download?.cancellable === false)}
          onClick={() => {
            const busyIds = rows.filter((m) => m.download && BUSY.includes(m.download.status)).map((m) => m.id);
            void Promise.all(busyIds.map((id) => api.cancelModel(id).catch(() => undefined))).then(refresh);
          }}
        >
          {t("Cancel")}
        </button>
      )}
      {!running && (
        <button
          type="button"
          onClick={start}
          className="btn-primary btn-sm"
        >
          {problem ? t("Try again") : t("Install now ({size})", { size: formatBytes(total) })}
        </button>
      )}
    </div>
  );
}
