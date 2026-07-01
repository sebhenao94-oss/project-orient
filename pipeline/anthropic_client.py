"""Anthropic native Messages API client behind the OpenAI-compatible seam.

The W3/W4 serializers emit a provider-neutral, OpenAI-shaped ``messages`` list
(system/user/assistant, with images as ``image_url`` base64 data URLs). The
direct Anthropic Messages API is a different wire shape: ``system`` is a
top-level parameter, images use a ``source`` block, and the response is a list
of content blocks rather than ``choices[0].message.content``.

This client implements ``OpenAICompatibleClientProtocol.chat_completions_create``
by translating that OpenAI-shaped request into a Messages API call and
re-wrapping the reply into the OpenAI chat-completion envelope the existing
parsers consume. It therefore drops in behind the same seam as
``UrllibOpenAICompatibleClient`` with no change to the extraction/relationship
runners or the response parsers.

Selected via ``LLM_PROVIDER=anthropic``. The ``anthropic`` SDK is imported
lazily so the package is only required when this provider is actually used.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

if __package__:
    from .llm_client import (
        DEFAULT_LLM_MAX_COMPLETION_TOKENS,
        DEFAULT_LLM_TIMEOUT_SECONDS,
        LLMAuthenticationError,
        LLMConfigurationError,
        LLMConnectionError,
        LLMMessageSerializationError,
        LLMProviderResponseError,
        LLMRateLimitError,
        LLMTimeoutError,
        _optional_float_env,
        _optional_int_env,
    )
else:  # pragma: no cover - exercised only when run as a top-level script
    from llm_client import (
        DEFAULT_LLM_MAX_COMPLETION_TOKENS,
        DEFAULT_LLM_TIMEOUT_SECONDS,
        LLMAuthenticationError,
        LLMConfigurationError,
        LLMConnectionError,
        LLMMessageSerializationError,
        LLMProviderResponseError,
        LLMRateLimitError,
        LLMTimeoutError,
        _optional_float_env,
        _optional_int_env,
    )


_DATA_URL_RE = re.compile(r"^data:(?P<media_type>[^;]+);base64,(?P<data>.+)$", re.S)


class AnthropicBatchItemResult:
    """One Message Batches result, keyed by the request's custom_id.

    ``status`` mirrors the Batch API result types: ``succeeded`` (``content``
    holds the assistant text) or ``errored`` / ``canceled`` / ``expired``
    (``error_message`` holds the reason).
    """

    __slots__ = ("custom_id", "status", "content", "error_message", "usage")

    def __init__(
        self,
        custom_id: Optional[str],
        status: str,
        content: Optional[str] = None,
        error_message: Optional[str] = None,
        usage: Optional[Dict[str, int]] = None,
    ) -> None:
        self.custom_id = custom_id
        self.status = status
        self.content = content
        self.error_message = error_message
        self.usage = usage


class AnthropicMessagesClient:
    """Adapter from the OpenAI-compatible seam to the Anthropic Messages API."""

    def __init__(
        self,
        *,
        api_key: str,
        ca_bundle: Optional[str] = None,
        max_tokens: int = DEFAULT_LLM_MAX_COMPLETION_TOKENS,
        cache_system: bool = True,
        anthropic_client: Optional[Any] = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise LLMConfigurationError("ANTHROPIC_API_KEY must not be blank")

        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - environment guard
            raise LLMConfigurationError(
                "The 'anthropic' package is required for LLM_PROVIDER=anthropic. "
                "Install it with: pip install anthropic"
            ) from exc

        self._anthropic = anthropic
        self._max_tokens = (
            max_tokens if max_tokens and max_tokens > 0 else DEFAULT_LLM_MAX_COMPLETION_TOKENS
        )
        self._cache_system = cache_system

        if anthropic_client is not None:
            # Injectable seam for tests.
            self._client = anthropic_client
            return

        http_client = None
        if ca_bundle:
            # Corporate / antivirus TLS interception (e.g. Avast SSL scanning)
            # re-signs HTTPS with a private root certifi does not trust. When a
            # CA bundle is provided, verify against it instead. Unset on machines
            # without interception so the default certifi bundle is used.
            try:
                import httpx
            except ImportError as exc:  # pragma: no cover - environment guard
                raise LLMConfigurationError(
                    "httpx is required to use LLM_CA_BUNDLE (installed with anthropic)."
                ) from exc
            http_client = httpx.Client(verify=ca_bundle, timeout=DEFAULT_LLM_TIMEOUT_SECONDS)

        self._client = anthropic.Anthropic(api_key=api_key, http_client=http_client)

    @classmethod
    def from_environment(cls) -> "AnthropicMessagesClient":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMConfigurationError("Missing required environment variable: ANTHROPIC_API_KEY")
        ca_bundle = os.getenv("LLM_CA_BUNDLE") or os.getenv("SSL_CERT_FILE") or None
        max_tokens = _optional_int_env("LLM_MAX_COMPLETION_TOKENS", DEFAULT_LLM_MAX_COMPLETION_TOKENS)
        cache_env = os.getenv("LLM_PROMPT_CACHE")
        cache_system = (
            True
            if cache_env is None or cache_env == ""
            else cache_env.strip().lower() not in ("0", "false", "no", "off")
        )
        return cls(
            api_key=api_key,
            ca_bundle=ca_bundle,
            max_tokens=max_tokens,
            cache_system=cache_system,
        )

    async def chat_completions_create(
        self,
        *,
        model: str,
        messages: List[Mapping[str, Any]],
        timeout_seconds: Optional[float] = None,
    ) -> Any:
        system, conversation = self._translate_messages(messages)
        timeout = timeout_seconds or _optional_float_env(
            "LLM_TIMEOUT_SECONDS", DEFAULT_LLM_TIMEOUT_SECONDS
        )
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._create(model, system, conversation, timeout),
        )

    def _create(
        self,
        model: str,
        system: str,
        conversation: List[Dict[str, Any]],
        timeout: float,
    ) -> Dict[str, Any]:
        if self._cache_system:
            conversation = self._apply_prefix_cache(conversation)
        kwargs: Dict[str, Any] = {
            "model": model,
            "max_tokens": self._max_tokens,
            "messages": conversation,
        }
        if system:
            kwargs["system"] = self._system_param(system)

        try:
            message = self._client.with_options(timeout=timeout).messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - re-raised as typed LLM errors below
            raise self._map_exception(exc) from exc

        return self._wrap_response(message)

    def _system_param(self, system: str) -> Any:
        """System prompt as a cache-controlled block list when prompt caching is
        enabled (the system prompt is the stable prefix shared across a run, so
        repeated calls in a batch/escalation pass read it at ~0.1x cost), else a
        plain string."""
        if self._cache_system:
            return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        return system

    def _apply_prefix_cache(self, conversation: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Place a cache breakpoint at the end of the stable demonstration prefix.

        The system prompt plus the few-shot user/assistant turns are
        byte-identical across every call in an extraction run; only the final
        target-image user message varies. Marking the last assistant
        (demonstration) turn caches that whole prefix, so calls after the first
        read it at ~0.1x. Without this the system block alone is often below the
        per-model cache minimum (2048 tokens for Haiku) so nothing caches, and
        the large few-shot images -- the bulk of the input -- are re-sent at full
        price every call. No-op when there is no assistant turn (e.g. a bare
        system+user drawing-tile request), where the system block's own
        cache_control still applies.
        """
        last_assistant = -1
        for index, message in enumerate(conversation):
            if message.get("role") == "assistant":
                last_assistant = index
        if last_assistant < 0:
            return conversation

        content = conversation[last_assistant].get("content")
        if isinstance(content, str):
            blocks: List[Dict[str, Any]] = [{"type": "text", "text": content}]
        elif isinstance(content, list) and content:
            blocks = [dict(block) for block in content]
        else:
            return conversation
        blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}

        updated = list(conversation)
        updated[last_assistant] = {**conversation[last_assistant], "content": blocks}
        return updated

    def _text_from_message(self, message: Any) -> str:
        content_blocks = getattr(message, "content", None) or []
        text_parts: List[str] = []
        for block in content_blocks:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", "") or "")
        return "".join(text_parts)

    @staticmethod
    def _usage_dict(usage: Any) -> Optional[Dict[str, int]]:
        if usage is None:
            return None
        keys = (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
        return {key: int(getattr(usage, key, 0) or 0) for key in keys}

    def _wrap_response(self, message: Any) -> Dict[str, Any]:
        # OpenAI chat-completion envelope expected by _assistant_content_from_response.
        envelope: Dict[str, Any] = {
            "choices": [{"message": {"role": "assistant", "content": self._text_from_message(message)}}]
        }
        usage = self._usage_dict(getattr(message, "usage", None))
        if usage is not None:
            envelope["usage"] = usage
        return envelope

    # ------------------------------------------------------------------ #
    # Message Batches API (asynchronous, ~50% cheaper; brief-mandated      #
    # default for production runs). Submit one batch, poll, collect by     #
    # custom_id. Results arrive in any order, so callers key on custom_id. #
    # ------------------------------------------------------------------ #

    def build_batch_request(
        self,
        *,
        custom_id: str,
        model: str,
        messages: List[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Translate one OpenAI-shaped request into a Batch API request entry."""
        system, conversation = self._translate_messages(messages)
        if self._cache_system:
            conversation = self._apply_prefix_cache(conversation)
        params: Dict[str, Any] = {
            "model": model,
            "max_tokens": self._max_tokens,
            "messages": conversation,
        }
        if system:
            params["system"] = self._system_param(system)
        return {"custom_id": custom_id, "params": params}

    def submit_message_batch(self, requests: List[Mapping[str, Any]]) -> str:
        try:
            batch = self._client.messages.batches.create(requests=list(requests))
        except Exception as exc:  # noqa: BLE001 - mapped to typed LLM errors
            raise self._map_exception(exc) from exc
        return batch.id

    def get_batch_processing_status(self, batch_id: str) -> str:
        try:
            return self._client.messages.batches.retrieve(batch_id).processing_status
        except Exception as exc:  # noqa: BLE001
            raise self._map_exception(exc) from exc

    def collect_batch_results(self, batch_id: str) -> Dict[str, AnthropicBatchItemResult]:
        try:
            raw_results = self._client.messages.batches.results(batch_id)
        except Exception as exc:  # noqa: BLE001
            raise self._map_exception(exc) from exc
        results: Dict[str, AnthropicBatchItemResult] = {}
        for item in raw_results:
            interpreted = self._interpret_batch_item(item)
            results[interpreted.custom_id] = interpreted
        return results

    def run_message_batch(
        self,
        requests: List[Mapping[str, Any]],
        *,
        poll_interval_seconds: float = 30.0,
        timeout_seconds: float = 86400.0,
        on_poll: Optional[Any] = None,
        sleep: Optional[Any] = None,
    ) -> Dict[str, AnthropicBatchItemResult]:
        """Submit a batch, poll until it ends, and return results by custom_id."""
        sleeper = sleep or time.sleep
        batch_id = self.submit_message_batch(requests)
        deadline = time.monotonic() + timeout_seconds
        while True:
            status = self.get_batch_processing_status(batch_id)
            if on_poll is not None:
                on_poll(batch_id, status)
            if status == "ended":
                break
            if time.monotonic() >= deadline:
                raise LLMTimeoutError(
                    f"Anthropic batch {batch_id} did not finish within {timeout_seconds}s"
                )
            sleeper(poll_interval_seconds)
        return self.collect_batch_results(batch_id)

    def _interpret_batch_item(self, item: Any) -> AnthropicBatchItemResult:
        custom_id = getattr(item, "custom_id", None)
        result = getattr(item, "result", None)
        result_type = getattr(result, "type", None)
        if result_type == "succeeded":
            message = getattr(result, "message", None)
            return AnthropicBatchItemResult(
                custom_id,
                "succeeded",
                content=self._text_from_message(message),
                usage=self._usage_dict(getattr(message, "usage", None)),
            )
        error = getattr(result, "error", None)
        message = str(error) if error is not None else f"batch item {result_type}"
        return AnthropicBatchItemResult(custom_id, result_type or "unknown", error_message=message)

    def _translate_messages(
        self, messages: List[Mapping[str, Any]]
    ) -> Tuple[str, List[Dict[str, Any]]]:
        system_parts: List[str] = []
        conversation: List[Dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if role == "system":
                system_parts.append(self._system_text(content))
                continue
            if role not in ("user", "assistant"):
                raise LLMMessageSerializationError(f"Unsupported message role for Anthropic: {role!r}")
            conversation.append({"role": role, "content": self._translate_content(content)})
        system = "\n\n".join(part for part in system_parts if part)
        return system, conversation

    def _system_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                part.get("text", "")
                for part in content
                if isinstance(part, Mapping) and part.get("type") == "text"
            )
        raise LLMMessageSerializationError("Unsupported system message content")

    def _translate_content(self, content: Any) -> Any:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            raise LLMMessageSerializationError("Unsupported message content")

        blocks: List[Dict[str, Any]] = []
        for part in content:
            if not isinstance(part, Mapping):
                raise LLMMessageSerializationError("Unsupported content part")
            part_type = part.get("type")
            if part_type == "text":
                blocks.append({"type": "text", "text": part.get("text", "")})
            elif part_type == "image_url":
                url = (part.get("image_url") or {}).get("url", "")
                match = _DATA_URL_RE.match(url)
                if not match:
                    raise LLMMessageSerializationError(
                        "Anthropic client requires base64 data-URL images (data:<mime>;base64,...)"
                    )
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": match.group("media_type"),
                            "data": match.group("data"),
                        },
                    }
                )
            else:
                raise LLMMessageSerializationError(f"Unsupported content part type: {part_type!r}")
        return blocks

    def _map_exception(self, exc: Exception) -> Exception:
        anthropic = self._anthropic
        if isinstance(exc, getattr(anthropic, "AuthenticationError", ())) or isinstance(
            exc, getattr(anthropic, "PermissionDeniedError", ())
        ):
            return LLMAuthenticationError("Anthropic provider rejected authentication")
        if isinstance(exc, getattr(anthropic, "RateLimitError", ())):
            return LLMRateLimitError("Anthropic provider rate limit exceeded")
        if isinstance(exc, getattr(anthropic, "APITimeoutError", ())):
            return LLMTimeoutError("Anthropic provider request timed out")
        if isinstance(exc, getattr(anthropic, "APIConnectionError", ())):
            return LLMConnectionError("Unable to reach Anthropic provider")
        if isinstance(exc, getattr(anthropic, "APIStatusError", ())):
            status = getattr(exc, "status_code", None)
            return LLMProviderResponseError(f"Anthropic provider returned HTTP status {status}")
        if isinstance(exc, getattr(anthropic, "AnthropicError", ())):
            return LLMProviderResponseError("Anthropic provider request failed")
        return LLMProviderResponseError("Anthropic provider request failed")
