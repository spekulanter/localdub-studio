import json

import httpx
import pytest

from localdub.core.timeline.models import DialogueSegment
from localdub.core.translation.ollama_provider import OllamaClient, OllamaError, OllamaTranslator
from localdub.core.translation.prompts import (
    ContextLine,
    PromptProfile,
    char_budget,
    clean_translation,
    generic_messages,
    profile_for_model,
)


def test_prompt_helpers():
    assert char_budget(0.1, 14) == 8
    assert char_budget(2, 14) == 28
    assert profile_for_model("TranslateGemma:latest") == PromptProfile.TRANSLATEGEMMA
    assert clean_translation(' Slovak: " ahoj  svet " ') == "ahoj svet"
    msgs = generic_messages(
        "Hi",
        source_lang="en",
        target_lang="sk",
        duration_s=1,
        budget=10,
        before=[ContextLine("Earlier", "Predtým")],
        after=[ContextLine("Later")],
    )
    assert "Previous lines" in msgs[1]["content"] and "Predtým" in msgs[1]["content"]
    assert "Following lines" in msgs[1]["content"] and "max 10 characters" in msgs[1]["content"]


def setup_client(handler):
    client = OllamaClient()
    client._http.close()
    client._http = httpx.Client(base_url=client.base_url, transport=httpx.MockTransport(handler))
    return client


def test_ollama_models_errors_json_retry_context_and_close():
    requests = []

    def handler(req):
        body = json.loads(req.content or b"{}")
        requests.append((req.url.path, body))
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:8b"}, {"name": "z"}]})
        if req.url.path == "/api/generate":
            return httpx.Response(200, json={})
        content = "A" * 20 if len([x for x in requests if x[0] == "/api/chat"]) == 1 else "OK"
        return httpx.Response(
            200, json={"message": {"content": json.dumps({"translation": content})}}
        )

    client = setup_client(handler)
    translator = OllamaTranslator(client, "qwen3:8b", chars_per_second=8, context_before=1)
    assert client.list_models() == ["qwen3:8b", "z"]
    assert translator.translate_segments(
        [
            DialogueSegment(id=1, start=0, end=1, source_text="Hello"),
            DialogueSegment(id=2, start=1, end=2, source_text="World"),
        ],
        "en",
        "sk",
    ) == ["OK", "OK"]
    chat = [b for p, b in requests if p == "/api/chat"]
    assert len(chat) == 3
    assert chat[0]["format"] and chat[0]["think"] is False
    assert "Hello" in chat[-1]["messages"][1]["content"]
    assert chat[1]["messages"][-1]["content"].startswith("That is")
    translator.close()
    assert requests[-1][0] == "/api/generate" and requests[-1][1]["keep_alive"] == 0

    missing = OllamaTranslator(
        setup_client(lambda req: httpx.Response(200, json={"models": []})), "absent"
    )
    with pytest.raises(OllamaError, match="ollama pull"):
        missing.check_available()


def test_translategemma_plain_mode_and_json_parsing():
    bodies = []

    def handler(req):
        body = json.loads(req.content)
        bodies.append(body)
        return httpx.Response(200, json={"message": {"content": ' Slovak: "Ahoj" '}})

    tr = OllamaTranslator(setup_client(handler), "translategemma:latest")
    assert (
        tr.translate_one(
            "Hi", source_lang="en", target_lang="sk", duration_s=1, before=[], after=[]
        )
        == "Ahoj"
    )
    assert "format" not in bodies[0]
    assert OllamaTranslator
