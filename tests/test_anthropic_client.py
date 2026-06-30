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
    LLMTimeoutError,
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


class _FakeResult:
    def __init__(self, result_type, message=None, error=None):
        self.type = result_type
        self.message = message
        self.error = error


class _FakeBatchItem:
    def __init__(self, custom_id, result):
        self.custom_id = custom_id
        self.result = result


class _FakeBatchHandle:
    def __init__(self, batch_id, processing_status):
        self.id = batch_id
        self.processing_status = processing_status


class _FakeBatches:
    def __init__(self, statuses, results):
        self._statuses = list(statuses)
        self._results = results
        self.created_requests = None

    def create(self, requests):
        self.created_requests = list(requests)
        return _FakeBatchHandle("batch_test", "in_progress")

    def retrieve(self, batch_id):
        status = self._statuses.pop(0) if len(self._statuses) > 1 else self._statuses[0]
        return _FakeBatchHandle(batch_id, status)

    def results(self, _batch_id):
        return iter(self._results)


class _FakeBatchMessages:
    def __init__(self, batches):
        self.batches = batches


class _FakeBatchClient:
    def __init__(self, statuses, results):
        self.messages = _FakeBatchMessages(_FakeBatches(statuses, results))


class MessageBatchTests(unittest.TestCase):
    def test_run_message_batch_polls_until_ended_and_maps_results(self):
        results = [
            _FakeBatchItem(
                "img0",
                _FakeResult("succeeded", message=_Message([_Block("text", '{"equipment": []}')])),
            ),
            _FakeBatchItem("img1", _FakeResult("errored", error="overloaded")),
        ]
        fake = _FakeBatchClient(statuses=["in_progress", "ended"], results=results)
        client = AnthropicMessagesClient(api_key="test-key", anthropic_client=fake)

        polled = []
        out = client.run_message_batch(
            [{"custom_id": "img0", "params": {}}, {"custom_id": "img1", "params": {}}],
            poll_interval_seconds=0.0,
            on_poll=lambda _bid, status: polled.append(status),
            sleep=lambda *_: None,
        )

        self.assertEqual(polled, ["in_progress", "ended"])
        self.assertEqual(fake.messages.batches.created_requests[0]["custom_id"], "img0")
        self.assertEqual(out["img0"].status, "succeeded")
        self.assertEqual(out["img0"].content, '{"equipment": []}')
        self.assertEqual(out["img1"].status, "errored")
        self.assertIn("overloaded", out["img1"].error_message)

    def test_run_message_batch_times_out(self):
        fake = _FakeBatchClient(statuses=["in_progress"], results=[])
        client = AnthropicMessagesClient(api_key="test-key", anthropic_client=fake)
        with self.assertRaises(LLMTimeoutError):
            client.run_message_batch(
                [{"custom_id": "x", "params": {}}],
                poll_interval_seconds=0.0,
                timeout_seconds=-1.0,
                sleep=lambda *_: None,
            )

    def test_build_batch_request_translates(self):
        client = _make_client()
        data_url, _ = _png_data_url()
        messages = [
            {"role": "system", "content": "S"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "go"},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ]
        req = client.build_batch_request(custom_id="img0", model="claude-haiku-4-5", messages=messages)
        self.assertEqual(req["custom_id"], "img0")
        params = req["params"]
        self.assertEqual(params["model"], "claude-haiku-4-5")
        self.assertEqual(params["system"], "S")
        self.assertIn("max_tokens", params)
        self.assertEqual(params["messages"][0]["content"][1]["type"], "image")


if __name__ == "__main__":
    unittest.main()
