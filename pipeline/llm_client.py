"""OpenAI-compatible vision client boundary for Project ORIENT W3 extraction."""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

if __package__:
    from .equipment_prompts import (
        AssistantJsonMessage,
        EquipmentMessagePlan,
        SystemTextMessage,
        UserImageTextMessage,
    )
    from .relationship_prompts import (
        AssistantJsonMessage as RelationshipAssistantJsonMessage,
        SystemTextMessage as RelationshipSystemTextMessage,
        UserImageTextMessage as RelationshipUserImageTextMessage,
        UserTextMessage as RelationshipUserTextMessage,
    )
    from .config import PROJECT_ROOT
    from .cost import record_usage
else:
    from equipment_prompts import (
        AssistantJsonMessage,
        EquipmentMessagePlan,
        SystemTextMessage,
        UserImageTextMessage,
    )
    from relationship_prompts import (
        AssistantJsonMessage as RelationshipAssistantJsonMessage,
        SystemTextMessage as RelationshipSystemTextMessage,
        UserImageTextMessage as RelationshipUserImageTextMessage,
        UserTextMessage as RelationshipUserTextMessage,
    )
    from config import PROJECT_ROOT
    from cost import record_usage


load_dotenv(PROJECT_ROOT / ".env")

SUPPORTED_IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
DEFAULT_LLM_TIMEOUT_SECONDS = 60.0
DEFAULT_LLM_MAX_RETRIES = 0
DEFAULT_LLM_MAX_COMPLETION_TOKENS = 2048


class OpenAICompatibleClientProtocol(Protocol):
    async def chat_completions_create(
        self,
        *,
        model: str,
        messages: List[Mapping[str, Any]],
        timeout_seconds: Optional[float] = None,
    ) -> Any:
        ...


class LLMClientError(RuntimeError):
    """Base error for OpenAI-compatible LLM client failures."""


class LLMConfigurationError(LLMClientError):
    """Raised when required LLM configuration is missing or invalid."""


class LLMMessageSerializationError(LLMClientError):
    """Raised when provider-neutral messages cannot be serialized."""


class LLMImageEncodingError(LLMMessageSerializationError):
    """Raised when a local image cannot be encoded for a multimodal request."""


class LLMAuthenticationError(LLMClientError):
    """Raised when the provider rejects authentication."""


class LLMRateLimitError(LLMClientError):
    """Raised when the provider rate-limits the request."""


class LLMTimeoutError(LLMClientError):
    """Raised when the provider request times out."""


class LLMConnectionError(LLMClientError):
    """Raised when the provider cannot be reached."""


class LLMProviderResponseError(LLMClientError):
    """Raised for non-success provider responses."""


class LLMMalformedResponseError(LLMClientError):
    """Raised when the provider response envelope is malformed."""


class LLMMissingAssistantContentError(LLMMalformedResponseError):
    """Raised when no nonblank assistant content is present."""


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise LLMConfigurationError(f"Missing required environment variable: {name}")
    return value


def _optional_float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise LLMConfigurationError(f"Environment variable {name} must be numeric") from exc
    if parsed <= 0:
        raise LLMConfigurationError(f"Environment variable {name} must be greater than 0")
    return parsed


def _optional_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise LLMConfigurationError(f"Environment variable {name} must be an integer") from exc
    if parsed < 0:
        raise LLMConfigurationError(f"Environment variable {name} must be non-negative")
    return parsed


def configured_llm_model() -> str:
    return _required_env("LLM_MODEL")


def build_llm_client_from_environment() -> "OpenAICompatibleClientProtocol":
    """Construct the env-selected vision client behind the shared seam.

    ``LLM_PROVIDER=anthropic`` -> native Anthropic Messages API client.
    Anything else (the default) -> the OpenAI-compatible client used for
    vLLM/Qwen and any OpenAI-SDK-compatible hosted provider.
    """
    provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if provider == "anthropic":
        if __package__:
            from .anthropic_client import AnthropicMessagesClient
        else:
            from anthropic_client import AnthropicMessagesClient
        return AnthropicMessagesClient.from_environment()
    return UrllibOpenAICompatibleClient.from_environment()


class UrllibOpenAICompatibleClient:
    """Small stdlib adapter for OpenAI-compatible Chat Completions endpoints."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        max_retries: int = DEFAULT_LLM_MAX_RETRIES,
    ) -> None:
        if not base_url or not base_url.strip():
            raise LLMConfigurationError("LLM_BASE_URL must not be blank")
        if not api_key or not api_key.strip():
            raise LLMConfigurationError("LLM_API_KEY must not be blank")
        if max_retries < 0:
            raise LLMConfigurationError("LLM_MAX_RETRIES must be non-negative")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.max_retries = max_retries

    @classmethod
    def from_environment(cls) -> "UrllibOpenAICompatibleClient":
        return cls(
            base_url=_required_env("LLM_BASE_URL"),
            api_key=_required_env("LLM_API_KEY"),
            max_retries=_optional_int_env("LLM_MAX_RETRIES", DEFAULT_LLM_MAX_RETRIES),
        )

    async def chat_completions_create(
        self,
        *,
        model: str,
        messages: List[Mapping[str, Any]],
        timeout_seconds: Optional[float] = None,
    ) -> Any:
        timeout = timeout_seconds or _optional_float_env(
            "LLM_TIMEOUT_SECONDS",
            DEFAULT_LLM_TIMEOUT_SECONDS,
        )
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._post_chat_completions(model, messages, timeout),
        )

    def _post_chat_completions(
        self,
        model: str,
        messages: List[Mapping[str, Any]],
        timeout_seconds: float,
    ) -> Any:
        body: Dict[str, Any] = {"model": model, "messages": messages}
        max_completion_tokens = _optional_int_env(
            "LLM_MAX_COMPLETION_TOKENS",
            DEFAULT_LLM_MAX_COMPLETION_TOKENS,
        )
        # 0 disables sending max_tokens so the provider default applies.
        if max_completion_tokens > 0:
            body["max_tokens"] = max_completion_tokens
        payload = json.dumps(body).encode("utf-8")
        request = Request(
            self._chat_completions_url(),
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(request, timeout=timeout_seconds) as response:
                    response_body = response.read().decode("utf-8")
                    return json.loads(response_body)
            except HTTPError as exc:
                if exc.code in {401, 403}:
                    raise LLMAuthenticationError("LLM provider rejected authentication") from exc
                if exc.code == 429:
                    last_error = LLMRateLimitError("LLM provider rate limit exceeded")
                    if attempt < self.max_retries:
                        continue
                    raise last_error from exc
                raise LLMProviderResponseError(
                    f"LLM provider returned HTTP status {exc.code}"
                ) from exc
            except TimeoutError as exc:
                last_error = LLMTimeoutError("LLM provider request timed out")
                if attempt < self.max_retries:
                    continue
                raise last_error from exc
            except URLError as exc:
                reason = getattr(exc, "reason", None)
                if isinstance(reason, TimeoutError):
                    last_error = LLMTimeoutError("LLM provider request timed out")
                else:
                    last_error = LLMConnectionError("Unable to reach LLM provider")
                if attempt < self.max_retries:
                    continue
                raise last_error from exc
            except json.JSONDecodeError as exc:
                raise LLMMalformedResponseError("LLM provider response was not valid JSON") from exc

        if last_error:
            raise last_error
        raise LLMProviderResponseError("LLM provider request failed")

    def _chat_completions_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"


def serialize_equipment_message_plan(
    message_plan: EquipmentMessagePlan,
) -> List[Mapping[str, Any]]:
    messages: List[Mapping[str, Any]] = []
    for message in message_plan.messages:
        if isinstance(message, SystemTextMessage):
            messages.append(_serialize_system_message(message))
        elif isinstance(message, UserImageTextMessage):
            messages.append(_serialize_user_image_text_message(message))
        elif isinstance(message, AssistantJsonMessage):
            messages.append(_serialize_assistant_json_message(message))
        else:
            raise LLMMessageSerializationError(
                f"Unsupported equipment message type: {type(message).__name__}"
            )
    return messages


def serialize_relationship_message_plan(
    message_plan: "RelationshipMessagePlan",
) -> List[Mapping[str, Any]]:
    messages: List[Mapping[str, Any]] = []
    for message in message_plan.messages:
        if isinstance(message, RelationshipSystemTextMessage):
            messages.append(
                {"role": "system", "content": _require_nonblank_text(message.text, "system message")}
            )
        elif isinstance(message, RelationshipUserTextMessage):
            messages.append(
                {"role": "user", "content": _require_nonblank_text(message.text, "user message text")}
            )
        elif isinstance(message, RelationshipUserImageTextMessage):
            messages.append(_serialize_user_image_text_message(message))
        elif isinstance(message, RelationshipAssistantJsonMessage):
            messages.append(_serialize_assistant_json_message(message))
        else:
            raise LLMMessageSerializationError(
                f"Unsupported relationship message type: {type(message).__name__}"
            )
    return messages


def _require_nonblank_text(text: str, context: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise LLMMessageSerializationError(f"{context} must be nonblank text")
    return text


def _serialize_system_message(message: SystemTextMessage) -> Mapping[str, Any]:
    return {"role": "system", "content": _require_nonblank_text(message.text, "system message")}


def _serialize_user_image_text_message(message: UserImageTextMessage) -> Mapping[str, Any]:
    text = _require_nonblank_text(message.text, "user message text")
    data_url = _image_data_url(message.image_path)
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
    }


def _serialize_assistant_json_message(message: AssistantJsonMessage) -> Mapping[str, Any]:
    return {
        "role": "assistant",
        "content": _require_nonblank_text(message.json_text, "assistant JSON example"),
    }


def _image_data_url(image_path: Path) -> str:
    image_path = Path(image_path)
    if not image_path.exists():
        raise LLMImageEncodingError(f"Image file does not exist: {image_path}")
    if not image_path.is_file():
        raise LLMImageEncodingError(f"Image path is not a file: {image_path}")

    suffix = image_path.suffix.lower()
    mime_type = SUPPORTED_IMAGE_MIME_TYPES.get(suffix)
    if mime_type is None:
        guessed_mime, _encoding = mimetypes.guess_type(str(image_path))
        if guessed_mime in set(SUPPORTED_IMAGE_MIME_TYPES.values()):
            mime_type = guessed_mime
        else:
            raise LLMImageEncodingError(f"Unsupported image type for LLM request: {image_path.suffix}")

    try:
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    except OSError as exc:
        raise LLMImageEncodingError(f"Unable to read image file for LLM request: {image_path}") from exc
    return f"data:{mime_type};base64,{encoded}"


async def request_equipment_extraction(
    *,
    message_plan: EquipmentMessagePlan,
    model: str,
    client: Optional[OpenAICompatibleClientProtocol] = None,
    timeout_seconds: Optional[float] = None,
) -> str:
    """Send one multimodal request and return raw assistant content."""
    if not model or not model.strip():
        raise LLMConfigurationError("model must not be blank")
    messages = serialize_equipment_message_plan(message_plan)
    llm_client = client or build_llm_client_from_environment()
    timeout = timeout_seconds or _optional_float_env(
        "LLM_TIMEOUT_SECONDS",
        DEFAULT_LLM_TIMEOUT_SECONDS,
    )

    try:
        response = await llm_client.chat_completions_create(
            model=model,
            messages=messages,
            timeout_seconds=timeout,
        )
    except LLMClientError:
        raise
    except Exception as exc:
        raise _map_transport_exception(exc) from exc

    record_usage(model, _get_value(response, "usage"))
    return _assistant_content_from_response(response)


async def request_relationship_extraction(
    *,
    message_plan: "RelationshipMessagePlan",
    model: str,
    client: Optional[OpenAICompatibleClientProtocol] = None,
    timeout_seconds: Optional[float] = None,
) -> str:
    """Send one relationship-mapping request and return raw assistant content."""
    if not model or not model.strip():
        raise LLMConfigurationError("model must not be blank")
    messages = serialize_relationship_message_plan(message_plan)
    llm_client = client or build_llm_client_from_environment()
    timeout = timeout_seconds or _optional_float_env(
        "LLM_TIMEOUT_SECONDS",
        DEFAULT_LLM_TIMEOUT_SECONDS,
    )

    try:
        response = await llm_client.chat_completions_create(
            model=model,
            messages=messages,
            timeout_seconds=timeout,
        )
    except LLMClientError:
        raise
    except Exception as exc:
        raise _map_transport_exception(exc) from exc

    record_usage(model, _get_value(response, "usage"))
    return _assistant_content_from_response(response)


def _map_transport_exception(exc: Exception) -> LLMClientError:
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    exc_name = type(exc).__name__.lower()
    if status_code in {401, 403} or "auth" in exc_name:
        return LLMAuthenticationError("LLM provider rejected authentication")
    if status_code == 429 or "rate" in exc_name:
        return LLMRateLimitError("LLM provider rate limit exceeded")
    if isinstance(exc, TimeoutError) or "timeout" in exc_name:
        return LLMTimeoutError("LLM provider request timed out")
    if isinstance(exc, OSError) or "connection" in exc_name:
        return LLMConnectionError("Unable to reach LLM provider")
    return LLMProviderResponseError("LLM provider request failed")


def _get_value(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _assistant_content_from_response(response: Any) -> str:
    if response is None:
        raise LLMMalformedResponseError("LLM provider response is missing")
    choices = _get_value(response, "choices")
    if not isinstance(choices, list) or not choices:
        raise LLMMalformedResponseError("LLM provider response must include at least one choice")
    first_choice = choices[0]
    message = _get_value(first_choice, "message")
    if message is None:
        raise LLMMalformedResponseError("LLM provider choice is missing assistant message")
    role = _get_value(message, "role")
    if role is not None and role != "assistant":
        raise LLMMalformedResponseError("LLM provider message role is not assistant")
    content = _get_value(message, "content")
    if not isinstance(content, str) or not content.strip():
        raise LLMMissingAssistantContentError("LLM provider response is missing assistant content")
    return content