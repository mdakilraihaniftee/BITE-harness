# Model configuration

PARSEC-VL uses the inherited OpenVLHarness model adapter. Model aliases map to
exact served IDs, request protocols, prompt bundles and supported request options
in [model_registry.yaml](../openvlharness/services/model_registry.yaml).
The principal local profile is
[local_grounding_tools.yaml](../examples/local_grounding_tools.yaml).

## Local Qwen

The model server exposes an OpenAI-compatible Chat Completions API. Configure the
base URL and key in the ignored `.env`:

```dotenv
MODEL_BASE_URL=http://127.0.0.1:8222/v1
MODEL_API_KEY=empty
AUXILIARY_MODEL_BASE_URL=http://127.0.0.1:8222/v1
AUXILIARY_MODEL_API_KEY=empty
```

`empty` is the local development key value, not a hosted provider credential.
The exact served ID is `Qwen/Qwen3-VL-8B-Instruct`; the configuration alias is
`qwen3-vl-8b-instruct`. Keep the vLLM served identity aligned with the registry.
The [README](../README.md#real-inference-with-a-live-visualization) covers checkpoint
installation, GPUs, automatic service startup and inference.

New Qwen instances started by `--start-services` use a 32,768-token demo context.
Manual `scripts/service.sh qwen` uses `QWEN_CONTEXT_LENGTH` from `.env` (default
168,000). Existing instances keep their startup context. A larger context consumes
more serving resources; choose it for the intended workload.

## Agent settings

```yaml
agent:
  model_service: orchestrator
  max_context_length: 168000
services:
  models:
    orchestrator:
      alias: qwen3-vl-8b-instruct
      base: ${MODEL_BASE_URL}
      key: ${MODEL_API_KEY}
      max_tokens: 12800
      temperature: 0.7
      top_p: 0.8
```

This fragment illustrates the model fields; use a complete profile for execution.
`max_tokens` reserves output capacity, while `agent.max_context_length` limits the
agent's context construction. The server must admit the resulting request.
When `max_tokens` is omitted, the adapter uses 4096. If an agent context limit is
set, it must exceed the output reservation by at least 512 tokens. Omitting the
agent context limit leaves enforcement to the provider.

## Other registered models

The registry and [configs/agent/](../configs/agent/) retain upstream profiles for
additional Qwen, GPT and Kimi model families. Copy an appropriate profile and
select a registered alias. An alias fixes the exact served model ID, API protocol,
prompts and supported options; changing only a display name is insufficient.
Options outside that model family's contract fail during configuration loading.
Registered compatibility is not a claim that a particular provider endpoint is
currently available or that it was benchmarked in this project.

To add a model, register its exact served ID, protocol, prompt bundle and allowed
request options in the registry. Search-enabled profiles also use an auxiliary
Qwen model for multimodal summarization and extraction. The default local
no-search profile does not require a search-provider key. See the
[tool-service guide](../openvlharness/services/tools/README.md) for optional backends.

## Raw trace export

Qwen evaluation supports `--save-raw-trace`, which enables token-ID capture in the
saved effective configuration. Other model families are rejected for this option.
Normal inference does not require raw trace export. Evaluation commands and the
dataset format are documented in the
[evaluation dataset guide](../evaluation_kit/dataset/README.md).
