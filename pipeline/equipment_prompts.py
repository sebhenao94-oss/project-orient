"""Offline prompt-package loading for Project ORIENT equipment extraction.

This module validates committed prompt artifacts and builds provider-neutral
message plans. It intentionally does not encode images, call an LLM, or perform
network, S3, database, preprocessing, or response-parsing work.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, List, Tuple, Union

from pydantic import ValidationError

if __package__:
    from .models import EquipmentExtractionResponse
else:
    from models import EquipmentExtractionResponse


@dataclass(frozen=True)
class PromptVersionFiles:
    system_prompt_filename: str
    user_template_filename: str
    manifest_filename: str


SUPPORTED_PROMPT_VERSIONS: Dict[str, PromptVersionFiles] = {
    "equipment_extraction_v2": PromptVersionFiles(
        system_prompt_filename="v2_system.md",
        user_template_filename="v2_user_template.md",
        manifest_filename="v2_few_shot_examples.json",
    ),
    "equipment_extraction_v3": PromptVersionFiles(
        system_prompt_filename="v3_system.md",
        user_template_filename="v3_user_template.md",
        manifest_filename="v3_few_shot_examples.json",
    ),
}


class EquipmentPromptError(ValueError):
    """Base error for equipment prompt-package loading failures."""


class UnsupportedPromptVersionError(EquipmentPromptError):
    """Raised when a requested prompt version is not supported."""


class PromptPackageFileError(EquipmentPromptError):
    """Raised when a prompt package file is missing or unreadable."""


class PromptManifestError(EquipmentPromptError):
    """Raised when a few-shot manifest is malformed or invalid."""


class ExampleImageResolutionError(EquipmentPromptError):
    """Raised when an example image path is unsafe or unavailable."""


@dataclass(frozen=True)
class EquipmentPromptExample:
    image_filename: str
    resolved_image_path: Path
    user_text: str
    expected_response: EquipmentExtractionResponse


@dataclass(frozen=True)
class EquipmentPromptPackage:
    prompt_version: str
    system_prompt: str
    user_template: str
    examples: Tuple[EquipmentPromptExample, ...]


@dataclass(frozen=True)
class SystemTextMessage:
    text: str
    role: str = field(default="system", init=False)


@dataclass(frozen=True)
class UserImageTextMessage:
    image_path: Path
    text: str
    role: str = field(default="user", init=False)


@dataclass(frozen=True)
class AssistantJsonMessage:
    expected_response: EquipmentExtractionResponse
    json_text: str
    role: str = field(default="assistant", init=False)


EquipmentMessage = Union[SystemTextMessage, UserImageTextMessage, AssistantJsonMessage]


@dataclass(frozen=True)
class EquipmentMessagePlan:
    prompt_version: str
    messages: Tuple[EquipmentMessage, ...]


def load_equipment_prompt_package(
    prompt_version: str,
    prompt_root: Path,
    example_image_dir: Path,
) -> EquipmentPromptPackage:
    """Load and validate one versioned equipment-extraction prompt package."""
    version_files = _version_files(prompt_version)
    prompt_root = Path(prompt_root)
    example_image_dir = Path(example_image_dir).resolve()

    system_prompt = _read_required_text(
        prompt_root / version_files.system_prompt_filename,
        prompt_version,
        "system prompt",
    )
    user_template = _read_required_text(
        prompt_root / version_files.user_template_filename,
        prompt_version,
        "user template",
    )
    manifest = _read_required_manifest(
        prompt_root / version_files.manifest_filename,
        prompt_version,
    )
    examples = _validate_manifest(manifest, prompt_version, example_image_dir)

    return EquipmentPromptPackage(
        prompt_version=prompt_version,
        system_prompt=system_prompt,
        user_template=user_template,
        examples=tuple(examples),
    )


def build_equipment_message_plan(
    prompt_package: EquipmentPromptPackage,
    target_image_path: Path,
) -> EquipmentMessagePlan:
    """Build an ordered provider-neutral multimodal message plan."""
    target_image_path = _resolve_target_image_path(target_image_path)
    messages: List[EquipmentMessage] = [SystemTextMessage(text=prompt_package.system_prompt)]

    for example in prompt_package.examples:
        messages.append(
            UserImageTextMessage(
                image_path=example.resolved_image_path,
                text=example.user_text,
            )
        )
        messages.append(
            AssistantJsonMessage(
                expected_response=example.expected_response,
                json_text=_equipment_response_json(example.expected_response),
            )
        )

    messages.append(
        UserImageTextMessage(
            image_path=target_image_path,
            text=prompt_package.user_template,
        )
    )

    return EquipmentMessagePlan(
        prompt_version=prompt_package.prompt_version,
        messages=tuple(messages),
    )


def _version_files(prompt_version: str) -> PromptVersionFiles:
    try:
        return SUPPORTED_PROMPT_VERSIONS[prompt_version]
    except KeyError as exc:
        raise UnsupportedPromptVersionError(
            f"Unsupported equipment prompt version: {prompt_version}"
        ) from exc


def _read_required_text(path: Path, prompt_version: str, description: str) -> str:
    try:
        if not path.exists():
            raise PromptPackageFileError(
                f"{prompt_version}: missing {description} file: {path.name}"
            )
        if not path.is_file():
            raise PromptPackageFileError(
                f"{prompt_version}: {description} path is not a file: {path.name}"
            )
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptPackageFileError(
            f"{prompt_version}: unable to read {description} file: {path.name}"
        ) from exc

    if not text.strip():
        raise PromptPackageFileError(
            f"{prompt_version}: {description} file must not be blank: {path.name}"
        )
    return text


def _read_required_manifest(path: Path, prompt_version: str) -> Mapping[str, Any]:
    try:
        if not path.exists():
            raise PromptPackageFileError(
                f"{prompt_version}: missing few-shot manifest file: {path.name}"
            )
        if not path.is_file():
            raise PromptPackageFileError(
                f"{prompt_version}: few-shot manifest path is not a file: {path.name}"
            )
        manifest_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptPackageFileError(
            f"{prompt_version}: unable to read few-shot manifest file: {path.name}"
        ) from exc

    try:
        manifest = json.loads(manifest_text)
    except json.JSONDecodeError as exc:
        raise PromptManifestError(
            f"{prompt_version}: malformed JSON manifest: {path.name}"
        ) from exc

    if not isinstance(manifest, Mapping):
        raise PromptManifestError(
            f"{prompt_version}: manifest top-level value must be an object: {path.name}"
        )
    return manifest


def _validate_manifest(
    manifest: Mapping[str, Any],
    requested_prompt_version: str,
    example_image_dir: Path,
) -> List[EquipmentPromptExample]:
    manifest_version = manifest.get("prompt_version")
    if not isinstance(manifest_version, str) or not manifest_version.strip():
        raise PromptManifestError(
            f"{requested_prompt_version}: manifest field prompt_version is required"
        )
    if manifest_version != requested_prompt_version:
        raise PromptManifestError(
            f"{requested_prompt_version}: manifest prompt_version {manifest_version} "
            "does not match requested version"
        )

    raw_examples = manifest.get("examples")
    if not isinstance(raw_examples, list):
        raise PromptManifestError(
            f"{requested_prompt_version}: manifest field examples must be a list"
        )
    if not raw_examples:
        raise PromptManifestError(
            f"{requested_prompt_version}: manifest examples list must not be empty"
        )

    examples: List[EquipmentPromptExample] = []
    seen_filenames = set()
    for index, raw_example in enumerate(raw_examples, start=1):
        if not isinstance(raw_example, Mapping):
            raise PromptManifestError(
                f"{requested_prompt_version}: example {index} must be an object"
            )

        image_filename = _required_nonblank_string(
            raw_example,
            "image_filename",
            requested_prompt_version,
            index,
        )
        user_text = _required_nonblank_string(
            raw_example,
            "user_text",
            requested_prompt_version,
            index,
        )
        if "expected_response" not in raw_example:
            raise PromptManifestError(
                f"{requested_prompt_version}: example {index} missing required field "
                "expected_response"
            )

        duplicate_key = image_filename.replace("\\", "/")
        if duplicate_key in seen_filenames:
            raise PromptManifestError(
                f"{requested_prompt_version}: duplicate example image_filename: "
                f"{image_filename}"
            )
        seen_filenames.add(duplicate_key)

        try:
            expected_response = EquipmentExtractionResponse(
                **raw_example["expected_response"]
            )
        except (TypeError, ValidationError) as exc:
            raise PromptManifestError(
                f"{requested_prompt_version}: example {index} has invalid "
                "expected_response"
            ) from exc

        examples.append(
            EquipmentPromptExample(
                image_filename=image_filename,
                resolved_image_path=_resolve_example_image_path(
                    image_filename,
                    example_image_dir,
                    requested_prompt_version,
                    index,
                ),
                user_text=user_text,
                expected_response=expected_response,
            )
        )

    return examples


def _required_nonblank_string(
    raw_example: Mapping[str, Any],
    field_name: str,
    prompt_version: str,
    example_index: int,
) -> str:
    if field_name not in raw_example:
        raise PromptManifestError(
            f"{prompt_version}: example {example_index} missing required field {field_name}"
        )
    value = raw_example[field_name]
    if not isinstance(value, str) or not value.strip():
        raise PromptManifestError(
            f"{prompt_version}: example {example_index} field {field_name} must be "
            "a nonblank string"
        )
    return value


def _resolve_example_image_path(
    image_filename: str,
    example_image_dir: Path,
    prompt_version: str,
    example_index: int,
) -> Path:
    if PurePosixPath(image_filename).is_absolute() or PureWindowsPath(
        image_filename
    ).is_absolute():
        raise ExampleImageResolutionError(
            f"{prompt_version}: example {example_index} image_filename must be "
            f"relative: {image_filename}"
        )

    parts = [
        part
        for part in image_filename.replace("\\", "/").split("/")
        if part and part != "."
    ]
    if not parts or any(part == ".." for part in parts):
        raise ExampleImageResolutionError(
            f"{prompt_version}: example {example_index} image_filename is unsafe: "
            f"{image_filename}"
        )

    candidate = example_image_dir.joinpath(*parts).resolve()
    _ensure_path_under_root(
        candidate,
        example_image_dir,
        f"{prompt_version}: example {example_index} image",
    )
    if not candidate.exists():
        raise ExampleImageResolutionError(
            f"{prompt_version}: example {example_index} image file does not exist: "
            f"{image_filename}"
        )
    if not candidate.is_file():
        raise ExampleImageResolutionError(
            f"{prompt_version}: example {example_index} image path is not a file: "
            f"{image_filename}"
        )
    return candidate


def _resolve_target_image_path(target_image_path: Path) -> Path:
    target_image_path = Path(target_image_path).resolve()
    if not target_image_path.exists():
        raise ExampleImageResolutionError(
            f"Target image file does not exist: {target_image_path}"
        )
    if not target_image_path.is_file():
        raise ExampleImageResolutionError(
            f"Target image path is not a file: {target_image_path}"
        )
    return target_image_path


def _ensure_path_under_root(candidate: Path, root: Path, context: str) -> None:
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ExampleImageResolutionError(
            f"{context} resolved outside the allowed image directory"
        ) from exc


def _equipment_response_json(response: EquipmentExtractionResponse) -> str:
    return json.dumps(
        response.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
