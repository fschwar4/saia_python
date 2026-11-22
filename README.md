# saia-python

[![PyPI](https://img.shields.io/pypi/v/saia-python.svg)](https://pypi.org/project/saia-python/)
[![Python versions](https://img.shields.io/pypi/pyversions/saia-python.svg)](https://pypi.org/project/saia-python/)
[![License: AGPL-3.0-only](https://img.shields.io/badge/license-AGPL--3.0--only-blue.svg)](https://github.com/fschwar4/saia_python/blob/main/LICENSE)
[![Tests](https://github.com/fschwar4/saia_python/actions/workflows/tests.yml/badge.svg)](https://github.com/fschwar4/saia_python/actions/workflows/tests.yml)
[![Docs](https://img.shields.io/badge/docs-online-blue.svg)](https://fschwar4.github.io/saia_python/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20480724.svg)](https://doi.org/10.5281/zenodo.20480724)

A Python wrapper for the [GWDG SAIA (Scalable AI Accelerator) platform](https://docs.hpc.gwdg.de/services/ai-services/saia/index.html) REST API.

SAIA provides self-hosted, OpenAI-compatible AI services at GWDG, including chat completions, voice transcription/translation, document conversion, and RAG (ARCANA). This library wraps the REST API so you can use it from Python — both as an object-oriented client and as standalone functions.

## Installation

```bash
pip install saia-python
```

Or from source:

```bash
git clone https://github.com/fschwar4/saia_python.git
cd saia_python
pip install -e .
```

## Quick Start

```python
from saia_python import SAIAClient

# API key auto-discovered from SAIA_API_KEY env var, .saia_api, or .env file
client = SAIAClient()

# List available models
print(client.models.list_ids())

# Chat completion
response = client.chat.completions.create(
    model="qwen3-30b-a3b-instruct-2507",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response["choices"][0]["message"]["content"])

# Check your rate limits
print(client.get_rate_limits())
```

All services are also available as standalone functions:

```python
from saia_python import list_model_ids, chat_completion

list_model_ids()
chat_completion(model="qwen3-30b-a3b-instruct-2507", messages=[...])
```

### Completions, Responses and Messages

The same client also speaks SAIA's other routes that generate text. Each call
is named as in the vendor SDK and returns a dict, and `text_of()` reads the
answer from any of them:

```python
from saia_python import text_of

model = "qwen3-30b-a3b-instruct-2507"
completion = client.completions.create(model, "Once upon a time", max_tokens=32)
response = client.responses.create(model, "Hello!", instructions="Be brief.")
message = client.messages.create(model, [{"role": "user", "content": "Hello!"}], max_tokens=256)
print(text_of(completion), text_of(response), text_of(message))
```

`/responses` keeps no state, so send the whole conversation each time. As of
2026-11-22, GWDG's documentation lists neither `/responses` nor `/messages`;
both work (checked live that day). See
[Native Generation Routes](https://fschwar4.github.io/saia_python/implementation.html#native-generation-routes)
and [ADR-0008](docs/adr/0008-native-wrappers-for-undocumented-routes.md).

### Async

For concurrent workloads (e.g. an ASGI service), install the `[async]` extra and
use `AsyncSAIAClient` — the `httpx.AsyncClient` twin of the data plane, carrying
the **same** `RetryPolicy` and rate-limit handling as the sync client (not the
`openai_async` shim, which bypasses them):

```bash
pip install saia-python[async]
```

```python
import asyncio
from saia_python.aio import AsyncSAIAClient


async def main():
    async with AsyncSAIAClient() as client:
        # Non-streaming RAG chat
        answer = await client.arcana.chat(
            model="deepseek-v4-flash-0731",
            messages=[{"role": "user", "content": "Summarise the onboarding guide."}],
            arcana_id="owner/kb",
        )
        print(answer["choices"][0]["message"]["content"])

        # Streaming plain chat — retry=False fails fast with an informative 429
        stream = await client.chat.completions.create(
            model="qwen3-30b-a3b-instruct-2507",
            messages=[{"role": "user", "content": "Hello!"}],
            stream=True,
            retry=False,
        )
        async for chunk in stream:
            ...


asyncio.run(main())
```

Async covers the data plane (chat, ARCANA RAG chat, streaming) plus the
read-only control-plane calls (`models`, arcana `version`/`heartbeat`/`list`/
`get`, `health_check`). File upload/index/sync, voice, and document conversion
remain synchronous on `SAIAClient` — see
[ADR-0007](docs/adr/0007-native-async-transport.md).

## Supported Services

| Service | Description | GWDG Docs |
|---------|-------------|-----------|
| **Chat AI** | Chat completions with streaming, tool calling, and structured output (Pydantic) | [Chat AI](https://docs.hpc.gwdg.de/services/ai-services/chat-ai/index.html) |
| **Completions** | Raw-text completion on `/completions`: the model continues a prompt, without a chat template | [SAIA API](https://docs.hpc.gwdg.de/services/ai-services/saia/index.html) |
| **Responses API** | OpenAI's Responses format on `/responses`, stateless | not listed (seen 2026-11-22) |
| **Messages API** | Anthropic's Messages format on `/messages`, without the Anthropic SDK | not listed (seen 2026-11-22) |
| **Voice AI** | Audio transcription and translation (Whisper) | [Voice AI](https://docs.hpc.gwdg.de/services/ai-services/voice-ai/index.html) |
| **ARCANA** | RAG — knowledge base management and retrieval-augmented chat | [ARCANA](https://docs.hpc.gwdg.de/services/ai-services/arcana/index.html) |
| **Documents** | PDF/document conversion via Docling | [SAIA API](https://docs.hpc.gwdg.de/services/ai-services/saia/index.html) |
| **Models** | List available models, probe tool-calling support | [SAIA API](https://docs.hpc.gwdg.de/services/ai-services/saia/index.html) |
| **Tokenizers** | Download model tokenizers; count chat-template tokens, special-token overhead, and subword fertility (opt-in `[tokenizer]` extra) | [Chat AI Models](https://docs.hpc.gwdg.de/services/ai-services/chat-ai/models/index.html) |
| **Rate Limits** | Inspect current quota and usage | [SAIA API](https://docs.hpc.gwdg.de/services/ai-services/saia/index.html) |

## Repository Structure

```
saia-python/
├── saia_python/                  # Main package
│   ├── __init__.py               # Public API, version, functional wrappers
│   ├── client.py                 # SAIAClient — composes all services
│   ├── aio.py                    # AsyncSAIAClient — async twins (httpx)
│   ├── chat.py                   # ChatService — chat completions + streaming
│   ├── completions.py            # CompletionsService — raw-text completion
│   ├── responses_api.py          # ResponsesService — OpenAI Responses format
│   ├── messages.py               # MessagesService — Anthropic Messages format
│   ├── responses.py              # text_of, iter_text, usage_of — read any result
│   ├── structured.py             # Structured output from a Pydantic model
│   ├── voice.py                  # VoiceService — transcribe + translate
│   ├── arcana.py                 # ArcanaService — RAG / knowledge bases
│   ├── arcana_references.py      # ARCANA reference-citation parser
│   ├── models.py                 # ModelsService — list available models
│   ├── tokenizer.py              # Tokenizers — download, chat-template token counting
│   ├── documents.py              # DocumentService — Docling conversion
│   ├── openai_compat.py          # OpenAI SDK compatibility layer
│   ├── auth.py                   # Credential and config discovery
│   ├── rate_limits.py            # RateLimitInfo dataclass + parser
│   ├── exceptions.py             # SAIAError hierarchy + raise_for_status
│   ├── _http.py                  # Shared transport: retry policy, post_generation
│   ├── _payloads.py              # Request-body builders, shared sync/async
│   ├── _streaming.py             # Shared SSE iterator
│   ├── _async_http.py            # Async transport (httpx)
│   ├── _async_streaming.py       # Async SSE stream (httpx)
│   ├── _util.py                  # Small internal utilities
│   └── py.typed                  # PEP 561 typing marker
├── docs/                         # Sphinx documentation (PyData theme)
│   ├── conf.py
│   ├── index.rst
│   ├── quickstart.rst
│   ├── explanations.rst
│   ├── architecture.rst
│   ├── implementation.rst
│   ├── configuration.rst
│   ├── api/                      # API reference (one page per module)
│   ├── adr/                      # Architecture Decision Records
│   ├── proposals/                # Design proposals (not part of the site)
│   ├── development.rst
│   ├── dev_notes.rst
│   ├── testing.rst
│   ├── roadmap.rst
│   └── CHANGELOG.md
├── tests/                        # Unit tests
├── examples/
│   ├── saia_python_demo.ipynb         # Interactive demo
│   ├── openai_compatible_proxy.ipynb  # OpenAI-compatible proxy example
│   ├── config.toml.example            # Template for structured config
│   └── .env.example                   # Template for secrets (.env)
├── .github/workflows/            # CI/CD (tests, docs, PyPI publish)
├── pyproject.toml                # Package metadata + dependencies
├── CITATION.cff                  # Citation metadata (CFF 1.2.0)
├── .gitignore
└── README.md
```

## Documentation

Online documentation: <https://fschwar4.github.io/saia_python/>

Build the docs locally:

```bash
pip install -e ".[docs]"
sphinx-build -b html -w warnings_sphinx_build.txt docs docs/_build/html
python3 -m http.server 8000 --directory docs/_build/html
```

## Citation

If you use `saia-python` in your work, please cite it. Citation metadata lives in
[`CITATION.cff`](https://github.com/fschwar4/saia_python/blob/main/CITATION.cff); GitHub's "Cite this repository" button renders it
as APA or BibTeX. The Zenodo concept DOI
[10.5281/zenodo.20480724](https://doi.org/10.5281/zenodo.20480724) always
resolves to the latest release; `CITATION.cff` also lists the DOI of each
release.

## License

[AGPL-3.0-only](https://github.com/fschwar4/saia_python/blob/main/LICENSE)
