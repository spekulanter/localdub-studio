import type { Project } from "../api";
import { formatTime, statusLabel } from "../lib/format";

interface Props {
  projects: Project[];
  selected: number | "new" | "models";
  onSelect: (id: number) => void;
  onNew: () => void;
}

const DOT: Record<string, string> = {
  done: "bg-emerald-500",
  running: "bg-sky-500 animate-pulse",
  queued: "bg-sky-300",
  failed: "bg-red-500",
  cancelled: "bg-slate-400",
};

export function ProjectList({ projects, selected, onSelect, onNew }: Props) {
  return (
    <nav aria-label="Projects">
      <button
        onClick={onNew}
        className={`mb-2 w-full rounded-md px-3 py-2 text-sm font-medium ${
          selected === "new"
            ? "bg-indigo-600 text-white"
            : "bg-indigo-100 text-indigo-900 hover:bg-indigo-200 dark:bg-indigo-950 dark:text-indigo-100"
        }`}
      >
        + New dub
      </button>
      <ul className="space-y-1">
        {projects.map((p) => (
          <li key={p.id}>
            <button
              onClick={() => onSelect(p.id)}
              aria-current={selected === p.id}
              className={`w-full rounded-md border px-3 py-2 text-left text-sm ${
                selected === p.id
                  ? "border-indigo-500 bg-white dark:bg-slate-900"
                  : "border-transparent hover:bg-slate-100 dark:hover:bg-slate-900"
              }`}
            >
              <span className="block truncate font-medium">{p.name}</span>
              <span className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                <span className={`inline-block size-2 rounded-full ${DOT[p.latest_job?.status ?? ""] ?? "bg-slate-300"}`} />
                {statusLabel(p.latest_job)} · {formatTime(p.duration)}
              </span>
            </button>
          </li>
        ))}
        {projects.length === 0 && <li className="px-1 text-xs text-slate-500">No projects yet.</li>}
      </ul>
    </nav>
  );
}
