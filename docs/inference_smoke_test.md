# Inference Smoke Test

## Purpose

Record the completed temporary development smoke test for Project ORIENT LLM
integration without storing credentials, active URLs, or runtime-specific
secrets in the repository.

## Test Summary

- Test date: June 8-9, 2026.
- Temporary environment: Google Colab Tesla T4.
- Smoke-tested model: `Qwen/Qwen3-VL-2B-Instruct`.
- Serving approach: Hugging Face Transformers plus FastAPI.
- vLLM status: attempted but not completed because of runtime compatibility
  issues.

## Results

- Direct text inference returned `ORIENT_MODEL_OK`.
- Direct vision inference succeeded after image resizing.
- Temporary API behavior:
  - `GET /v1/models` with valid credentials returned `200`.
  - `GET /v1/models` with invalid credentials returned `401`.
  - `POST /v1/chat/completions` returned `200` and `ORIENT_ENDPOINT_OK`.
  - Requests 1-5 returned `200`.
  - Request 6 returned `429` under the temporary configured rate limit.

## Limitations

- The runtime was temporary.
- The endpoint was localhost-only inside Colab.
- Runtime state disappears after reset.
- The endpoint is not externally reachable from the Windows repository.
- This was not production hosting.
- This was not proof of a completed vLLM deployment.
- Large images require resizing, cropping, or tiling before model inference.

## Current Conclusion

The development smoke-test requirement is complete. Repository client
integration, prompt development, production batching, and persistent hosting
remain incomplete.
