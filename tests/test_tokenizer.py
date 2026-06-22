"""Tests for the tokenizer module.

The committed tests are fully offline and need none of the ``[tokenizer]``
extra: the chat-template / counting logic is exercised against a small in-test
``FakeTokenizer`` (dependency injection via the ``tokenizer=`` argument), and the
registry / path logic is pure. A single live smoke test downloads a real
tokenizer and is gated behind both ``importorskip`` and the
``SAIA_TOKENIZER_LIVE`` environment variable, so it never runs in CI or the
offline gate by default.
"""

from __future__ import annotations

import os

import pytest

from saia_python import tokenizer as tk
from saia_python.tokenizer import (
    GWDG_MODEL_REPOS,
    ChatTokenCount,
    TokenizerService,
    chat_template_length,
    chat_template_tokens,
    resolve_repo,
    special_token_overhead,
    subword_fertility,
)

# ---------------------------------------------------------------------------
# A deterministic stand-in for a transformers tokenizer
# ---------------------------------------------------------------------------


class FakeTokenizer:
    """Whitespace tokenizer with predictable special/structural-token accounting.

    - ``encode(text, add_special_tokens=False)``: one id per whitespace word;
      with ``add_special_tokens=True`` a BOS (1) and EOS (2) wrap the ids.
    - ``apply_chat_template``: wraps each message's words between a role-start
      (10) and message-end (11) token, optionally appending a generation-prompt
      token (12). So the structural overhead is exactly ``2`` per message
      (+1 for the generation prompt).
    - ``strict_user``: when set, the template raises unless a user turn exists —
      mimicking a strict chat template, to exercise the tolerant fallback.
    """

    def __init__(
        self,
        *,
        strict_user: bool = False,
        with_convert: bool = True,
        fail_on_gen_prompt: bool = False,
    ):
        self.strict_user = strict_user
        self.fail_on_gen_prompt = fail_on_gen_prompt
        if not with_convert:
            # Drop the optional id->token mapping to test that branch.
            self.convert_ids_to_tokens = None  # type: ignore[assignment]

    def encode(self, text, add_special_tokens=False):
        ids = [100 + i for i, _ in enumerate(text.split())]
        if add_special_tokens:
            ids = [1, *ids, 2]
        return ids

    def apply_chat_template(self, messages, tokenize=True, add_generation_prompt=False):
        if not messages:
            raise IndexError("list index out of range")
        if self.strict_user and not any(m.get("role") == "user" for m in messages):
            raise ValueError("this template requires a user message")
        if self.fail_on_gen_prompt and add_generation_prompt:
            raise ValueError("this template cannot add a generation prompt")
        if not tokenize:
            text = "".join(
                f"<|start|>{m.get('role', '')}\n{m.get('content', '')}<|end|>\n"
                for m in messages
            )
            if add_generation_prompt:
                text += "<|start|>assistant\n"
            return text
        ids: list[int] = []
        for m in messages:
            ids.append(10)
            ids.extend(100 + i for i, _ in enumerate(m.get("content", "").split()))
            ids.append(11)
        if add_generation_prompt:
            ids.append(12)
        return ids

    def convert_ids_to_tokens(self, ids):
        return [f"<{i}>" for i in ids]


# ---------------------------------------------------------------------------
# Registry / repository resolution
# ---------------------------------------------------------------------------


def test_registry_is_well_formed():
    assert len(GWDG_MODEL_REPOS) >= 17
    # every value is a plausible org/name HF repo
    for mid, repo in GWDG_MODEL_REPOS.items():
        assert "/" in repo and not repo.startswith("/"), (mid, repo)


@pytest.mark.parametrize(
    "model,expected",
    [
        ("openai-gpt-oss-120b", "openai/gpt-oss-120b"),
        ("qwen3-coder-30b-a3b-instruct", "Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8"),
        ("meta-llama-3.1-8b-instruct", "nvidia/Llama-3.1-8B-Instruct-FP8"),
    ],
)
def test_resolve_repo_by_id(model, expected):
    assert resolve_repo(model) == expected


def test_resolve_repo_by_display_name_and_passthrough():
    # Catalogue display name (also the live /models `name` field).
    assert resolve_repo("GPT OSS 120B") == "openai/gpt-oss-120b"
    # Full org/name passes through untouched, even if unknown to the registry.
    assert resolve_repo("some-org/Custom-Tokenizer") == "some-org/Custom-Tokenizer"


def test_resolve_repo_unknown_raises_with_hint():
    with pytest.raises(ValueError, match="Unknown GWDG model"):
        resolve_repo("definitely-not-a-model")


def test_repo_url():
    assert tk.repo_url("openai-gpt-oss-120b") == (
        "https://huggingface.co/openai/gpt-oss-120b"
    )


# ---------------------------------------------------------------------------
# Cache directory resolution
# ---------------------------------------------------------------------------


def test_tokenizer_dir_precedence(monkeypatch, tmp_path):
    monkeypatch.delenv("SAIA_TOKENIZER_DIR", raising=False)
    assert tk.tokenizer_dir() == tk.DEFAULT_TOKENIZER_DIR
    monkeypatch.setenv("SAIA_TOKENIZER_DIR", str(tmp_path / "env"))
    assert tk.tokenizer_dir() == tmp_path / "env"
    # explicit argument wins over the env var
    assert tk.tokenizer_dir(tmp_path / "explicit") == tmp_path / "explicit"


def test_download_returns_cached_without_network(tmp_path):
    # Pre-create the cache layout with the completion marker; download_tokenizer
    # must short-circuit and never touch huggingface_hub (not needed offline).
    repo = tk.resolve_repo("openai-gpt-oss-120b")
    cached = tmp_path / repo
    cached.mkdir(parents=True)
    (cached / tk._COMPLETE_MARKER).write_text("ok", encoding="utf-8")
    out = tk.download_tokenizer("openai-gpt-oss-120b", cache_dir=tmp_path)
    assert out == cached


def test_partial_download_is_not_treated_as_complete(tmp_path, monkeypatch):
    # A directory with files but no completion marker (an interrupted download)
    # must NOT short-circuit — snapshot_download is re-invoked.
    repo = tk.resolve_repo("openai-gpt-oss-120b")
    partial = tmp_path / repo
    partial.mkdir(parents=True)
    (partial / "tokenizer_config.json").write_text("{}", encoding="utf-8")  # only this

    calls: dict[str, object] = {}

    class _FakeHub:
        def snapshot_download(self, **kwargs):
            calls["kwargs"] = kwargs

    monkeypatch.setattr(tk, "_require", lambda name: _FakeHub())
    out = tk.download_tokenizer("openai-gpt-oss-120b", cache_dir=tmp_path)
    assert "kwargs" in calls  # re-downloaded rather than trusting the partial dir
    assert (out / tk._COMPLETE_MARKER).exists()  # marker written after success


def test_download_gated_raises_expressive_error(tmp_path, monkeypatch):
    # A gated 403 from the Hub becomes a clear, actionable GatedRepoAccessError.
    class GatedRepoError(Exception):
        pass

    class _Hub:
        def snapshot_download(self, **kwargs):
            raise GatedRepoError("403 Client Error. Cannot access gated repo")

    monkeypatch.setattr(tk, "_require", lambda name: _Hub())
    with pytest.raises(tk.GatedRepoAccessError) as excinfo:
        tk.download_tokenizer("medgemma-27b-it", cache_dir=tmp_path, force=True)
    msg = str(excinfo.value)
    assert "gated" in msg.lower()
    assert "https://huggingface.co/google/medgemma-27b-it" in msg
    assert "HF_TOKEN" in msg
    assert excinfo.value.__cause__ is not None  # original error preserved
    # No completion marker is written on failure.
    assert not (tmp_path / "google/medgemma-27b-it" / tk._COMPLETE_MARKER).exists()


def test_download_non_gated_error_propagates(tmp_path, monkeypatch):
    class _Hub:
        def snapshot_download(self, **kwargs):
            raise OSError("disk full")

    monkeypatch.setattr(tk, "_require", lambda name: _Hub())
    with pytest.raises(OSError, match="disk full"):
        tk.download_tokenizer(
            "qwen3-coder-30b-a3b-instruct", cache_dir=tmp_path, force=True
        )


# ---------------------------------------------------------------------------
# _to_id_list normalisation
# ---------------------------------------------------------------------------


class _FakeTensor:
    def __init__(self, data):
        self._data = data

    def tolist(self):
        return self._data


@pytest.mark.parametrize(
    "obj,expected",
    [
        ([1, 2, 3], [1, 2, 3]),
        ({"input_ids": [4, 5], "attention_mask": [1, 1]}, [4, 5]),
        ([[6, 7, 8]], [6, 7, 8]),
        (_FakeTensor([9, 10]), [9, 10]),
        ({"input_ids": _FakeTensor([[11, 12]])}, [11, 12]),
    ],
)
def test_to_id_list_normalises_shapes(obj, expected):
    assert tk._to_id_list(obj) == expected


# ---------------------------------------------------------------------------
# Chat-template token counting (deterministic via FakeTokenizer)
# ---------------------------------------------------------------------------


def test_counts_overhead_and_fertility_exactly():
    tok = FakeTokenizer()
    # system has 3 words, user has 2 words -> 5 text tokens.
    r = chat_template_tokens(
        tokenizer=tok,
        system="alpha beta gamma",
        user="delta epsilon",
        add_generation_prompt=True,
    )
    assert isinstance(r, ChatTokenCount)
    assert r.num_text_tokens == 5
    # 2 messages * (role-start + words + msg-end) + generation prompt:
    # (1+3+1) + (1+2+1) + 1 = 10
    assert r.num_tokens == 10
    assert r.overhead_tokens == 5
    assert r.num_words == 5
    assert r.fertility == pytest.approx(1.0)
    assert r.fertility_with_special == pytest.approx(2.0)
    assert r.tokens and r.tokens[0] == "<10>"
    assert r.warnings == []
    assert "tokens" in r.summary()


def test_length_and_overhead_wrappers_match_full_result():
    tok = FakeTokenizer()
    kwargs = dict(tokenizer=tok, system="alpha beta gamma", user="delta epsilon")
    full = chat_template_tokens(**kwargs)
    assert chat_template_length(**kwargs) == full.num_tokens
    assert special_token_overhead(**kwargs) == full.overhead_tokens


def test_subword_fertility_flag_selects_numerator():
    tok = FakeTokenizer()
    kwargs = dict(tokenizer=tok, user="one two three four")
    assert subword_fertility(include_special=False, **kwargs) == pytest.approx(1.0)
    # with_special is strictly larger because the template adds structural tokens
    assert subword_fertility(include_special=True, **kwargs) > 1.0


def test_no_words_yields_nan_fertility():
    import math

    tok = FakeTokenizer()
    r = chat_template_tokens(tokenizer=tok, messages=[{"role": "user", "content": ""}])
    assert r.num_words == 0
    assert math.isnan(r.fertility)


def test_missing_convert_ids_to_tokens_is_tolerated():
    tok = FakeTokenizer(with_convert=False)
    r = chat_template_tokens(tokenizer=tok, user="hello world")
    assert r.num_tokens > 0
    assert r.tokens == []


# ---------------------------------------------------------------------------
# Tolerance: missing parts must never raise
# ---------------------------------------------------------------------------


def test_strict_template_missing_user_falls_back_without_raising():
    tok = FakeTokenizer(strict_user=True)
    # system-only: the strict template rejects it, so a fallback is used.
    r = chat_template_tokens(tokenizer=tok, system="just a system prompt")
    assert r.num_tokens > 0
    assert any("chat template" in w for w in r.warnings)


def test_empty_conversation_does_not_raise():
    tok = FakeTokenizer()
    r = chat_template_tokens(tokenizer=tok, messages=[])
    assert r.num_words == 0
    assert any("empty conversation" in w for w in r.warnings)


def test_requires_model_or_tokenizer():
    with pytest.raises(ValueError, match="model.*tokenizer"):
        chat_template_tokens(user="hello")


# ---------------------------------------------------------------------------
# System / user prompt from a file
# ---------------------------------------------------------------------------


def test_system_prompt_from_markdown_file(tmp_path):
    f = tmp_path / "sys.md"
    f.write_text("# Persona\nYou are helpful", encoding="utf-8")  # 5 words
    tok = FakeTokenizer()
    r = chat_template_tokens(tokenizer=tok, system_file=str(f), user="hi there")
    # 5 (system) + 2 (user) words counted
    assert r.num_words == 7


def test_inline_and_file_together_is_an_error(tmp_path):
    f = tmp_path / "sys.txt"
    f.write_text("text", encoding="utf-8")
    tok = FakeTokenizer()
    with pytest.raises(ValueError, match="not both"):
        chat_template_tokens(tokenizer=tok, system="inline", system_file=str(f))


def test_missing_system_file_raises(tmp_path):
    tok = FakeTokenizer()
    with pytest.raises(FileNotFoundError):
        chat_template_tokens(tokenizer=tok, system_file=str(tmp_path / "nope.md"))


# ---------------------------------------------------------------------------
# TokenizerService — live-model annotation (offline, mocked models service)
# ---------------------------------------------------------------------------


class _FakeModels:
    def __init__(self, entries):
        self._entries = entries

    def list(self):
        return self._entries


def test_service_available_repos_static():
    svc = TokenizerService(None)
    assert svc.available_repos(live=False) == GWDG_MODEL_REPOS
    # No models service -> static catalogue even when live is requested.
    assert svc.available_repos(live=True) == GWDG_MODEL_REPOS


def test_service_annotates_live_list_and_marks_unknown_none():
    entries = [
        {"id": "openai-gpt-oss-120b", "name": "GPT OSS 120B"},
        {"id": "gpt-5", "name": "GPT-5"},  # proprietary, no repo
    ]
    svc = TokenizerService(_FakeModels(entries))
    repos = svc.available_repos(live=True)
    assert repos["openai-gpt-oss-120b"] == "openai/gpt-oss-120b"
    assert repos["gpt-5"] is None


def test_service_falls_back_when_live_list_errors():
    class _Boom:
        def list(self):
            raise RuntimeError("network down")

    svc = TokenizerService(_Boom())
    assert svc.available_repos(live=True) == GWDG_MODEL_REPOS


# ---------------------------------------------------------------------------
# Generation-prompt consistency on the fallback path
# ---------------------------------------------------------------------------


def test_generation_prompt_flag_reflects_dropped_prompt():
    # Template rejects the generation prompt; the retry drops it. The reported
    # flag and rendered string must describe the COUNTED ids (no gen prompt),
    # not the original request.
    tok = FakeTokenizer(fail_on_gen_prompt=True)
    r = chat_template_tokens(
        tokenizer=tok, user="hello world", add_generation_prompt=True
    )
    assert r.add_generation_prompt is False  # effective value, not the input True
    assert r.num_tokens > 0
    assert "assistant" not in (r.rendered or "")  # gen prompt absent from render
    assert any("without a generation prompt" in w for w in r.warnings)


# ---------------------------------------------------------------------------
# Batch download — per-model failure tolerance (offline, monkeypatched)
# ---------------------------------------------------------------------------


def test_download_all_tolerates_per_model_failure(tmp_path, monkeypatch):
    def fake_download(model, **kwargs):
        if model == "bad":
            raise RuntimeError("gated repo / network error")
        return tmp_path / model

    monkeypatch.setattr(tk, "download_tokenizer", fake_download)
    result = tk.download_all_tokenizers(models=["ok", "bad"])
    assert result["ok"] == tmp_path / "ok"
    assert result["bad"] is None  # failure recorded, batch not aborted


def test_describe_download_error_flags_gated_with_url():
    # Detect by exception class name (as huggingface_hub's GatedRepoError does)...
    class GatedRepoError(Exception):
        pass

    msg = tk._describe_download_error("medgemma-27b-it", GatedRepoError("403"))
    assert "gated" in msg.lower()
    assert "huggingface.co/google/medgemma-27b-it" in msg
    # ...and by a 403/401 in the message of a generic error.
    msg2 = tk._describe_download_error(
        "medgemma-27b-it", RuntimeError("403 Client Error")
    )
    assert "huggingface.co/google/medgemma-27b-it" in msg2
    # A non-gated error is reported plainly, without the licence hint.
    plain = tk._describe_download_error(
        "qwen3-coder-30b-a3b-instruct", ValueError("boom")
    )
    assert "gated" not in plain.lower()
    assert "boom" in plain


def test_service_download_all_open_only_filters(monkeypatch):
    # open_only must drop ids whose annotated repo is None (proprietary).
    entries = [
        {"id": "openai-gpt-oss-120b", "name": "GPT OSS 120B"},
        {"id": "gpt-5", "name": "GPT-5"},  # repo None
    ]
    seen: dict[str, list[str] | None] = {}

    def fake_download_all(*, models=None, **kwargs):
        seen["models"] = models
        return {m: None for m in (models or [])}

    monkeypatch.setattr(tk, "download_all_tokenizers", fake_download_all)
    svc = TokenizerService(_FakeModels(entries))
    svc.download_all(open_only=True)
    assert seen["models"] == ["openai-gpt-oss-120b"]  # gpt-5 (no repo) excluded


# ---------------------------------------------------------------------------
# tiktoken path (stubbed — no real tiktoken needed)
# ---------------------------------------------------------------------------


class _StubEncoding:
    def __init__(self, name):
        self.name = name

    def encode(self, text):
        # deterministic: one token per character, tagged by encoding name length
        return list(range(len(text)))


class _StubTiktoken:
    def get_encoding(self, name):
        return _StubEncoding(name)

    def encoding_for_model(self, model):
        raise KeyError(model)  # force the OPENAI_TIKTOKEN_ENCODINGS / default path


def test_count_tiktoken_tokens_uses_model_encoding_lookup(monkeypatch):
    monkeypatch.setattr(tk, "_require", lambda name: _StubTiktoken())
    # known model -> its mapped encoding; count is len(text) per the stub
    assert tk.count_tiktoken_tokens("abcd", model="gpt-5") == 4
    # explicit encoding overrides
    assert tk.count_tiktoken_tokens("ab", encoding="o200k_base") == 2
    # unknown model + no encoding -> falls back without raising
    assert tk.count_tiktoken_tokens("xyz", model="unknown-model") == 3


# ---------------------------------------------------------------------------
# Relative special-token overhead
# ---------------------------------------------------------------------------


def test_overhead_relative_ratios():
    tok = FakeTokenizer()
    # 5 text tokens, 10 templated -> 5 overhead. (see exact-counts test above)
    r = chat_template_tokens(
        tokenizer=tok, system="alpha beta gamma", user="delta epsilon"
    )
    assert r.overhead_tokens == 5
    assert r.overhead_ratio_text == pytest.approx(5 / 5)  # overhead / text
    assert r.overhead_ratio_total == pytest.approx(5 / 10)  # overhead / total
    assert "of total" in r.summary()


def test_overhead_ratio_text_nan_when_no_text():
    import math

    tok = FakeTokenizer()
    r = chat_template_tokens(tokenizer=tok, messages=[{"role": "user", "content": ""}])
    assert r.num_text_tokens == 0
    assert math.isnan(r.overhead_ratio_text)


# ---------------------------------------------------------------------------
# Hugging Face token discovery
# ---------------------------------------------------------------------------


def test_load_hf_token_from_env(monkeypatch):
    for var in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HF_TOKEN", "hf_envtoken")
    assert tk.load_hf_token() == "hf_envtoken"


def test_load_hf_token_from_saia_env_file(monkeypatch, tmp_path):
    for var in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    # cwd has no token file; home has a .saia_env with the token.
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    (home / ".saia_env").write_text("HF_TOKEN=hf_fromfile\n", encoding="utf-8")
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(tk.Path, "home", classmethod(lambda cls: home))
    assert tk.load_hf_token() == "hf_fromfile"


def test_load_hf_token_explicit_path(tmp_path):
    f = tmp_path / "creds.env"
    f.write_text("HUGGING_FACE_HUB_TOKEN=hf_explicit\n", encoding="utf-8")
    assert tk.load_hf_token(str(f)) == "hf_explicit"


def test_load_hf_token_none_when_absent(monkeypatch, tmp_path):
    for var in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    monkeypatch.setattr(tk.Path, "home", classmethod(lambda cls: empty))
    assert tk.load_hf_token() is None


# ---------------------------------------------------------------------------
# Directory token distribution (offline, FakeTokenizer)
# ---------------------------------------------------------------------------


# FakeTokenizer = one token per whitespace-split chunk, so the token count of a
# file equals len(content.split()).
def _make_corpus(root):
    (root / "a.md").write_text("# A\none two three", encoding="utf-8")  # 5 chunks
    sub = root / "sub"
    sub.mkdir()
    (sub / "b.md").write_text("## B\n" + "word " * 10, encoding="utf-8")  # 12 chunks
    (sub / "c.txt").write_text("plain chunk text", encoding="utf-8")  # 3 chunks
    (root / "data.bin").write_bytes(b"\x00\x01\x02")  # skipped (binary)
    (sub / "pic.png").write_bytes(b"not a real image")  # image


def test_token_distribution_walks_recursively_and_classifies(tmp_path):
    _make_corpus(tmp_path)
    tok = FakeTokenizer()
    dist = tk.token_distribution(tmp_path, tokenizer=tok, count_images=False)
    kinds = dist.by_kind()
    assert kinds["text"] == 3  # a.md, sub/b.md, sub/c.txt (recursed into sub/)
    assert kinds["skipped"] == 2  # data.bin + pic.png (count_images=False)
    assert dist.total_tokens == 5 + 12 + 3
    # paths are POSIX-relative to the root.
    assert any(f.path == "sub/b.md" for f in dist.files)
    exts = dist.by_extension()
    assert exts[".md"]["files"] == 2 and exts[".txt"]["files"] == 1
    st = dist.stats()
    assert st["files"] == 3 and st["max"] == 12 and st["min"] == 3
    assert sum(c for _, _, c in dist.histogram(3)) == 3


def test_token_distribution_counts_images_via_estimator(tmp_path, monkeypatch):
    _make_corpus(tmp_path)
    tok = FakeTokenizer()
    # Deterministic image estimate without depending on Pillow.
    monkeypatch.setattr(tk, "_estimate_image_tokens", lambda path, patch: 42)
    dist = tk.token_distribution(tmp_path, tokenizer=tok, count_images=True)
    assert dist.by_kind()["image"] == 1
    img = next(f for f in dist.files if f.kind == "image")
    assert img.num_tokens == 42 and img.path == "sub/pic.png"
    assert dist.total_tokens == 5 + 12 + 3 + 42


def test_token_distribution_max_bytes_skips_large_text(tmp_path):
    (tmp_path / "big.md").write_text("x " * 1000, encoding="utf-8")
    tok = FakeTokenizer()
    dist = tk.token_distribution(tmp_path, tokenizer=tok, max_bytes=10)
    assert dist.by_kind().get("skipped") == 1
    assert dist.total_tokens == 0


def test_token_distribution_requires_model_or_tokenizer(tmp_path):
    with pytest.raises(ValueError, match="model.*tokenizer"):
        tk.token_distribution(tmp_path)


def test_token_distribution_rejects_non_directory(tmp_path):
    f = tmp_path / "f.md"
    f.write_text("hi", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        tk.token_distribution(f, tokenizer=FakeTokenizer())


# ---------------------------------------------------------------------------
# Live smoke test — opt-in only (network + [tokenizer] extra)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("SAIA_TOKENIZER_LIVE"),
    reason="set SAIA_TOKENIZER_LIVE=1 to run the network-backed tokenizer test",
)
def test_live_qwen_chat_template_roundtrip():
    pytest.importorskip("transformers")
    pytest.importorskip("huggingface_hub")
    r = chat_template_tokens(
        "qwen3-coder-30b-a3b-instruct",
        system="You are a terse assistant.",
        user="Write a haiku.",
    )
    assert r.num_text_tokens > 0
    assert r.num_tokens > r.num_text_tokens  # structural overhead is positive
    assert r.overhead_tokens > 0
    assert r.repo == "Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8"
