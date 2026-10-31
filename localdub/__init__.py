"""LocalDub Studio."""

import os
from pathlib import Path

from localdub import extras as _extras
from localdub.paths import user_dir

# Everything the app downloads lives under ONE folder (the models folder), so the Models page can
# show where it is, measure it and delete things safely. Hugging Face downloads of libraries we do
# not control (Demucs) follow HF_HUB_CACHE, so point it there before any huggingface_hub import.
_models = os.environ.get("LOCALDUB_MODELS_DIR")
os.environ.setdefault(
    "HF_HUB_CACHE", str((Path(_models) if _models else user_dir("models")) / "huggingface")
)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
# Plain HTTP downloads (not the Xet transfer engine): they can be cancelled from the models page.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

# Optional PyTorch packages installed from inside the app live outside the program folder.
_extras.activate()
