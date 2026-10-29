"""Command line entry point (Milestone 0: headless pipeline)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from localdub.config import Settings
from localdub.core.platform import disable_power_throttling
from localdub.pipeline import STAGES, Pipeline, PipelineError


def _setup_logging(verbose: bool, logfile: Path | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if logfile is not None:
        logfile.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(logfile, encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    for noisy in ("httpx", "httpcore", "huggingface_hub", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def cmd_env(args: argparse.Namespace, settings: Settings) -> int:
    from localdub.diagnostics import environment_report

    print(json.dumps(environment_report(settings), indent=2, ensure_ascii=False))
    return 0


def cmd_serve(args: argparse.Namespace, settings: Settings) -> int:
    import uvicorn

    from localdub.api.app import create_app

    uvicorn.run(create_app(settings), host=settings.api_host, port=settings.api_port)
    return 0


def cmd_run(args: argparse.Namespace, settings: Settings) -> int:
    if args.asr_model:
        settings.asr_model = args.asr_model
    if args.llm:
        settings.translation_model = args.llm
    if args.original_audio:
        settings.original_audio = args.original_audio
    if args.drop_original_track:
        settings.keep_original_track = False
    workdir = args.workdir or settings.work_dir / args.input.stem
    _setup_logging(args.verbose, workdir / "pipeline.log")
    pipe = Pipeline(
        args.input,
        workdir,
        settings,
        source_lang=None if args.source_lang == "auto" else args.source_lang,
        target_lang="sk",
        voice=args.voice,
    )
    try:
        result = pipe.run(from_stage=args.from_stage, to_stage=args.to_stage)
    except PipelineError as exc:
        logging.getLogger("localdub").error("Pipeline failed: %s", exc)
        return 1
    print(
        json.dumps(
            {"stages": result, "video": str(pipe.output_video), "srt": str(pipe.output_srt)},
            indent=2,
        )
    )
    return 0


def cmd_verify(args: argparse.Namespace, settings: Settings) -> int:
    from localdub.core.media.ffmpeg import FFmpeg
    from localdub.verify import verify_workdir

    workdir = args.workdir or settings.work_dir / args.input.stem
    asr = None
    if args.back_transcribe:
        from localdub.pipeline import default_providers

        asr = default_providers(settings).asr()
    report = verify_workdir(
        workdir, args.input, FFmpeg(settings.ffmpeg_path, settings.ffprobe_path), asr=asr
    )
    md = report.to_markdown()
    (workdir / "verify_report.md").write_text(md, encoding="utf-8")
    print(md)
    return 0 if report.passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="localdub-m0", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("env", help="print an environment diagnostics report")

    run = sub.add_parser("run", help="dub a video into Slovak")
    run.add_argument("input", type=Path)
    run.add_argument("--workdir", type=Path)
    run.add_argument("--source-lang", default="en", help="ISO code or 'auto'")
    run.add_argument("--voice", help="Supertonic voice, e.g. F1..F5, M1..M5")
    run.add_argument("--llm", help="Ollama model for translation")
    run.add_argument("--asr-model", help="faster-whisper model, e.g. large-v3, medium")
    run.add_argument(
        "--original-audio",
        choices=["duck", "mute"],
        help="duck: original stays quietly under the dub (default); mute: dub only",
    )
    run.add_argument(
        "--drop-original-track",
        action="store_true",
        help="do not store the untouched original audio as a second track in the MP4",
    )
    run.add_argument("--from-stage", choices=STAGES, help="force re-running from this stage")
    run.add_argument("--to-stage", choices=STAGES, help="stop after this stage")

    sub.add_parser("serve", help="start the local web UI and API")
    fetch = sub.add_parser("fetch-models", help="download the model files ahead of the first job")
    fetch.add_argument("--diarization", action="store_true", help="also speaker-detection models")
    fetch.add_argument(
        "--experimental",
        action="store_true",
        help="also the speech-removal and voice-cloning models (needs the experimental extra)",
    )

    ver = sub.add_parser("verify", help="objective checks of a finished work directory")
    ver.add_argument("input", type=Path, help="the source video")
    ver.add_argument("--workdir", type=Path)
    ver.add_argument("--back-transcribe", action="store_true", help="ASR the dub (sk) and compare")

    args = parser.parse_args(argv)
    # Windows consoles default to a legacy code page (e.g. cp1250); paths and Slovak text
    # must never crash logging.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    _setup_logging(args.verbose)
    disable_power_throttling()
    settings = Settings()
    if args.cmd == "env":
        return cmd_env(args, settings)
    if args.cmd == "verify":
        return cmd_verify(args, settings)
    if args.cmd == "fetch-models":
        from localdub.core.model_fetch import fetch_models

        fetch_models(settings, diarization=args.diarization, experimental=args.experimental)
        return 0
    if args.cmd == "serve":
        return cmd_serve(args, settings)
    return cmd_run(args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
