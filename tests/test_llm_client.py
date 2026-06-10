import asyncio
import base64
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from equipment_prompts import (  # noqa: E402
    AssistantJsonMessage,
    EquipmentMessagePlan,
    SystemTextMessage,
    UserImageTextMessage,
)
from llm_client import (  # noqa: E402
    LLMAuthenticationError,
    LLMConnectionError,
    LLMImageEncodingError,
    LLMMalformedResponseError,
    LLMMessageSerializationError,
    LLMMissingAssistantContentError,
    LLMRateLimitError,
    LLMTimeoutError,
    request_equipment_extraction,
    serialize_equipment_message_plan,
)
from models import EquipmentExtractionResponse  # noqa: E402


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    async def chat_completions_create(self, *, model, messages, timeout_seconds=None):
        self.calls.append(
            {"model": model, "messages": messages, "timeout_seconds": timeout_seconds}
        )
        if self.error:
            raise self.error
        return self.response


def valid_response():
    return EquipmentExtractionResponse(
        equipment=[
            {
                "raw_label": "AHU 02 A",
                "canonical_name": "AHU_02A",
                "equipment_type": "AHU",
                "confidence": 0.98,
            }
        ]
    )


def write_file(root: Path, name: str, content=b"image bytes") -> Path:
    path = root / name
    path.write_bytes(content)
    return path


class TestMessageSerialization(unittest.TestCase):
    def test_system_user_and_assistant_messages_serialize_in_order(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = write_file(Path(tmp_dir), "ahu.png", b"abc")
            expected = valid_response()
            plan = EquipmentMessagePlan(
                prompt_version="equipment_extraction_v2",
                messages=(
                    SystemTextMessage(text="system"),
                    UserImageTextMessage(image_path=image_path, text="look"),
                    AssistantJsonMessage(
                        expected_response=expected,
                        json_text='{"equipment":[]}',
                    ),
                ),
            )

            messages = serialize_equipment_message_plan(plan)

        self.assertEqual([message["role"] for message in messages], ["system", "user", "assistant"])
        self.assertEqual(messages[0], {"role": "system", "content": "system"})
        self.assertEqual(messages[1]["content"][0], {"type": "text", "text": "look"})
        image_url = messages[1]["content"][1]["image_url"]["url"]
        self.assertTrue(image_url.startswith("data:image/png;base64,"))
        self.assertEqual(image_url.split(",", 1)[1], base64.b64encode(b"abc").decode("ascii"))
        self.assertEqual(messages[2], {"role": "assistant", "content": '{"equipment":[]}'})

    def test_jpg_uses_jpeg_mime_type(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = write_file(Path(tmp_dir), "vav.JPG")
            plan = EquipmentMessagePlan(
                prompt_version="equipment_extraction_v2",
                messages=(UserImageTextMessage(image_path=image_path, text="look"),),
            )

            messages = serialize_equipment_message_plan(plan)

        self.assertTrue(messages[0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    def test_missing_image_fails(self):
        plan = EquipmentMessagePlan(
            prompt_version="equipment_extraction_v2",
            messages=(UserImageTextMessage(image_path=Path("missing.png"), text="look"),),
        )

        with self.assertRaises(LLMImageEncodingError):
            serialize_equipment_message_plan(plan)

    def test_directory_image_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            plan = EquipmentMessagePlan(
                prompt_version="equipment_extraction_v2",
                messages=(UserImageTextMessage(image_path=Path(tmp_dir), text="look"),),
            )

            with self.assertRaises(LLMImageEncodingError):
                serialize_equipment_message_plan(plan)

    def test_unsupported_image_type_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = write_file(Path(tmp_dir), "image.gif")
            plan = EquipmentMessagePlan(
                prompt_version="equipment_extraction_v2",
                messages=(UserImageTextMessage(image_path=image_path, text="look"),),
            )

            with self.assertRaises(LLMImageEncodingError):
                serialize_equipment_message_plan(plan)

    def test_blank_text_fails(self):
        plan = EquipmentMessagePlan(
            prompt_version="equipment_extraction_v2",
            messages=(SystemTextMessage(text="   "),),
        )

        with self.assertRaises(LLMMessageSerializationError):
            serialize_equipment_message_plan(plan)


class TestRequestEquipmentExtraction(unittest.IsolatedAsyncioTestCase):
    def _plan(self, root: Path):
        image_path = write_file(root, "ahu.png")
        return EquipmentMessagePlan(
            prompt_version="equipment_extraction_v2",
            messages=(
                SystemTextMessage(text="system"),
                UserImageTextMessage(image_path=image_path, text="look"),
            ),
        )

    async def test_successful_response_returns_raw_assistant_text(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = FakeClient(
                response={"choices": [{"message": {"role": "assistant", "content": " raw json "}}]}
            )
            result = await request_equipment_extraction(
                message_plan=self._plan(Path(tmp_dir)),
                model="qwen-test",
                client=client,
                timeout_seconds=12,
            )

        self.assertEqual(result, " raw json ")
        self.assertEqual(client.calls[0]["model"], "qwen-test")
        self.assertEqual(client.calls[0]["timeout_seconds"], 12)

    async def test_empty_choices_fail(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = FakeClient(response={"choices": []})
            with self.assertRaises(LLMMalformedResponseError):
                await request_equipment_extraction(
                    message_plan=self._plan(Path(tmp_dir)),
                    model="qwen-test",
                    client=client,
                )

    async def test_missing_message_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = FakeClient(response={"choices": [{}]})
            with self.assertRaises(LLMMalformedResponseError):
                await request_equipment_extraction(
                    message_plan=self._plan(Path(tmp_dir)),
                    model="qwen-test",
                    client=client,
                )

    async def test_null_content_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = FakeClient(response={"choices": [{"message": {"role": "assistant", "content": None}}]})
            with self.assertRaises(LLMMissingAssistantContentError):
                await request_equipment_extraction(
                    message_plan=self._plan(Path(tmp_dir)),
                    model="qwen-test",
                    client=client,
                )

    async def test_blank_content_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = FakeClient(response={"choices": [{"message": {"role": "assistant", "content": "   "}}]})
            with self.assertRaises(LLMMissingAssistantContentError):
                await request_equipment_extraction(
                    message_plan=self._plan(Path(tmp_dir)),
                    model="qwen-test",
                    client=client,
                )

    async def test_authentication_failure_is_mapped(self):
        class AuthFailure(Exception):
            status_code = 401

        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(LLMAuthenticationError):
                await request_equipment_extraction(
                    message_plan=self._plan(Path(tmp_dir)),
                    model="qwen-test",
                    client=FakeClient(error=AuthFailure("nope")),
                )

    async def test_rate_limit_failure_is_mapped(self):
        class RateFailure(Exception):
            status_code = 429

        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(LLMRateLimitError):
                await request_equipment_extraction(
                    message_plan=self._plan(Path(tmp_dir)),
                    model="qwen-test",
                    client=FakeClient(error=RateFailure("slow down")),
                )

    async def test_timeout_failure_is_mapped(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(LLMTimeoutError):
                await request_equipment_extraction(
                    message_plan=self._plan(Path(tmp_dir)),
                    model="qwen-test",
                    client=FakeClient(error=TimeoutError("timeout")),
                )

    async def test_connection_failure_is_mapped(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(LLMConnectionError):
                await request_equipment_extraction(
                    message_plan=self._plan(Path(tmp_dir)),
                    model="qwen-test",
                    client=FakeClient(error=OSError("network")),
                )


if __name__ == "__main__":
    unittest.main()