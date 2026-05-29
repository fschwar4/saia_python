"""Models service — list available SAIA models."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .exceptions import raise_for_status

if TYPE_CHECKING:
    import requests


class ModelsService:
    """Access the ``/models`` endpoint.

    Args:
        session: A :class:`requests.Session` with auth headers configured.
        base_url: The SAIA API base URL (e.g. ``https://chat-ai.academiccloud.de/v1``).
    """

    def __init__(self, session: requests.Session, base_url: str):
        self._session = session
        self._base_url = base_url.rstrip("/")

    def list(self) -> list[dict]:
        """Return the full model list as returned by the API.

        Returns:
            A list of model dicts, each containing at least an ``"id"`` key.
        """
        resp = self._session.get(f"{self._base_url}/models")
        raise_for_status(resp)
        data = resp.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return [data]

    def list_ids(self) -> list[str]:
        """Return a deduplicated list of model ID strings."""
        models = self.list()
        seen = set()
        ids = []
        for m in models:
            mid = (
                m.get("id")
                or m.get("modelId")
                or m.get("model_id")
                or m.get("model")
                or m.get("name")
                or m.get("model_name")
            )
            if mid and mid not in seen:
                seen.add(mid)
                ids.append(mid)
        return ids

    def list_tool_capable(self, *, verbose: bool = False) -> list[str]:
        """Identify models that support tool calling by probing each one.

        Sends a minimal tool-calling request to each available model and
        checks whether the response contains a ``tool_calls`` field. This
        is a trial-and-error approach because the SAIA API does not expose
        tool support as model metadata.

        Args:
            verbose: If ``True``, print per-model results during probing.

        Returns:
            A list of model ID strings that responded with a tool call.

        Note:
            This method consumes API quota (one request per model) and may
            take several minutes depending on the number of available models.
        """
        model_ids = self.list_ids()

        _PROBE_TOOLS = [{
            "type": "function",
            "function": {
                "name": "probe",
                "description": "Test probe.",
                "parameters": {
                    "type": "object",
                    "properties": {"x": {"type": "string"}},
                    "required": ["x"],
                },
            },
        }]
        _PROBE_MESSAGES = [{"role": "user", "content": "Call the probe tool with x='test'."}]

        try:
            from tqdm.auto import tqdm
        except ImportError:
            tqdm = None

        capable = []
        iterator = model_ids
        if tqdm is not None and not verbose:
            iterator = tqdm(model_ids, desc="Probing models", unit="model")

        for mid in iterator:
            try:
                resp = self._session.post(
                    f"{self._base_url}/chat/completions",
                    json={
                        "model": mid,
                        "messages": _PROBE_MESSAGES,
                        "tools": _PROBE_TOOLS,
                        "max_tokens": 50,
                    },
                    timeout=30,
                )
                data = resp.json()
                msg = data.get("choices", [{}])[0].get("message", {})
                has_tools = bool(msg.get("tool_calls"))
                if has_tools:
                    capable.append(mid)
                if verbose:
                    status = "tool_calls" if has_tools else "no tools"
                    print(f"  {mid:<45} {status}")
            except Exception as e:
                if verbose:
                    print(f"  {mid:<45} error: {e}")

        return capable

    def __repr__(self):
        return f"ModelsService(base_url={self._base_url!r})"
