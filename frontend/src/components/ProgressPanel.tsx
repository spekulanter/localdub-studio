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
    <section className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900" aria-label="Job progress">
      <div className="mb-2 flex items-center justify-between gap-3">
        <h3 className="font-medium">
          {statusLabel(job)}
          {job.status === "running" && job.message && <span className="ml-2 text-sm text-slate-500">{job.message}</span>}
          {job.attempts > 1 && active && <span className="ml-2 text-xs text-amber-600">resumed (attempt {job.attempts})</span>}
        </h3>
        {active ? (
          <button onClick={onCancel} disabled={busy} className="rounded-md border border-slate-300 px-3 py-1 text-sm hover:bg-slate-100 disabled:opacity-50 dark:border-slate-700 dark:hover:bg-slate-800">
            Cancel
          </button>
        ) : (
          (job.status === "failed" || job.status === "cancelled") && (
            <button onClick={onRetry} disabled={busy} className="rounded-md bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50">
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
        className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800"
      >
        <div
          className={`h-full transition-all ${job.status === "failed" ? "bg-red-500" : job.status === "done" ? "bg-emerald-500" : "bg-indigo-500"}`}
          style={{ width: `${job.status === "done" ? 100 : pct}%` }}
        />
      </div>
      <ol className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
        {order.map((s, i) => {
          const done = job.status === "done" || i < current;
          const now = job.status === "running" && i === current;
          return (
            <li key={s} className={now ? "font-semibold text-indigo-600 dark:text-indigo-300" : done ? "text-emerald-600 dark:text-emerald-400" : ""}>
              {done ? "✓ " : now ? "▸ " : "○ "}
              {STAGE_LABELS[s]}
            </li>
          );
        })}
      </ol>
      {job.status === "failed" && (
        <div className="mt-3 space-y-2" role="alert">
          <p className="rounded-md bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">{job.error ?? "The job failed."}</p>
          <div className="flex flex-wrap gap-2">
            <button onClick={() => void copy(job.error ?? "")} className="rounded-md border border-slate-300 px-3 py-1 text-sm dark:border-slate-700">
              Copy error
            </button>
            <button onClick={() => void copyFullLog()} className="rounded-md border border-slate-300 px-3 py-1 text-sm dark:border-slate-700">
              Copy full log
            </button>
            <a href={api.jobLogUrl(job.id)} download={`localdub-job-${job.id}.log`} className="rounded-md border border-slate-300 px-3 py-1 text-sm dark:border-slate-700">
              Download log
            </a>
            {copied && <span className="self-center text-xs text-emerald-600" role="status">{copied}</span>}
          </div>
          {log && log.length > 0 && (
            <details>
              <summary className="cursor-pointer text-xs text-slate-500">Show the last log lines</summary>
              <pre className="mt-1 max-h-48 overflow-auto rounded bg-slate-100 p-2 text-xs dark:bg-slate-800">{log.join("\n")}</pre>
            </details>
          )}
        </div>
      )}
    </section>
  );
}
