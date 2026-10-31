import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Options } from "../api";
import { OptionFields } from "../components/OptionFields";
import { ProjectList } from "../components/ProjectList";
import { ModelsPanel } from "../components/ModelsPanel";
import { mkModel, mkResponse } from "../testing/models";
import { I18nProvider, translate, useI18n } from "./index";
import { sk } from "./sk";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

const placeholders = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort().join(",");

describe("the Slovak dictionary", () => {
  it("keeps every {placeholder} of the English text", () => {
    for (const [en, local] of Object.entries(sk)) {
      expect(placeholders(local), en).toBe(placeholders(en));
    }
  });

  it("has no empty translations", () => {
    for (const [en, local] of Object.entries(sk)) expect(local.trim().length, en).toBeGreaterThan(0);
  });

  it("translates, substitutes variables and falls back to English", () => {
    expect(translate("sk", "Ollama connected · {n} models", { n: 3 })).toBe("Ollama pripojená · modelov: 3");
    expect(translate("sk", "Text that nobody translated")).toBe("Text that nobody translated");
    expect(translate("en", "{n} lines", { n: 2 })).toBe("2 lines");
  });
});

const options: Options = {
  voices: ["F1", "M1"],
  source_languages: { en: "English", auto: "Auto-detect" },
  target_language: "sk",
  default_voice: "F1",
  default_llm: "translategemma:4b",
  default_asr: "whisper-large-v3",
  asr_choices: [],
  translation_choices: [],
  stages: [],
  max_upload_mb: 1, default_max_upload_mb: 4096, free_disk_mb: 100000,
  separation_available: true,
};
const settings = {
  source_lang: "en", voice: "F1", llm_model: "translategemma:4b", asr_id: "whisper-large-v3",
  original_audio: "duck" as const, keep_original_track: true, diarize: false, clone_voice: false,
  clone_consent: false, num_speakers: null,
};

function Switcher() {
  const { setLang } = useI18n();
  return <button onClick={() => setLang("sk")}>to-sk</button>;
}

describe("the interface in Slovak", () => {
  it("renders Slovak when chosen, English otherwise", () => {
    const { unmount } = render(<ProjectList projects={[]} selected="new" onSelect={vi.fn()} />);
    expect(screen.getByText(/No dubs yet/)).toBeTruthy();
    unmount();
    render(
      <I18nProvider initial="sk">
        <ProjectList projects={[]} selected="new" onSelect={vi.fn()} />
      </I18nProvider>,
    );
    expect(screen.getByText(/Zatiaľ žiadne dabingy/)).toBeTruthy();
  });

  it("switches language live and remembers the choice", () => {
    render(
      <I18nProvider initial="en">
        <Switcher />
        <ProjectList projects={[]} selected="new" onSelect={vi.fn()} />
      </I18nProvider>,
    );
    expect(screen.getByText("Projects")).toBeTruthy();
    fireEvent.click(screen.getByText("to-sk"));
    expect(screen.getByText("Projekty")).toBeTruthy();
    expect(window.localStorage.getItem("localdub.lang")).toBe("sk");
    expect(document.documentElement.lang).toBe("sk");
  });

  it("translates the models library, including the delete confirmation", () => {
    const data = mkResponse([mkModel({ installed: true, can_delete: true, selected: true })], {
      roles: [{ id: "asr", title: "Rozpoznávanie reči", description: "x", required: true, selectable: true, selected_id: "whisper-large-v3" }],
    });
    render(
      <I18nProvider initial="sk">
        <ModelsPanel data={data} onChanged={vi.fn()} />
      </I18nProvider>,
    );
    expect(screen.getByText("Používa sa pre nové dabingy")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Zmazať" }));
    expect(screen.getByRole("button", { name: "Áno, zmazať" })).toBeTruthy();
  });
});

describe("voice samples", () => {
  const stubAudio = () => {
    const play = vi.fn().mockResolvedValue(undefined);
    class FakeAudio {
      play = play;
      pause = vi.fn();
      onended: (() => void) | null = null;
    }
    vi.stubGlobal("Audio", FakeAudio);
    vi.stubGlobal("URL", { ...URL, createObjectURL: () => "blob:x", revokeObjectURL: vi.fn() });
    return play;
  };

  it("plays a sample of the selected voice", async () => {
    const play = stubAudio();
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      urls.push(url);
      return new Response("RIFFdata");
    }));
    render(<OptionFields options={options} health={null} value={settings} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "▶ Listen" }));
    await waitFor(() => expect(play).toHaveBeenCalled());
    expect(urls).toEqual(["/api/voices/F1/sample"]);
  });

  it("explains when the voice model is missing", async () => {
    stubAudio();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "Download the Slovak voice first." }), { status: 409 })));
    render(<OptionFields options={options} health={null} value={settings} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "▶ Listen" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Download the Slovak voice first.");
  });
});
