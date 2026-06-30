import asyncio
import base64
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

import httpx  # noqa: E402

from anthropic_client import AnthropicMessagesClient  # noqa: E402
from llm_client import (  # noqa: E402
    LLMConnectionError,
    LLMMessageSerializationError,
    build_llm_client_from_environment,
)


class _Block:
    def __init__(self, block_type, text):
        self.type = block_type
        self.text = text


class _Message:
    def __init__(self, content):
        self.content = content


class _FakeMessages:
    def __init__(self, message=None, exc=None):
        self._message = message
        self._exc = exc
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if self._exc is not None:
            raise self._exc
        return self._message


class _FakeAnthropicClient:
    """Stands in for anthropic.Anthropic; supports with_options(...).messages.create(...)."""

    def __init__(self, message=None, exc=None):
        self.messages = _FakeMessages(message=message, exc=exc)

    def with_options(self, **_kwargs):
        return self


def _make_client(message=None, exc=None):
    return AnthropicMessagesClient(
        api_key="test-key",
        anthropic_client=_FakeAnthropicClient(message=message, exc=exc),
    )


def _png_data_url():
    raw = b"\x89PNG\r\n\x1a\n fake-bytes"
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii"), raw


class TranslateMessagesTests(unittest.TestCase):
    def test_extracts_system_and_translates_image_and_text(self):
        client = _make_client()
        data_url, raw = _png_data_url()
        messages = [
            {"role": "system", "content": "You extract equipment."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "List the equipment."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
            {"role": "assistant", "content": '{"equipment": []}'},
        ]

        system, conversation = client._translate_messages(messages)

        self.assertEqual(system, "You extract equipment.")
        self.assertEqual(len(conversation), 2)

        user = conversation[0]
        self.assertEqual(user["role"], "user")
        self.assertEqual(user["content"][0], {"type": "text", "text": "List the equipment."})
        image_block = user["content"][1]
        self.assertEqual(image_block["type"], "image")
        self.assertEqual(image_block["source"]["type"], "base64")
        self.assertEqual(image_block["source"]["media_type"], "image/png")
        self.assertEqual(
            base64.b64decode(image_block["source"]["data"]),
            raw,
        )

        # Assistant few-shot string content passes through unchanged.
        self.assertEqual(conversation[1], {"role": "assistant", "content": '{"equipment": []}'})

    def test_non_data_url_image_rejected(self):
        client = _make_client()
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
                ],
            }
        ]
        with self.assertRaises(LLMMessageSerializationError):
            client._translate_messages(messages)


class ChatCompletionsCreateTests(unittest.TestCase):
    def test_wraps_text_blocks_into_openai_envelope(self):
        message = _Message([_Block("text", '{"equipment":'), _Block("text", " []}")])
        client = _make_client(message=message)

        response = asyncio.run(
            client.chat_completions_create(
                model="claude-haiku-4-5",
                messages=[{"role": "user", "content": "hi"}],
            )
        )

        content = response["choices"][0]["message"]["content"]
        self.assertEqual(content, '{"equipment": []}')
        # max_tokens is required by the Messages API and must be sent.
        self.assertIn("max_tokens", client._client.messages.last_kwargs)

    def test_connection_error_is_mapped(self):
        exc = httpx.ConnectError("boom")
        api_exc = __import__("anthropic").APIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        )
        api_exc.__cause__ = exc
        client = _make_client(exc=api_exc)

        with self.assertRaises(LLMConnectionError):
            asyncio.run(
                client.chat_completions_create(
                    model="claude-haiku-4-5",
                    messages=[{"role": "user", "content": "hi"}],
                )
            )


class FactorySelectionTests(unittest.TestCase):
    def test_selects_anthropic_when_provider_is_anthropic(self):
        with mock.patch.dict(
            "os.environ",
            {"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key"},
            clear=False,
        ):
            client = build_llm_client_from_environment()
        self.assertIsInstance(client, AnthropicMessagesClient)

    def test_defaults_to_openai_compatible_client(self):
        with mock.patch.dict(
            "os.environ",
            {
                "LLM_PROVIDER": "",
                "LLM_BASE_URL": "http://localhost:8000/v1",
                "LLM_API_KEY": "sk-local",
            },
            clear=False,
        ):
            client = build_llm_client_from_environment()
        self.assertEqual(type(client).__name__, "UrllibOpenAICompatibleClient")


if __name__ == "__main__":
    unittest.main()
