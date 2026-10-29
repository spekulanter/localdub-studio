export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";
export type Stage = "probe" | "extract" | "asr" | "translate" | "tts" | "assemble" | "export";
export type OriginalAudio = "duck" | "mute";

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
}

export interface Health {
  ok: boolean;
  ollama: { reachable: boolean; error: string | null; models: string[] };
}

export interface SegmentRow {
  id: number;
  start: number;
  end: number;
  source_text: string;
  translated_text: string;
  fit_status: string | null;
}

export interface SegmentsResponse {
  stage: string | null;
  segments: SegmentRow[];
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
  options: () => request<Options>("/api/options"),
  projects: () => request<Project[]>("/api/projects"),
  project: (id: number) => request<Project>(`/api/projects/${id}`),
  createProject: (form: FormData) =>
    request<Project>("/api/projects", { method: "POST", body: form }),
  patchProject: (id: number, patch: Partial<Pick<Project, "name" | "voice" | "llm_model" | "original_audio" | "keep_original_track">>) =>
    request<Project>(`/api/projects/${id}`, json("PATCH", patch)),
  deleteProject: (id: number) => request<void>(`/api/projects/${id}`, { method: "DELETE" }),
  startJob: (projectId: number, fromStage?: Stage) =>
    request<Job>(`/api/projects/${projectId}/jobs`, json("POST", { from_stage: fromStage ?? null })),
  cancelJob: (jobId: number) => request<Job>(`/api/jobs/${jobId}/cancel`, json("POST")),
  jobLog: (jobId: number, tail = 40) =>
    request<{ lines: string[] }>(`/api/jobs/${jobId}/log?tail=${tail}`),
  segments: (projectId: number) => request<SegmentsResponse>(`/api/projects/${projectId}/segments`),
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
