import { useEffect, useState } from "react";
import { api, type UpdateInfo } from "../api";
import { useT } from "../i18n";
import { formatBytes, percent } from "../lib/bytes";

const DISMISSED = "localdub.update.dismissed";

function dismissedVersion(): string | null {
  try {
    return localStorage.getItem(DISMISSED);
  } catch {
    return null;
  }
}

/** Offers a newer normal release (never a pre-release), downloads it and starts its installer. */
export function UpdateBanner({ enabled }: { enabled: boolean }) {
  const t = useT();
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [hidden, setHidden] = useState<string | null>(dismissedVersion);
  const [problem, setProblem] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [closing, setClosing] = useState(false);
  const status = info?.download.status;

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    api.update().then((r) => alive && setInfo(r)).catch(() => undefined); // offline is not worth a message
    return () => {
      alive = false;
    };
  }, [enabled]);

  useEffect(() => {
    if (status !== "running") return;
    const id = window.setInterval(() => {
      api.update().then(setInfo).catch(() => undefined);
    }, 700);
    return () => window.clearInterval(id);
  }, [status]);

  if (!enabled || info === null || !info.available || info.version === hidden) return null;

  const later = () => {
    try {
      localStorage.setItem(DISMISSED, info.version ?? "");
    } catch {
      /* the banner just comes back next time */
    }
    setHidden(info.version);
  };
  const start = () => {
    setProblem(null);
    api.startUpdateDownload().then(setInfo).catch((e: unknown) => setProblem(e instanceof Error ? e.message : String(e)));
  };
  const install = (force: boolean) => {
    setProblem(null);
    api
      .installUpdate(force)
      .then(() => setClosing(true))
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : String(e);
        if (!force && /job is running/i.test(msg)) setAsking(true);
        else setProblem(msg);
      });
  };

  return (
    <div className="alert flex flex-wrap items-center justify-between gap-3" role="status" data-testid="update-banner">
      <div className="min-w-0 flex-1 space-y-1">
        <p className="font-medium">
          {t("Version {v} is available (you have {c}).", { v: info.version ?? "", c: info.current })}
        </p>
        {status === "running" && (
          <p className="text-sm text-muted">
            {t("Downloading… {pct}% of {size}", { pct: percent(info.download.done, info.download.total), size: formatBytes(info.download.total) })}
          </p>
        )}
        {status === "ready" && !closing && (
          <p className="text-sm text-muted">{t("Downloaded and checked. The program will close and the installer will open (on a Mac: a disk image to drag into Applications).")}</p>
        )}
        {closing && <p className="text-sm text-muted">{t("Closing so the update can be installed…")}</p>}
        {asking && <p className="text-sm text-warn">{t("A dubbing job is running or waiting. It is paused and continues after the update.")}</p>}
        {(problem || info.download.error) && (
          <p className="text-sm text-bad" role="alert">
            {problem ?? info.download.error}
          </p>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {info.page && (
          <a href={info.page} target="_blank" rel="noreferrer noopener" className="btn-ghost btn-sm">
            {t("What's new")}
          </a>
        )}
        {(status === "idle" || status === "error") && (
          <button className="btn-primary btn-sm" onClick={start}>
            {t("Download and update ({size})", { size: formatBytes(info.size ?? 0) })}
          </button>
        )}
        {status === "ready" && !closing && (
          <button className="btn-primary btn-sm" onClick={() => install(asking)}>
            {asking ? t("Install anyway") : t("Install now")}
          </button>
        )}
        {!closing && status !== "running" && (
          <button className="btn-ghost btn-sm" onClick={later}>
            {t("Later")}
          </button>
        )}
      </div>
    </div>
  );
}
