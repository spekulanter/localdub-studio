import { useEffect, useRef, useState } from "react";
import { api, type YoutubeChoice, type YoutubeInfo, type YoutubeStatus } from "../api";
import { useT } from "../i18n";
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
  /** The checked links and their options (only the ones that work); empty while there is nothing to download. */
  onChoice: (choices: YoutubeChoice[]) => void;
  disabled?: boolean;
}

const MAX_LINKS = 50;

interface Item {
  url: string;
  info?: YoutubeInfo;
  error?: string;
}

export function YoutubeSource({ onChoice, disabled }: Props) {
  const t = useT();
  const toolsIntro = (size: string) =>
    t("Importing from YouTube needs two small programs, yt-dlp and Deno (about {size}). They are downloaded from their official GitHub pages and checked against the publishers' SHA-256.", { size });
  const [status, setStatus] = useState<YoutubeStatus | null>(null);
  const [text, setText] = useState("");
  const [quality, setQuality] = useState("auto");
  const [cookies, setCookies] = useState("none");
  const [items, setItems] = useState<Item[]>([]);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [updating, setUpdating] = useState(false);
  const [updateMessage, setUpdateMessage] = useState<string | null>(null);

  const loadStatus = () => {
    api.youtubeStatus().then(setStatus).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  };
  useEffect(loadStatus, []);

  // Every check gets a number; an answer that arrives after the links changed is ignored.
  const latest = useRef(0);

  const links = Array.from(new Set(text.split(/\s+/).filter(Boolean))).slice(0, MAX_LINKS);

  const choices = (list: Item[], q = quality, c = cookies): YoutubeChoice[] =>
    list.flatMap((i) => (i.info ? [{ url: i.url, quality: q, cookies_browser: c, info: i.info }] : []));

  const reset = () => {
    latest.current++;
    setChecking(false);
    setItems([]);
    setError(null);
    onChoice([]);
  };

  async function check() {
    if (links.length === 0) return;
    const mine = ++latest.current;
    setChecking(true);
    setError(null);
    setItems([]);
    onChoice([]);
    const found: Item[] = [];
    try {
      for (const link of links) {
        let item: Item;
        try {
          const info = await api.youtubeInfo(link, cookies);
          item = info.is_live ? { url: link, error: t("Live streams cannot be dubbed. Use a finished video.") } : { url: link, info };
        } catch (e) {
          item = { url: link, error: e instanceof Error ? e.message : String(e) };
        }
        if (mine !== latest.current) return; // the links were edited while YouTube was answering
        found.push(item);
        setItems([...found]);
      }
      onChoice(choices(found));
    } finally {
      if (mine === latest.current) setChecking(false);
    }
  }

  async function update() {
    setUpdating(true);
    setUpdateMessage(null);
    try {
      const r = await api.updateYtdlp();
      setUpdateMessage(r.message.split("\n").filter((l) => l.trim()).pop() ?? t("Updated."));
      loadStatus();
    } catch (e) {
      setUpdateMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setUpdating(false);
    }
  }

  if (!status) return <p className="text-sm text-muted">{t("Checking the YouTube tools…")}</p>;

  if (!status.installed) {
    return (
      <div className="rounded-lg border border-line p-4">
        <h3 className="mb-1 font-medium">{t("One-time setup for YouTube links")}</h3>
        <InstallNotice ids={["youtube"]} intro={toolsIntro} onInstalled={loadStatus} />
        {error && <p className="mt-2 text-sm text-bad" role="alert">{error}</p>}
      </div>
    );
  }

  return (
    <fieldset disabled={disabled} className="space-y-3">
      <label className="block text-sm">
        <span className="mb-1 block font-medium">{t("YouTube links (one per line)")}</span>
        <textarea
          rows={3}
          placeholder="https://www.youtube.com/watch?v=…"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            if (items.length > 0 || error || checking) reset();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              void check();
            }
          }}
          className={field}
          aria-label={t("YouTube links (one per line)")}
        />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => void check()} disabled={links.length === 0 || checking} className="btn-secondary shrink-0">
            {checking ? t("Checking…") : links.length > 1 ? t("Check links") : t("Check link")}
          </button>
          <span className="text-xs text-muted">
            {links.length > 1 ? t("{n} links; they are dubbed one after another.", { n: links.length }) : t("Paste several links to dub them all in turn (Ctrl + Enter checks).")}
          </span>
        </div>
      </label>

      {error && (
        <p className="alert alert-bad" role="alert">
          {error}
        </p>
      )}

      {items.length > 0 && (
        <ul className="space-y-2">
          {items.map((it) =>
            it.info ? (
              <li key={it.url} className="flex gap-3 rounded-lg border border-emerald-300 bg-emerald-50 p-3" data-testid="youtube-card">
                {it.info.thumbnail && (
                  <img src={it.info.thumbnail} alt="" referrerPolicy="no-referrer" loading="lazy" className="h-16 w-28 shrink-0 rounded-md bg-inset object-cover" />
                )}
                <div className="min-w-0 text-sm">
                  <p className="line-clamp-2 font-medium">{it.info.title}</p>
                  <p className="text-muted">
                    {[it.info.uploader, it.info.duration ? formatTime(it.info.duration) : null].filter(Boolean).join(" · ")}
                  </p>
                  <p className="mt-1 text-xs text-ok">{t("✓ The link works.")}</p>
                </div>
              </li>
            ) : (
              <li key={it.url} className="alert alert-bad" role="alert">
                <span className="break-all font-mono text-xs">{it.url}</span>
                <br />
                {it.error}
              </li>
            ),
          )}
        </ul>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          <span className="mb-1 block font-medium">{t("Video quality")}</span>
          <select
            className={field}
            value={quality}
            onChange={(e) => {
              setQuality(e.target.value);
              if (items.some((i) => i.info)) onChoice(choices(items, e.target.value));
            }}
          >
            {status.qualities.map((q) => (
              <option key={q} value={q}>
                {t(QUALITY_LABELS[q] ?? q)}
              </option>
            ))}
          </select>
          <span className="mt-1 block text-xs text-muted">{t("Dubbing does not need more than 1080p.")}</span>
        </label>
        <details className="text-sm">
          <summary className="cursor-pointer font-medium">{t("Age-restricted or members-only video?")}</summary>
          <label className="mt-2 block">
            <span className="mb-1 block">{t("Use cookies from")}</span>
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
                  {t(BROWSER_LABELS[b] ?? b)}
                </option>
              ))}
            </select>
          </label>
          <p className="mt-1 text-xs text-muted">
            {t("yt-dlp reads your own browser's sign-in on this computer. The cookies are not stored or sent anywhere else.")}
          </p>
        </details>
      </div>

      <p className="text-xs text-muted">
        {t("Only use videos you have the right to download and dub. Downloading can be against YouTube's terms of service.")}
      </p>
      <p className="flex flex-wrap items-center gap-2 text-xs text-muted">
        yt-dlp {status.yt_dlp.version ?? "?"}
        <button type="button" onClick={() => void update()} disabled={updating} className="underline disabled:opacity-50">
          {updating ? t("Updating…") : t("Update yt-dlp")}
        </button>
        {updateMessage && <span role="status">{updateMessage}</span>}
        <span>{t("(if downloads suddenly stop working, updating usually fixes it)")}</span>
      </p>
    </fieldset>
  );
}
