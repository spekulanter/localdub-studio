from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

import numpy as np
import pytest

from localdub.config import Settings
from localdub.core.asr.parakeet_provider import plan_chunks, tokens_to_words
from localdub.core.modelmgr import handlers as H
from localdub.core.modelmgr import hardware as hw
from localdub.core.modelmgr.catalog import (
    CatalogError,
    Requirements,
    load_catalog,
    parse_catalog,
    valid_ollama_tag,
)
from localdub.core.modelmgr.manager import ModelManager
from localdub.core.modelmgr.resolve import UnknownModel, resolve_asr
from localdub.core.modelmgr.state import ModelState
from localdub.core.models import ModelDownloadError, ensure_archive_files


def make_manager(tmp_path: Path) -> ModelManager:
    s = Settings(data_dir=tmp_path / "data", models_dir=tmp_path / "models",
                 ollama_url="http://127.0.0.1:9")  # fmt: skip
    return ModelManager(s)


# ----- catalogue ---------------------------------------------------------------------------
def test_the_shipped_catalogue_is_valid_and_every_choice_has_a_default():
    cat = load_catalog()
    for role in cat.roles:
        if role.selectable:
            assert cat.default_of(role.id) is not None
    assert cat.default_of("asr").id == "whisper-large-v3"  # type: ignore[union-attr]
    assert cat.default_of("translation").id == "translategemma-4b"  # type: ignore[union-attr]
    # nothing may claim a measurement it does not have
    assert cat.entry("translategemma-12b").measured is None  # type: ignore[union-attr]
    assert cat.entry("parakeet-tdt-0.6b-v3").status == "experimental"  # type: ignore[union-attr]
    for e in cat.entries:
        assert e.choose_if or not e.avoid_if or e.id, e.id
        assert e.license_name and e.license_url.startswith("https://")


def test_a_malformed_catalogue_is_refused():
    base = {"catalog_version": "x", "roles": [], "entries": [{"id": "a"}]}
    with pytest.raises(CatalogError):
        parse_catalog(base)


def test_ollama_tags_are_validated():
    assert valid_ollama_tag("gemma3:12b") and valid_ollama_tag("user/model:q4")
    assert not valid_ollama_tag("http://evil/x") and not valid_ollama_tag("a b")
    assert not valid_ollama_tag("../x") and not valid_ollama_tag("")


def test_asr_ids_resolve_and_unknown_ones_fail(tmp_path: Path):
    s = Settings(models_dir=tmp_path)
    w = resolve_asr(s, "whisper-large-v3")
    assert (w.engine, w.name, w.repo) == ("whisper", "large-v3", "Systran/faster-whisper-large-v3")
    p = resolve_asr(s, "parakeet-tdt-0.6b-v3")
    assert p.engine == "parakeet" and p.folder == tmp_path / "parakeet-tdt-0.6b-v3-int8"
    with pytest.raises(UnknownModel):
        resolve_asr(s, "translategemma-4b")


# ----- hardware ----------------------------------------------------------------------------
def test_nvidia_smi_output_is_parsed():
    gpu = hw.parse_smi("NVIDIA GeForce RTX 5070 Ti, 16303, 15000, 560.94\n")
    assert gpu and gpu.name.endswith("5070 Ti") and round(gpu.vram_gb) == 16
    assert hw.parse_smi("garbage") is None


def test_fit_levels():
    gpu8 = hw.Hardware(hw.Gpu("x", 8192, 8000, "1"), 32.0, 8, 10**12, 2 * 10**12)
    gpu16 = hw.Hardware(hw.Gpu("x", 16384, 16000, "1"), 32.0, 8, 10**12, 2 * 10**12)
    none = hw.Hardware(None, 16.0, 8, 10**12, 2 * 10**12)
    big = Requirements(9, 8.1, "gpu-or-cpu")
    assert hw.fits(big, gpu8)["level"] == "partial"
    assert hw.fits(big, gpu16)["level"] == "ok"
    assert hw.fits(big, none)["level"] == "no_gpu"
    assert hw.fits(Requirements(19, 17, "gpu-or-cpu"), gpu8)["level"] == "too_big"
    assert hw.fits(Requirements(None, 1, "cpu"), none)["level"] == "cpu"


def test_speaker_models_are_pinned_to_a_commit_that_cannot_change():
    """Upstream replaced the embedding file in its GitHub release on 2026-11-19 and every new
    download failed its checksum. A Hugging Face URL with a commit id always serves the same bytes."""
    import re

    from localdub.core.diarize.sherpa_diarizer import EMBEDDING, SEGMENTATION, SIZES

    for model in (SEGMENTATION, EMBEDDING):
        assert re.match(r"https://huggingface\.co/[\w.-]+/[\w.-]+/resolve/[0-9a-f]{40}/", model.url)
        assert re.fullmatch(r"[0-9a-f]{64}", model.sha256) and model.member is None
    assert EMBEDDING.sha256.startswith("1a331345")  # the file LocalDub has always installed
    assert load_catalog().entry("diarization").size_bytes == sum(SIZES)  # type: ignore[union-attr]


# What Windows keeps in the registry for each display adapter (values as winreg returns them).
AMD_RX7800 = {
    "DriverDesc": "AMD Radeon RX 7800 XT",
    "MatchingDeviceId": "PCI\\VEN_1002&DEV_747E&REV_C8",
    "HardwareInformation.qwMemorySize": 17_163_091_968,  # REG_QWORD: 16 GB
    "HardwareInformation.MemorySize": 4_293_918_720,  # REG_DWORD: stuck at 4 GB
    "DriverVersion": "32.0.12033.1030",
}
INTEL_UHD = {  # integrated graphics: memory written as REG_BINARY, no 64-bit value
    "DriverDesc": "Intel(R) UHD Graphics",
    "MatchingDeviceId": "PCI\\VEN_8086&DEV_A788&SUBSYS_3E3A17AA",
    "HardwareInformation.MemorySize": bytes([0, 240, 255, 127]),
    "DriverVersion": "32.0.101.7088",
}
BASIC = {"DriverDesc": "Microsoft Basic Display Adapter", "MatchingDeviceId": "ROOT\\BasicDisplay"}


def test_display_adapters_are_read_from_registry_values():
    amd = hw.adapter_from_values(AMD_RX7800)
    assert amd is not None and amd.vendor == "amd" and amd.name == "AMD Radeon RX 7800 XT"
    assert round(amd.vram_gb) == 16 and not amd.cuda  # the 64-bit value wins over the 4 GB one
    intel = hw.adapter_from_values(INTEL_UHD)
    assert intel is not None and intel.vendor == "intel" and round(intel.vram_gb) == 2
    assert hw.adapter_from_values(BASIC) is None  # no real card behind it
    assert hw.pick_adapter([intel, amd]) == amd and hw.pick_adapter([]) is None


def test_this_windows_machine_lists_its_cards():
    """Reads the real registry: every card found has a maker and a name (none on other systems)."""
    for gpu in hw.windows_adapters():
        assert gpu.name and gpu.vendor in ("nvidia", "amd", "intel", "other")


def test_without_nvidia_an_amd_card_is_found(monkeypatch):
    monkeypatch.setattr(hw, "_gpu_cache", None)
    monkeypatch.setattr(hw.sys, "platform", "win32")
    monkeypatch.setattr(hw, "_smi", lambda: None)  # no NVIDIA driver
    cards = [hw.adapter_from_values(v) for v in (INTEL_UHD, AMD_RX7800)]
    monkeypatch.setattr(hw, "windows_adapters", lambda: cards)
    gpu = hw.detect_gpu()
    assert gpu is not None and gpu.name == "AMD Radeon RX 7800 XT"


def test_an_amd_card_counts_for_ollama_only():
    amd = hw.Hardware(hw.adapter_from_values(AMD_RX7800), 32.0, 16, 10**12, 2 * 10**12)
    intel = hw.Hardware(hw.adapter_from_values(INTEL_UHD), 16.0, 8, 10**12, 2 * 10**12)
    whisper, gemma = Requirements(6, 3, "gpu"), Requirements(4, 3.3, "gpu-or-cpu")

    fit = hw.fits(whisper, amd, "sk")
    assert fit["level"] == "needs_nvidia" and "AMD Radeon RX 7800 XT" in fit["text"]
    fit = hw.fits(gemma, amd, "sk", ollama=True)
    assert fit["level"] == "ok" and "Radeon RX 6000" in fit["text"]
    assert hw.fits(Requirements(19, 17, "gpu-or-cpu"), amd, ollama=True)["level"] == "partial"
    assert hw.fits(gemma, intel, ollama=True)["level"] == "needs_nvidia"  # Ollama: no Intel
    assert hw.fits(Requirements(None, 1, "cpu"), amd)["level"] == "cpu"


def test_the_models_page_shows_an_amd_card(monkeypatch, tmp_path: Path):
    amd = hw.Hardware(hw.adapter_from_values(AMD_RX7800), 32.0, 16, 10**12, 2 * 10**12)
    monkeypatch.setattr(hw, "detect", lambda models_dir: amd)
    snap = make_manager(tmp_path).snapshot(lang="sk")
    assert snap["hardware"]["gpu"]["vendor"] == "amd"
    rows = {m["id"]: m for m in snap["models"]}
    assert rows["whisper-large-v3"]["fits"]["level"] == "needs_nvidia"
    assert rows["translategemma-4b"]["fits"]["level"] == "ok"


# ----- safe deletion -----------------------------------------------------------------------
def test_safe_rmtree_removes_inside_the_root_only(tmp_path: Path):
    root = tmp_path / "models"
    (root / "a").mkdir(parents=True)
    (root / "a" / "f.bin").write_bytes(b"x")
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(H.NotDeletable):
        H.safe_rmtree(outside, root)
    with pytest.raises(H.NotDeletable):
        H.safe_rmtree(root, root)
    assert H.safe_rmtree(root / "a", root) is True and not (root / "a").exists()
    assert H.safe_rmtree(root / "missing", root) is False


def test_safe_rmtree_never_follows_links(tmp_path: Path):
    root = tmp_path / "models"
    target = tmp_path / "precious"
    target.mkdir()
    (target / "keep.txt").write_text("keep")
    (root / "m").mkdir(parents=True)
    try:
        (root / "m" / "link").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("cannot create symlinks here")
    with pytest.raises(H.NotDeletable):
        H.safe_rmtree(root / "m", root)
    assert (target / "keep.txt").exists()


# ----- state -------------------------------------------------------------------------------
def test_state_survives_restarts_and_a_corrupt_file(tmp_path: Path):
    path = tmp_path / "models-state.json"
    st = ModelState(path)
    st.set_selected("asr", "whisper-large-v3-turbo")
    st.add_custom("gemma3:12b", 8_100_000_000)
    st.update_record("x", update_available=True)
    again = ModelState(path)
    assert again.selected("asr") == "whisper-large-v3-turbo"
    assert again.custom_ollama()[0]["tag"] == "gemma3:12b"
    assert again.record("x")["update_available"] is True
    path.write_text("{ not json", encoding="utf-8")
    assert ModelState(path).selected("asr") is None


# ----- manager -----------------------------------------------------------------------------
def test_selection_needs_an_installed_model_and_falls_back_to_the_default(
    tmp_path: Path, monkeypatch
):
    mgr = make_manager(tmp_path)
    installed = {"whisper-large-v3", "whisper-small-en"}
    monkeypatch.setattr(
        H.Handler, "installed", lambda self, e, ctx: e.id in installed, raising=True
    )
    for cls in (H.WhisperHandler, H.ParakeetHandler, H.OllamaHandler):
        monkeypatch.setattr(cls, "installed", lambda self, e, ctx: e.id in installed)
    with pytest.raises(H.ModelError):
        mgr.select("parakeet-tdt-0.6b-v3")  # not downloaded
    mgr.select("whisper-small-en")
    assert mgr.selected_entry("asr").id == "whisper-small-en"  # type: ignore[union-attr]
    installed.discard("whisper-small-en")  # deleted behind our back
    assert mgr.selected_entry("asr").id == "whisper-large-v3"  # type: ignore[union-attr]
    with pytest.raises(H.ModelError):
        mgr.select("supertonic")  # nothing to choose for the voice


def test_deleting_is_refused_during_jobs_and_warns_about_the_last_model(
    tmp_path: Path, monkeypatch
):
    mgr = make_manager(tmp_path)
    deleted: list[str] = []
    monkeypatch.setattr(H.WhisperHandler, "installed", lambda self, e, ctx: e.id not in deleted)
    monkeypatch.setattr(H.WhisperHandler, "delete", lambda self, e, ctx: deleted.append(e.id))
    for other in ("whisper-large-v3-turbo", "whisper-small-en"):
        deleted.append(other)  # pretend these were never installed -> large-v3 is the last one
    deleted_before = list(deleted)
    mgr.jobs_active = lambda: True
    with pytest.raises(H.ModelError, match="running"):
        mgr.delete("whisper-large-v3")
    assert deleted == deleted_before
    mgr.jobs_active = lambda: False
    monkeypatch.setattr(H.ParakeetHandler, "installed", lambda self, e, ctx: False)
    result = mgr.delete("whisper-large-v3")
    assert result["deleted"] and "needs one" in result["warnings"][0]


def test_custom_ollama_models_are_validated_remembered_and_removable(tmp_path: Path, monkeypatch):
    mgr = make_manager(tmp_path)
    monkeypatch.setattr(
        "localdub.core.modelmgr.manager.ollama_manifest", lambda tag: ("d" * 64, 5_000_000_000)
    )
    with pytest.raises(H.ModelError):
        mgr.add_custom_ollama("https://x/y")
    entry = mgr.add_custom_ollama("someone/gemma3:12b")
    assert entry.custom and entry.status == "custom" and "/" not in entry.id
    assert mgr.get(entry.id).source["tag"] == "someone/gemma3:12b"
    assert make_manager(tmp_path).get(entry.id)  # survives a restart
    mgr.remove_custom(entry.id, delete_files=False)
    with pytest.raises(H.ModelError):
        mgr.get(entry.id)
    with pytest.raises(H.NotDeletable):
        mgr.remove_custom("translategemma-4b", delete_files=False)


def test_update_check_compares_local_and_remote_revisions(tmp_path: Path, monkeypatch):
    mgr = make_manager(tmp_path)
    monkeypatch.setattr(
        H.OllamaHandler, "installed", lambda self, e, ctx: e.id == "translategemma-4b"
    )
    monkeypatch.setattr(H.WhisperHandler, "installed", lambda self, e, ctx: False)
    monkeypatch.setattr(H.OllamaHandler, "local_revision", lambda self, e, ctx: "old")
    monkeypatch.setattr(H.OllamaHandler, "remote_revision", lambda self, e, ctx: "new")
    out = mgr.check_updates()
    assert out["updates"] == ["translategemma-4b"] and out["checked"] == 1

    def offline(self, e, ctx):
        raise H.ModelError("offline")

    monkeypatch.setattr(H.OllamaHandler, "remote_revision", offline)
    out = mgr.check_updates()
    assert out["updates"] == [] and "offline" in out["errors"]["translategemma-4b"]


def test_ollama_names_match_with_or_without_latest_tag():
    tags = [{"name": "all-minilm:latest"}, {"name": "qwen3:8b"}]
    assert H.ollama_find(tags, "all-minilm")
    assert H.ollama_find(tags, "qwen3:8b") and not H.ollama_find(tags, "qwen3:4b")
    assert H.ollama_find(None, "x") is None


def test_ollama_registry_tags_split():
    assert H.split_ollama_tag("translategemma:4b") == ("library", "translategemma", "4b")
    assert H.split_ollama_tag("user/m") == ("user", "m", "latest")


# ----- archive download --------------------------------------------------------------------
def make_tar(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_archive_members_are_extracted_after_the_checksum_matches(tmp_path: Path):
    import httpx

    blob = make_tar({"pk/a.onnx": b"AAA", "pk/tokens.txt": b"t", "pk/test_wavs/x.wav": b"junk"})
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=blob))
    )
    dest = tmp_path / "pk"
    ensure_archive_files(
        "http://t/x.tar.bz2", hashlib.sha256(blob).hexdigest(),
        {"pk/a.onnx": "a.onnx", "pk/tokens.txt": "tokens.txt"}, dest, client=client,
    )  # fmt: skip
    assert sorted(p.name for p in dest.iterdir()) == ["a.onnx", "tokens.txt"]
    assert (dest / "a.onnx").read_bytes() == b"AAA"


def test_a_wrong_archive_checksum_installs_nothing(tmp_path: Path):
    import httpx

    blob = make_tar({"pk/a.onnx": b"AAA"})
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=blob))
    )
    with pytest.raises(ModelDownloadError):
        ensure_archive_files(
            "http://t/x", "0" * 64, {"pk/a.onnx": "a.onnx"}, tmp_path / "d", client=client
        )
    assert not list((tmp_path / "d").glob("*")) if (tmp_path / "d").exists() else True


# ----- parakeet words ----------------------------------------------------------------------
def test_tokens_are_joined_into_words_with_times():
    toks = [" Hel", "lo", " wor", "ld", ".", " Bye"]
    starts = [0.0, 0.2, 0.6, 0.8, 1.0, 2.0]
    durs = [0.2, 0.3, 0.2, 0.2, 0.1, 0.4]
    words = tokens_to_words(toks, starts, durs, offset=10.0)
    assert [w.text for w in words] == [" Hello", " world.", " Bye"]
    assert words[0].start == 10.0 and words[1].start == 10.6
    assert words[0].end <= words[1].start and words[2].end > words[2].start


def test_long_audio_is_cut_at_a_quiet_moment():
    sr = 16000
    audio = np.ones(sr * 100, dtype=np.float32) * 0.5
    audio[int(38.5 * sr) : int(38.7 * sr)] = 0.0  # a pause just before the 40 s limit
    chunks = plan_chunks(audio, sr, max_s=40.0, search_s=4.0)
    assert chunks[0][0] == 0 and chunks[-1][1] == len(audio)
    assert all(b - a <= 40 * sr for a, b in chunks)
    assert 38.5 * sr <= chunks[0][1] <= 38.7 * sr
    assert all(chunks[i][1] == chunks[i + 1][0] for i in range(len(chunks) - 1))


# ----- Slovak texts ------------------------------------------------------------------------
def test_every_catalogue_entry_and_role_has_slovak_texts():
    cat = load_catalog()
    for role in cat.roles:
        title, description = role.text("sk")
        assert title and description and description != role.description
    for e in cat.entries:
        sk = e.text("sk")
        assert sk["summary"] != e.summary, e.id
        assert len(sk["choose_if"]) == len(e.choose_if), e.id
        assert len(sk["avoid_if"]) == len(e.avoid_if), e.id
        if e.measured:
            assert sk["measured"] != e.measured, e.id
        if e.pinned:
            assert sk["pinned"] != e.pinned, e.id
        if e.requirements.note:
            assert sk["note"] != e.requirements.note, e.id
    # an unknown language falls back to English
    assert cat.entries[0].text("de")["summary"] == cat.entries[0].summary


def test_fit_texts_follow_the_language():
    gpu8 = hw.Hardware(hw.Gpu("x", 8192, 8000, "1"), 32.0, 8, 10**12, 2 * 10**12)
    big = Requirements(9, 8.1, "gpu-or-cpu")
    assert "Chce asi" in hw.fits(big, gpu8, "sk")["text"]
    assert "Wants about" in hw.fits(big, gpu8)["text"]
    assert "Beží na procesore" in hw.fits(Requirements(None, 1, "cpu"), gpu8, "sk")["text"]
