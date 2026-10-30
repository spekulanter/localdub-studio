import { Clapperboard, Link2 } from "lucide-react";
import type { Project } from "../api";
import { formatTime, statusLabel } from "../lib/format";

interface Props {
  projects: Project[];
  selected: number | "new" | "models";
  onSelect: (id: number) => void;
}

const DOT: Record<string, string> = {
  done: "bg-ok",
  running: "bg-accent animate-pulse",
  queued: "bg-warn",
  failed: "bg-bad",
  cancelled: "bg-line-strong",
};

export function ProjectList({ projects, selected, onSelect }: Props) {
  return (
    <nav aria-label="Projects" className="min-h-0">
      <p className="eyebrow mb-2 px-3">Projects</p>
      <ul className="space-y-0.5">
        {projects.map((p) => {
          const active = selected === p.id;
          return (
            <li key={p.id}>
              <button
                onClick={() => onSelect(p.id)}
                aria-current={active}
                className={`group relative w-full rounded-[10px] px-3 py-2 text-left transition-colors ${
                  active ? "bg-accent-soft" : "hover:bg-inset"
                }`}
              >
                {active && <span className="absolute inset-y-2 left-0 w-[3px] rounded-full bg-accent" />}
                <span className="block truncate text-sm font-medium">{p.name}</span>
                <span className="mt-0.5 flex items-center gap-1.5 font-mono text-[11px] text-muted">
                  <span className={`inline-block size-1.5 shrink-0 rounded-full ${DOT[p.latest_job?.status ?? ""] ?? "bg-line-strong"}`} />
                  {p.source_url && <Link2 className="size-3 shrink-0" aria-label="from YouTube" />}
                  <span className="truncate">
                    {statusLabel(p.latest_job)}
                    {p.duration > 0 ? ` · ${formatTime(p.duration)}` : ""}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      {projects.length === 0 && (
        <div className="mx-1 mt-1 rounded-xl border border-dashed border-line-strong px-4 py-6 text-center text-xs text-muted">
          <Clapperboard className="mx-auto mb-2 size-5 opacity-60" />
          No dubs yet. Start one with the button above.
        </div>
      )}
    </nav>
  );
}
