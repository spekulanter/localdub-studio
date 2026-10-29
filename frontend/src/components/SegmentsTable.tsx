import type { SegmentsResponse } from "../api";
import { formatTime } from "../lib/format";

const FIT: Record<string, { label: string; cls: string; hint: string }> = {
  ok: { label: "fits", cls: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200", hint: "Fits its time slot." },
  stretched: { label: "sped up", cls: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200", hint: "Spoken slightly faster to fit." },
  shifted: { label: "shifted", cls: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200", hint: "Starts a little late so lines do not overlap." },
  overflow: { label: "too long", cls: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200", hint: "Translation is too long for the slot; the dub lags the speaker." },
};

export function SegmentsTable({ data }: { data: SegmentsResponse | null }) {
  if (!data || data.segments.length === 0) {
    return <p className="text-sm text-slate-500">Segments appear here once speech has been recognised.</p>;
  }
  const flagged = data.segments.filter((s) => s.fit_status === "overflow" || s.fit_status === "shifted").length;
  return (
    <div>
      <p className="mb-2 text-xs text-slate-500 dark:text-slate-400">
        {data.segments.length} segments{flagged > 0 && ` · ${flagged} where timing is tight`}. Editing is planned for the next milestone.
      </p>
      <div className="max-h-[28rem] overflow-auto rounded-md border border-slate-200 dark:border-slate-800">
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 bg-slate-100 text-xs uppercase text-slate-500 dark:bg-slate-800">
            <tr>
              <th className="px-3 py-2">Time</th>
              <th className="px-3 py-2">English</th>
              <th className="px-3 py-2">Slovak</th>
              <th className="px-3 py-2">Timing</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
            {data.segments.map((s) => {
              const fit = s.fit_status ? FIT[s.fit_status] : undefined;
              return (
                <tr key={s.id} className="align-top">
                  <td className="whitespace-nowrap px-3 py-2 tabular-nums text-slate-500">
                    {formatTime(s.start)}–{formatTime(s.end)}
                  </td>
                  <td className="px-3 py-2">{s.source_text}</td>
                  <td className="px-3 py-2">{s.translated_text || <span className="text-slate-400">…</span>}</td>
                  <td className="px-3 py-2">
                    {fit && (
                      <span title={fit.hint} className={`rounded px-1.5 py-0.5 text-xs ${fit.cls}`}>
                        {fit.label}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
