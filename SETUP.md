# SETUP — the environment this project was built on

Everything in this repo was developed, driven, and verified by the OpenClaw
agent **homeBot** on an **NVIDIA DGX Spark** — the agent wrote the TPAP
client, calibrated the coil with a webcam, ran the ambient services, and
captured every photo/GIF referenced in the [README](README.md). This file
documents the exact stack so the whole setup (agent + models + services)
can be repeated on another Spark.

For the protocol/client itself, see [README.md](README.md).

## The stack

| Layer | Version / value |
|---|---|
| Host | NVIDIA DGX Spark (GB10, Grace Blackwell, 12.1, unified 128 GB) |
| OS | Ubuntu 24.04.5 LTS, arm64 |
| OpenClaw | **2026.9.4** (commit `3a9d69d`), Node v24.21.0 |
| Primary model | `vllm/unsloth/Qwen3.8-27B-NVFP4` — vLLM **0.28.0** on a second Spark over Tailscale (`tailnet-ip:8000/v1`), 256k context, 16k max output, reasoning + tool calls |
| Local fallback model | `vllm2/nvidia/Qwen3.6-35B-A3B-NVFP4` — vLLM on the same Spark at `127.0.0.1:8000/v1` |
| Embeddings (memory search) | Ollama `nomic-embed-text` |
| Python (this repo) | 3.12 venv with `requests`, `cryptography`, `ecdsa` (see `requirements.txt`) |
| Webcam (coil calibration) | any USB cam; `fswebcam -d /dev/video0` on this host |
| Device services | systemd user units: `coil-clock.service`, `nvidia-light.service`, `strip-heartbeat.service` (snapshots + restore guide in the `homebot-backup` repo) |

Local vLLM serve command (the `vllm2` fallback, for reference):

```bash
vllm serve nvidia/Qwen3.6-35B-A3B-NVFP4 \
  --moe-backend flashinfer_b12x --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder --reasoning-parser qwen3 \
  --host 127.0.0.1 --port 8000 --tensor-parallel-size 1 \
  --trust-remote-code --kv-cache-dtype fp8 --attention-backend flashinfer \
  --gpu-memory-utilization 0.6 --max-model-len 262144 \
  --max-num-seqs 4 --max-num-batched-tokens 8192 \
  --enable-chunked-prefill --async-scheduling --enable-prefix-caching \
  --load-format fastsafetensors
```

## OpenClaw model wiring

`~/.openclaw/openclaw.json` → `models.providers`: one provider per vLLM
endpoint (`baseUrl`, `api: openai-completions`, `contextWindow`,
`maxTokens`, `reasoning`), then `agents.defaults.model.primary` picks the
active model id (`vllm/<model>`). On this host:

```jsonc
"models": {
  "providers": {
    "vllm":  { "baseUrl": "http://tailnet-ip:8000/v1", "api": "openai-completions",
               "models": [{ "id": "unsloth/Qwen3.8-27B-NVFP4", "reasoning": true,
                            "input": ["text","image"], "contextWindow": 256000, "maxTokens": 16000 }] },
    "vllm2": { "baseUrl": "http://127.0.0.1:8000/v1", "api": "openai-completions",
               "models": [{ "id": "nvidia/Qwen3.6-35B-A3B-NVFP4", "reasoning": true,
                            "input": ["text","image"], "contextWindow": 256000, "maxTokens": 16000 }] }
  }
},
"agents": { "defaults": { "model": { "primary": "vllm/unsloth/Qwen3.8-27B-NVFP4" } } }
```

(No API key needed for the local endpoint; a dummy one is set because the
OpenAI-compatible provider expects the field.)

## Notes for repeating it

- **The model names look odd but are real**: this setup is from Oct 2026,
  when `unsloth/Qwen3.8-27B-NVFP4` and `nvidia/Qwen3.6-35B-A3B-NVFP4`
  were current NVFP4 builds for Spark. On a fresh machine, any NVFP4 model
  that fits 128 GB unified memory works — the client code does not care
  which model is answering, only that OpenClaw has a working model provider.
- **Keep a vision-capable model**: both providers are multimodal
  (text+image). The webcam verification loop (photo → model inspects →
  adjust → repeat) is what makes the calibration and live verification
  work; without image input the agent can't check the strip.
- **The second model is optional**: one local NVFP4 vLLM endpoint is
  enough; the two-provider setup just gives a fallback. Anything
  OpenAI-compatible (vLLM, llama.cpp, Ollama) works as the provider.
- **No cloud**: both models are local/self-hosted; nothing in this setup
  phones home. Tailscale is only used to reach the second box on the LAN.
- **Credentials stay local**: Tapo account credentials live in
  `~/.openclaw/settings/tapo-mcp.env` (`TAPO_MCP_USERNAME` /
  `TAPO_MCP_PASSWORD`); scripts read them via `TPAP_USER`/`TPAP_PASS` env
  vars with that file as fallback. They are never committed to any repo.

## Repeating the device services

The systemd user units that keep the ambient content alive are snapshotted
in the `homebot-backup` repo (`systemd/units/` + restore guide):

```bash
# fresh machine, after cloning homebot-backup:
install -D systemd/units/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now coil-clock nvidia-light
```

## Changelog

- **2026-10-06**: split out of the README (`The setup this was built on`
  section) into this dedicated file; README keeps a short
  [How this was built](README.md#how-this-was-built) pointer + TOC entry.
