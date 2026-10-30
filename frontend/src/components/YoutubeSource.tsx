import { useEffect, useRef, useState } from "react";
import { api, type YoutubeChoice, type YoutubeInfo, type YoutubeStatus } from "../api";
import { formatTime } from "../lib/format";
import { InstallNotice } from "./InstallNotice";

const QUALITY_LABELS: Record<string, string> = {
  auto: "Automatic (up to 1080p)",
  "720": "720p",
  "1080": "1080p",
  "1440": "1440p",
  "2160": "2160p (4K)",
};
const BROWSER_LABELS: Record<string, string> = {
  none: "Do not use cookies",
  edge: "Microsoft Edge",
  chrome: "Google Chrome",
  firefox: "Mozilla Firefox",
};
const field = "field";

interface Props {
  /** The checked link and its options, or null while there is nothing valid to download. */
  onChoice: (choice: YoutubeChoice | null) => void;
  disabled?: boolean;
}

const TOOLS_INTRO = (size: string) =>
  `Importing from YouTube needs two small programs, yt-dlp and Deno (about ${size}). They are downloaded from their official GitHub pages and checked against the publishers' SHA-256.`;

export function YoutubeSource({ onChoice, disabled }: Props) {
  const [status, setStatus] = useState<YoutubeStatus | null>(null);
  const [url, setUrl] = useState("");
  const [quality, setQuality] = useState("auto");
  const [cookies, setCookies] = useState("none");
  const [info, setInfo] = useState<YoutubeInfo | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [updating, setUpdating] = useState(false);
  const [updateMessage, setUpdateMessage] = useState<string | null>(null);

  const loadStatus = () => {
    api.youtubeStatus().then(setStatus).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  };
  useEffect(loadStatus, []);

  // Every check gets a number; an answer that arrives after the link changed is ignored.
  const latest = useRef(0);

  const reset = () => {
    latest.current++;
    setChecking(false);
    setInfo(null);
    setError(null);
    onChoice(null);
  };

  async function check() {
    const link = url.trim();
    if (!link) return;
    const mine = ++latest.current;
    setChecking(true);
    setError(null);
    onChoice(null);
    try {
      const found = await api.youtubeInfo(link, cookies);
      if (mine !== latest.current) return; // the link was edited while YouTube was answering
      if (found.is_live) {
        setInfo(null);
        setError("Live streams cannot be dubbed. Use a finished video.");
        return;
      }
      setInfo(found);
      onChoice({ url: link, quality, cookies_browser: cookies, info: found });
    } catch (e) {
      if (mine !== latest.current) return;
      setInfo(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mine === latest.current) setChecking(false);
    }
  }

  async function update() {
    setUpdating(true);
    setUpdateMessage(null);
    try {
      const r = await api.updateYtdlp();
      setUpdateMessage(r.message.split("\n").filter((l) => l.trim()).pop() ?? "Updated.");
      loadStatus();
    } catch (e) {
      setUpdateMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setUpdating(false);
    }
  }

  if (!status) return <p className="text-sm text-muted">Checking the YouTube tools…</p>;

  if (!status.installed) {
    return (
      <div className="rounded-lg border border-line p-4">
        <h3 className="mb-1 font-medium">One-time setup for YouTube links</h3>
        <InstallNotice ids={["youtube"]} intro={TOOLS_INTRO} onInstalled={loadStatus} />
        {error && <p className="mt-2 text-sm text-bad" role="alert">{error}</p>}
      </div>
    );
  }

  return (
    <fieldset disabled={disabled} className="space-y-3">
      <label className="block text-sm">
        <span className="mb-1 block font-medium">YouTube link</span>
        <div className="flex gap-2">
          <input
            type="url"
            inputMode="url"
            placeholder="https://www.youtube.com/watch?v=…"
            value={url}
            onChange={(e) => {
              setUrl(e.target.value);
              if (info || error || checking) reset();
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void check();
              }
            }}
            className={field}
            aria-label="YouTube link"
          />
          <button
            type="button"
            onClick={() => void check()}
            disabled={!url.trim() || checking}
            className="btn-secondary shrink-0"
          >
            {checking ? "Checking…" : "Check link"}
          </button>
        </div>
      </label>

      {error && (
        <p className="alert alert-bad" role="alert">
          {error}
        </p>
      )}

      {info && (
        <div className="flex gap-3 rounded-lg border border-emerald-300 bg-emerald-50 p-3" data-testid="youtube-card">
          {info.thumbnail && (
            <img src={info.thumbnail} alt="" referrerPolicy="no-referrer" loading="lazy" className="h-20 w-36 shrink-0 rounded-md bg-inset object-cover" />
          )}
          <div className="min-w-0 text-sm">
            <p className="line-clamp-2 font-medium">{info.title}</p>
            <p className="text-muted">
              {[info.uploader, info.duration ? formatTime(info.duration) : null].filter(Boolean).join(" · ")}
            </p>
            <p className="mt-1 text-xs text-ok">✓ The link works.</p>
          </div>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          <span className="mb-1 block font-medium">Video quality</span>
          <select
            className={field}
            value={quality}
            onChange={(e) => {
              setQuality(e.target.value);
              if (info) onChoice({ url: url.trim(), quality: e.target.value, cookies_browser: cookies, info });
            }}
          >
            {status.qualities.map((q) => (
              <option key={q} value={q}>
                {QUALITY_LABELS[q] ?? q}
              </option>
            ))}
          </select>
          <span className="mt-1 block text-xs text-muted">Dubbing does not need more than 1080p.</span>
        </label>
        <details className="text-sm">
          <summary className="cursor-pointer font-medium">Age-restricted or members-only video?</summary>
          <label className="mt-2 block">
            <span className="mb-1 block">Use cookies from</span>
            <select
              className={field}
              value={cookies}
              onChange={(e) => {
                setCookies(e.target.value);
                reset();
              }}
            >
              {status.browsers.map((b) => (
                <option key={b} value={b}>
                  {BROWSER_LABELS[b] ?? b}
                </option>
              ))}
            </select>
          </label>
          <p className="mt-1 text-xs text-muted">
            yt-dlp reads your own browser's sign-in on this computer. The cookies are not stored or sent anywhere else.
          </p>
        </details>
      </div>

      <p className="text-xs text-muted">
        Only use videos you have the right to download and dub. Downloading can be against YouTube's terms of service.
      </p>
      <p className="flex flex-wrap items-center gap-2 text-xs text-muted">
        yt-dlp {status.yt_dlp.version ?? "?"}
        <button type="button" onClick={() => void update()} disabled={updating} className="underline disabled:opacity-50">
          {updating ? "Updating…" : "Update yt-dlp"}
        </button>
        {updateMessage && <span role="status">{updateMessage}</span>}
        <span>(if downloads suddenly stop working, updating usually fixes it)</span>
      </p>
    </fieldset>
  );
}
