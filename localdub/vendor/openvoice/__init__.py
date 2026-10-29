"""Vendored subset of OpenVoice (MyShell.ai, MIT licence, see LICENSE in this folder).

Source: https://github.com/myshell-ai/OpenVoice at commit 74a1d147b17a8c3092dd5430504bd83ef6c7eb23
(`openvoice/{attentions,commons,mel_processing,models,modules,transforms,utils}.py`).

Changes: imports rewritten to this package; `mel_processing` imports librosa lazily; `api.py` and the
text front end were left out (voice conversion does not need them). Nothing else was modified.
"""
