export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";
export type Stage = "probe" | "extract" | "asr" | "diarize" | "translate" | "tts" | "separate" | "convert" | "assemble" | "export";
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
  original_audio: OriginalAudio;
  keep_original_track: boolean;
  diarize: boolean;
  clone_voice: boolean;
  num_speakers: number | null;
  created_at: number;
  latest_job: Job | null;
  has_output: boolean;
}

export interface Options {
  voices: string[];
  source_languages: Record<string, string>;
  target_language: string;
  default_voice: string;
  default_llm: string;
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
  status: "queued" | "running" | "done" | "error";
  done: number;
  total: number;
  message: string;
  error: string | null;
  /** false: only a percentage is meaningful (the package install adds an unpacking estimate) */
  show_bytes?: boolean;
}

export interface ModelInfo {
  id: string;
  title: string;
  description: string;
  size_bytes: number;
  required: boolean;
  group: string;
  installed: boolean;
  /** false when the optional PyTorch packages are missing */
  available: boolean;
  download: ModelDownload | null;
}

export interface ModelsResponse {
  models: ModelInfo[];
  required_missing: string[];
  busy: boolean;
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

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  health: () => request<Health>("/api/health"),
  models: () => request<ModelsResponse>("/api/models"),
  downloadModels: (ids?: string[]) =>
    request<{ started: string[] }>("/api/models/download", json("POST", ids ? { ids } : {})),
  jobLogFull: (jobId: number) => fetch(`/api/jobs/${jobId}/log/download`).then((r) => r.text()),
  jobLogUrl: (jobId: number) => `/api/jobs/${jobId}/log/download`,
  options: () => request<Options>("/api/options"),
  projects: () => request<Project[]>("/api/projects"),
  project: (id: number) => request<Project>(`/api/projects/${id}`),
  createProject: (form: FormData) =>
    request<Project>("/api/projects", { method: "POST", body: form }),
  patchProject: (id: number, patch: Partial<Pick<Project, "name" | "voice" | "llm_model" | "original_audio" | "keep_original_track" | "diarize" | "num_speakers" | "clone_voice">> & { clone_consent?: boolean }) =>
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
