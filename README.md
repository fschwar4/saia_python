# saia-python

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
response = client.chat.completions(
    model="meta-llama-3.1-8b-instruct",
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
chat_completion(model="meta-llama-3.1-8b-instruct", messages=[...])
```

## Supported Services

| Service | Description | GWDG Docs |
|---------|-------------|-----------|
| **Chat AI** | Chat completions with streaming and tool calling | [Chat AI](https://docs.hpc.gwdg.de/services/ai-services/chat-ai/index.html) |
| **Voice AI** | Audio transcription and translation (Whisper) | [Voice AI](https://docs.hpc.gwdg.de/services/ai-services/voice-ai/index.html) |
| **ARCANA** | RAG — knowledge base management and retrieval-augmented chat | [ARCANA](https://docs.hpc.gwdg.de/services/ai-services/arcana/index.html) |
| **Documents** | PDF/document conversion via Docling | [SAIA API](https://docs.hpc.gwdg.de/services/ai-services/saia/index.html) |
| **Models** | List available models, probe tool-calling support | [SAIA API](https://docs.hpc.gwdg.de/services/ai-services/saia/index.html) |
| **Rate Limits** | Inspect current quota and usage | [SAIA API](https://docs.hpc.gwdg.de/services/ai-services/saia/index.html) |

## Repository Structure

```
saia-python/
├── saia_python/                  # Main package
│   ├── __init__.py               # Public API, version, functional wrappers
│   ├── client.py                 # SAIAClient — composes all services
│   ├── chat.py                   # ChatService — completions + streaming
│   ├── voice.py                  # VoiceService — transcribe + translate
│   ├── arcana.py                 # ArcanaService — RAG / knowledge bases
│   ├── models.py                 # ModelsService — list available models
│   ├── documents.py              # DocumentService — Docling conversion
│   ├── openai_compat.py          # OpenAI SDK compatibility layer
│   ├── auth.py                   # Credential and config discovery
│   ├── rate_limits.py            # RateLimitInfo dataclass + parser
│   ├── exceptions.py             # SAIAError hierarchy + raise_for_status
│   └── _streaming.py             # Shared SSE iterator
├── docs/                         # Sphinx documentation (PyData theme)
│   ├── conf.py
│   ├── index.rst
│   ├── quickstart.rst
│   ├── explanations.rst
│   ├── architecture.rst
│   ├── implementation.rst
│   ├── configuration.rst
│   ├── api/                      # API reference (one page per module)
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
├── .github/workflows/            # CI/CD (tests + docs deployment)
├── pyproject.toml                # Package metadata + dependencies
├── .gitignore
└── README.md
```

## Documentation

Build the docs locally:

```bash
pip install -e ".[docs]"
sphinx-build -b html -w warnings_sphinx_build.txt docs docs/_build/html
python3 -m http.server 8000 --directory docs/_build/html
```

## License

AGPL-3.0
