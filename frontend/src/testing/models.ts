import type { ModelInfo, ModelsResponse } from "../api";

/** A complete ModelInfo for tests; override only what the test is about. */
export const mkModel = (over: Partial<ModelInfo> = {}): ModelInfo => ({
  id: "whisper-large-v3",
  role: "asr",
  title: "Speech recognition",
  summary: "d",
  choose_if: [],
  avoid_if: [],
  requirements: { vram_gb: 4, disk_gb: 3, runs_on: "gpu-or-cpu", note: "", needs_packages: false },
  size_bytes: 3_000_000_000,
  license: { name: "MIT", url: "https://example.org/licence" },
  status: "recommended",
  measured: null,
  languages: null,
  pinned: null,
  custom: false,
  default: false,
  required: true,
  group: "asr",
  installed: false,
  available: true,
  selected: false,
  fits: { level: "ok", text: "Fits your graphics card." },
  download: null,
  locations: [],
  store_note: null,
  size_on_disk: null,
  update: { supported: true, available: false, checked_at: null, error: null },
  can_delete: false,
  can_open_folder: false,
  ...over,
});

export const mkResponse = (models: ModelInfo[], over: Partial<ModelsResponse> = {}): ModelsResponse => ({
  models,
  busy: false,
  required_missing: models.filter((m) => m.required && !m.installed).map((m) => m.id),
  ...over,
});
