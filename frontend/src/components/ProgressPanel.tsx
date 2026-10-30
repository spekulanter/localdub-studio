import { useEffect, useState } from "react";
import { api, type Job, type Stage } from "../api";
import { STAGE_LABELS, statusLabel } from "../lib/format";

const ORDER: Stage[] = ["download", "probe", "extract", "asr", "diarize", "translate", "tts", "separate", "convert", "assemble", "export"];

interface Props {
  job: Job;
  /** The video comes from a link, so downloading is the first step. */
  hasDownload?: boolean;
  onCancel: () => void;
  onRetry: () => void;
  busy: boolean;
}

export function ProgressPanel({ job, onCancel, onRetry, busy, hasDownload = false }: Props) {
  const order = hasDownload ? ORDER : ORDER.filter((s) => s !== "download");
  const active = job.status === "queued" || job.status === "running";
  const pct = Math.round(job.progress * 100);
  const current = job.stage === "" ? -1 : order.indexOf(job.stage);
  const [log, setLog] = useState<string[] | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied("Copied");
    } catch {
      setCopied("Could not copy: use Download log");
    }
    window.setTimeout(() => setCopied(null), 3000);
  }
  const copyFullLog = async () => copy(`${job.error ?? ""}\n\n${await api.jobLogFull(job.id)}`);

  useEffect(() => {
    if (job.status !== "failed") {
      setLog(null);
      return;
    }
    api.jobLog(job.id, 25).then((r) => setLog(r.lines)).catch(() => setLog(null));
  }, [job.id, job.status]);

  return (
    <section className="card" aria-label="Job progress">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="font-display text-xl font-semibold">
          {statusLabel(job)}
          {job.status === "running" && job.message && <span className="ml-3 font-mono text-xs font-normal text-muted">{job.message}</span>}
          {job.attempts > 1 && active && <span className="ml-2 text-xs text-warn">resumed (attempt {job.attempts})</span>}
        </h3>
        {active ? (
          <button onClick={onCancel} disabled={busy} className="btn-secondary btn-sm">
            Cancel
          </button>
        ) : (
          (job.status === "failed" || job.status === "cancelled") && (
            <button onClick={onRetry} disabled={busy} className="btn-primary btn-sm">
              {job.status === "failed" ? "Retry (keeps finished steps)" : "Resume"}
            </button>
          )
        )}
      </div>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        className="meter"
      >
        <span
          data-state={job.status === "failed" ? "failed" : job.status === "done" ? "done" : undefined}
          data-live={job.status === "running"}
          style={{ width: `${job.status === "done" ? 100 : pct}%` }}
        />
      </div>
      <ol className="mt-4 flex flex-wrap gap-1.5 text-xs">
        {order.map((s, i) => {
          const done = job.status === "done" || i < current;
          const now = job.status === "running" && i === current;
          return (
            <li
              key={s}
              className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 ${
                now ? "bg-accent-soft font-medium text-accent" : done ? "text-ok" : "text-muted"
              }`}
            >
              <span className={`size-1.5 rounded-full ${now ? "animate-pulse bg-accent" : done ? "bg-ok" : "bg-line-strong"}`} />
              {STAGE_LABELS[s]}
            </li>
          );
        })}
      </ol>
      {job.status === "failed" && (
        <div className="mt-3 space-y-2" role="alert">
          <p className="alert alert-bad">{job.error ?? "The job failed."}</p>
          <div className="flex flex-wrap gap-2">
            <button onClick={() => void copy(job.error ?? "")} className="btn-secondary btn-sm">
              Copy error
            </button>
            <button onClick={() => void copyFullLog()} className="btn-secondary btn-sm">
              Copy full log
            </button>
            <a href={api.jobLogUrl(job.id)} download={`localdub-job-${job.id}.log`} className="btn-secondary btn-sm">
              Download log
            </a>
            {copied && <span className="self-center text-xs text-ok" role="status">{copied}</span>}
          </div>
          {log && log.length > 0 && (
            <details>
              <summary className="cursor-pointer text-xs text-muted">Show the last log lines</summary>
              <pre className="mt-1 max-h-48 overflow-auto rounded bg-inset p-2 text-xs">{log.join("\n")}</pre>
            </details>
          )}
        </div>
      )}
    </section>
  );
}
