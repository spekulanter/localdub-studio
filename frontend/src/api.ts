export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";
export type Stage = "download" | "probe" | "extract" | "asr" | "diarize" | "translate" | "tts" | "separate" | "convert" | "assemble" | "export";
export type OriginalAudio = "duck" | "mute" | "background";

export interface Job {
  id: number;
  project_id: number;
  status: JobStatus;
  stage: Stage | "";
  message: string;
  progress: number;
  error: string | null;
  from_stage: Stage | null;
  attempts: number;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
}

export interface Project {
  id: number;
  name: string;
  original_name: string;
  duration: number;
  source_lang: string;
  voice: string;
  llm_model: string;
  asr_id: string;
  original_audio: OriginalAudio;
  keep_original_track: boolean;
  diarize: boolean;
  clone_voice: boolean;
  num_speakers: number | null;
  created_at: number;
  latest_job: Job | null;
  has_output: boolean;
  /** false while a video from a link is still being downloaded */
  has_input: boolean;
  source_url: string | null;
  download_quality: string;
}

export interface Options {
  voices: string[];
  source_languages: Record<string, string>;
  target_language: string;
  default_voice: string;
  default_llm: string;
  default_asr: string;
  asr_choices: ModelChoice[];
  translation_choices: ModelChoice[];
  stages: Stage[];
  max_upload_mb: number;
  separation_available: boolean;
}

export interface Health {
  ok: boolean;
  ollama: { reachable: boolean; error: string | null; models: string[] };
}

export type ReviewStatus = "pending" | "edited" | "approved";

export interface SegmentRow {
  id: number;
  start: number;
  end: number;
  source_text: string;
  translated_text: string;
  fit_status: string | null;
  speaker_id: string;
  voice_id: string | null;
  effective_voice: string | null;
  review_status: ReviewStatus;
  edited: boolean;
  stale_edit: boolean;
  has_audio: boolean;
  placed_start: number | null;
  audio_duration: number | null;
}

export interface SegmentsResponse {
  stage: string | null;
  segments: SegmentRow[];
  edits_pending: boolean;
  speaker_voices: Record<string, string>;
  speaker_defaults: Record<string, string>;
  speaker_gender_estimate: Record<string, string>;
}

/** Fields sent in a segment PATCH. A key set to null clears that edit. */
export interface SegmentPatch {
  translated_text?: string | null;
  voice_id?: string | null;
  start?: number | null;
  end?: number | null;
  review_status?: ReviewStatus | null;
}

export interface Preview {
  url: string;
  duration: number;
  window: number;
}

export interface ModelDownload {
  status: "queued" | "running" | "done" | "error" | "cancelled";
  /** false while a step cannot be interrupted (unpacking the optional packages) */
  cancellable?: boolean;
  cancelling?: boolean;
  done: number;
  total: number;
  message: string;
  error: string | null;
  /** false: only a percentage is meaningful (the package install adds an unpacking estimate) */
  show_bytes?: boolean;
}

export interface Fit {
  level: "ok" | "partial" | "too_big" | "cpu" | "no_gpu";
  text: string;
}

export interface ModelInfo {
  id: string;
  role: string;
  title: string;
  summary: string;
  choose_if: string[];
  avoid_if: string[];
  requirements: {
    vram_gb: number | null;
    disk_gb: number;
    runs_on: string;
    note: string;
    needs_packages: boolean;
  };
  size_bytes: number;
  license: { name: string; url: string };
  status: "recommended" | "available" | "experimental" | "not_recommended" | "custom";
  measured: string | null;
  languages: string | null;
  pinned: string | null;
  custom: boolean;
  default: boolean;
  required: boolean;
  group: string;
  installed: boolean;
  /** false when the optional PyTorch packages are missing */
  available: boolean;
  /** the model new dubs use for its role */
  selected: boolean;
  fits: Fit;
  download: ModelDownload | null;
  locations: string[];
  store_note: string | null;
  size_on_disk: number | null;
  update: { supported: boolean; available: boolean; checked_at: number | null; error: string | null };
  can_delete: boolean;
  can_open_folder: boolean;
}

export interface ModelRole {
  id: string;
  title: string;
  description: string;
  required: boolean;
  selectable: boolean;
  selected_id: string | null;
}

export interface HardwareInfo {
  gpu: { name: string; vram_gb: number; vram_free_gb: number; driver: string } | null;
  ram_gb: number | null;
  cpu_threads: number;
  disk_free_bytes: number;
  disk_total_bytes: number;
}

export interface ModelsResponse {
  catalog_version?: string;
  roles?: ModelRole[];
  models: ModelInfo[];
  required_missing: string[];
  busy: boolean;
  hardware?: HardwareInfo;
  paths?: Record<string, string>;
  models_bytes?: number | null;
}

export interface ModelChoice {
  id: string;
  title: string;
  status: ModelInfo["status"];
  summary: string;
  tag: string | null;
  /** languages this model can recognise; null = all */
  source_langs: string[] | null;
  installed: boolean;
}

export interface ToolState {
  available: boolean;
  version: string | null;
  error: string | null;
}

export interface YoutubeStatus {
  installed: boolean;
  yt_dlp: ToolState;
  deno: ToolState;
  qualities: string[];
  browsers: string[];
}

export interface YoutubeInfo {
  id: string;
  title: string;
  uploader: string | null;
  thumbnail: string | null;
  duration: number | null;
  is_live: boolean;
}

/** What the YouTube tab hands to the form once a link was checked. */
export interface YoutubeChoice {
  url: string;
  quality: string;
  cookies_browser: string;
  info: YoutubeInfo;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail !== undefined) detail = JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

let apiLang = "en";
/** The language of the texts the server provides (model descriptions); set by the I18nProvider. */
export const setApiLang = (lang: string) => {
  apiLang = lang;
};

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  health: () => request<Health>("/api/health"),
  models: (sizes = false) => request<ModelsResponse>(`/api/models?lang=${apiLang}${sizes ? "&sizes=true" : ""}`),
  selectModel: (id: string) => request<{ ok: boolean }>(`/api/models/${encodeURIComponent(id)}/select`, json("POST", {})),
  deleteModel: (id: string) =>
    request<{ deleted: boolean; warnings: string[] }>(`/api/models/${encodeURIComponent(id)}`, { method: "DELETE" }),
  voiceSampleUrl: (voice: string) => `/api/voices/${encodeURIComponent(voice)}/sample`,
  cancelModel: (id: string) => request<{ cancelled: boolean }>(`/api/models/${encodeURIComponent(id)}/cancel`, json("POST", {})),
  modelAction: (id: string, action: "update" | "repair") =>
    request<{ started: string[] }>(`/api/models/${encodeURIComponent(id)}/${action}`, json("POST", {})),
  checkModelUpdates: () =>
    request<{ checked: number; updates: string[]; errors: Record<string, string> }>("/api/models/check-updates", json("POST", {})),
  addOllamaModel: (tag: string) => request<{ id: string }>("/api/models/custom-ollama", json("POST", { tag })),
  openModelsFolder: (id?: string) => request<{ opened: string }>("/api/models/open-folder", json("POST", id ? { id } : {})),
  youtubeStatus: () => request<YoutubeStatus>("/api/youtube/status"),
  youtubeInfo: (url: string, cookies_browser: string) =>
    request<YoutubeInfo>("/api/youtube/info", json("POST", { url, cookies_browser })),
  updateYtdlp: () => request<{ message: string }>("/api/youtube/update", json("POST")),
  createFromYoutube: (body: Record<string, unknown>) =>
    request<Project>("/api/projects/from-youtube", json("POST", body)),
  downloadModels: (ids?: string[]) =>
    request<{ started: string[] }>("/api/models/download", json("POST", ids ? { ids } : {})),
  jobLogFull: (jobId: number) => fetch(`/api/jobs/${jobId}/log/download`).then((r) => r.text()),
  jobLogUrl: (jobId: number) => `/api/jobs/${jobId}/log/download`,
  options: () => request<Options>(`/api/options?lang=${apiLang}`),
  projects: () => request<Project[]>("/api/projects"),
  project: (id: number) => request<Project>(`/api/projects/${id}`),
  createProject: (form: FormData) =>
    request<Project>("/api/projects", { method: "POST", body: form }),
  patchProject: (id: number, patch: Partial<Pick<Project, "name" | "voice" | "llm_model" | "asr_id" | "original_audio" | "keep_original_track" | "diarize" | "num_speakers" | "clone_voice">> & { clone_consent?: boolean }) =>
    request<Project>(`/api/projects/${id}`, json("PATCH", patch)),
  deleteProject: (id: number) => request<void>(`/api/projects/${id}`, { method: "DELETE" }),
  startJob: (projectId: number, fromStage?: Stage) =>
    request<Job>(`/api/projects/${projectId}/jobs`, json("POST", { from_stage: fromStage ?? null })),
  cancelJob: (jobId: number) => request<Job>(`/api/jobs/${jobId}/cancel`, json("POST")),
  jobLog: (jobId: number, tail = 40) =>
    request<{ lines: string[] }>(`/api/jobs/${jobId}/log?tail=${tail}`),
  segments: (projectId: number) => request<SegmentsResponse>(`/api/projects/${projectId}/segments`),
  patchSegment: (projectId: number, id: number, patch: SegmentPatch) =>
    request<SegmentRow>(`/api/projects/${projectId}/segments/${id}`, json("PATCH", patch)),
  revertSegment: (projectId: number, id: number) =>
    request<void>(`/api/projects/${projectId}/segments/${id}/edit`, { method: "DELETE" }),
  setSpeakerVoices: (projectId: number, voices: Record<string, string>) =>
    request<SegmentsResponse>(`/api/projects/${projectId}/speakers`, json("PUT", { voices })),
  segmentAudioUrl: (projectId: number, id: number, version: string | number = 0) =>
    `/api/projects/${projectId}/segments/${id}/audio?v=${version}`,
  /** Synthesise the (possibly unsaved) text with a voice and return a playable blob URL. */
  async previewSegment(projectId: number, id: number, body: { text?: string; voice?: string }): Promise<Preview> {
    const res = await fetch(`/api/projects/${projectId}/segments/${id}/preview`, json("POST", body));
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const b = (await res.json()) as { detail?: unknown };
        if (typeof b.detail === "string") detail = b.detail;
      } catch {
        /* not JSON */
      }
      throw new ApiError(res.status, detail);
    }
    return {
      url: URL.createObjectURL(await res.blob()),
      duration: Number(res.headers.get("X-Audio-Duration")),
      window: Number(res.headers.get("X-Window")),
    };
  },
  fileUrl: (projectId: number, kind: "video" | "srt" | "srt_en", inline = false) =>
    `/api/projects/${projectId}/files/${kind}${inline ? "?inline=true" : ""}`,
  sourceUrl: (projectId: number) => `/api/projects/${projectId}/source`,
};

/** Subscribe to job progress (server-sent events). Returns a function that closes the stream. */
export function watchJob(jobId: number, onJob: (job: Job) => void, onLost?: () => void): () => void {
  const source = new EventSource(`/api/jobs/${jobId}/events`);
  source.onmessage = (ev: MessageEvent<string>) => {
    const job = JSON.parse(ev.data) as Job;
    onJob(job);
    if (job.status !== "queued" && job.status !== "running") source.close();
  };
  source.onerror = () => {
    // The browser retries by itself; report only when the stream is closed for good.
    if (source.readyState === EventSource.CLOSED) onLost?.();
  };
  return () => source.close();
}
