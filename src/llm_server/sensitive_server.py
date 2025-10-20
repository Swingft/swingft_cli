#!/usr/bin/env python3
"""
Minimal LLM server focused on RAW input/output viewing.

Endpoints
  - GET  /health
  - POST /complete
      payload:
        EITHER {"prompt": "<full prompt string>"}
        OR     {"instruction": "...", "input": "..."}  # convenience: joined with two newlines
      returns:
        {
          "model": "<basename>",
          "params": {...},
          "prompt": "<raw prompt used>",
          "output": "<raw model text (first line trimmed)>",
          "full_output": "<entire model text>"
        }

Notes
  - No analyzers, no heuristics, no AST parsing, no post-processing.
  - Designed for quickly inspecting exactly what the model saw and produced.
"""

from __future__ import annotations

import os
import json
import time
import argparse
from typing import Any, Dict, Optional

from flask import Flask, request, jsonify
from flask_cors import CORS
from llama_cpp import Llama

# ----------------------- App / model config -----------------------

app = Flask(__name__)
CORS(app)

BASE_MODEL_PATH = os.getenv("BASE_MODEL_PATH", "./models/base_model.gguf")
LORA_PATH       = os.getenv("LORA_PATH", os.path.join("./models", "lora_sensitive.gguf"))  # default to sensitive LoRA
N_CTX           = int(os.getenv("N_CTX", "4096"))
N_THREADS       = int(os.getenv("N_THREADS", "8"))

# Default generation params (can be overridden per request)
DEFAULT_MAX_TOKENS = int(os.getenv("MAX_TOKENS", "1024"))
DEFAULT_TEMP       = float(os.getenv("TEMP", "0.0"))
DEFAULT_TOP_P      = float(os.getenv("TOP_P", "1.0"))
DEFAULT_TOP_K      = int(os.getenv("TOP_K", "40"))

_llm: Optional[Llama] = None

def _get_llm() -> Llama:
    global _llm
    if _llm is None:
        _llm = Llama(
            model_path=BASE_MODEL_PATH,
            lora_path=(LORA_PATH or None),
            n_ctx=N_CTX,
            n_threads=N_THREADS,
            logits_all=False,
            verbose=False,
        )
    return _llm

def _warmup_llm() -> None:
    try:
        _get_llm()("warmup", max_tokens=4, temperature=0.0, top_p=1.0, stop=["\n"])
    except Exception:
        pass

# ----------------------- Helpers -----------------------

def _resolve_prompt(payload: Dict[str, Any]) -> str:
    """Return a single string prompt to send to the model."""
    if isinstance(payload.get("prompt"), str):
        return payload["prompt"]
    # convenience: join instruction + input if provided
    instr = payload.get("instruction")
    inp   = payload.get("input")
    if isinstance(instr, str) and isinstance(inp, str):
        return f"{instr}\n\n{inp}"
    raise ValueError("Provide 'prompt' string (or both 'instruction' and 'input').")

# ----------------------- Endpoints -----------------------

@app.get("/health")
def health():
    try:
        _ = _get_llm()
        return jsonify({
            "status": "healthy",
            "model": os.path.basename(BASE_MODEL_PATH),
            "lora": (os.path.basename(LORA_PATH) if (LORA_PATH or "").strip() else "none"),
            "n_ctx": N_CTX,
            "n_threads": N_THREADS
        })
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 500

@app.post("/complete")
def complete():
    try:
        data = request.get_json(silent=True) or {}
        prompt = _resolve_prompt(data)

        # Optional response formatting control
        fmt = str(data.get("format", "")).strip().lower()  # "", "json_minified", "json_pretty"
        if fmt == "json_minified":
            # Prepend a hard instruction so models produce exactly ONE line of JSON.
            # We keep RAW output but constrain the model to avoid markdown/headers.
            guard = (
                "You are a formatter. Output exactly ONE LINE of MINIFIED JSON.\n"
                "No markdown, no code fences, no extra text. Do not include labels like 'Response' or 'Input'.\n"
                "The JSON must follow this schema: "
                "{\"reasons\": {\"<identifier>\": \"<one-sentence reason or empty string>\"}, \"identifiers\": [\"<sensitive only>\"]}\n"
                "Return ONLY the JSON, on a single line."
            )
            prompt = f"{guard}\n\n{prompt}\n"
        elif fmt == "json_pretty":
            # Prefer pretty JSON (multi-line). Still forbid markdown/fences.
            guard = (
                "You are a formatter. Output exactly ONE JSON object.\n"
                "No markdown, no code fences, no extra text. Do not include labels.\n"
                "Use pretty-printed JSON with indentation.\n"
                "Schema: {\"reasons\": {\"<identifier>\": \"<one-sentence reason or empty string>\"}, \"identifiers\": [\"<sensitive only>\"]}"
            )
            prompt = f"{guard}\n\n{prompt}\n"

        # If client asks for sensitive preset, tighten decoding defaults unless explicitly overridden
        use_sensitive_preset = bool(data.get("sensitive"))

        # Params: allow overrides but keep safe defaults
        max_tokens = int(data.get("max_tokens", 64 if use_sensitive_preset else DEFAULT_MAX_TOKENS))
        temperature = float(data.get("temperature", 0.0 if use_sensitive_preset else DEFAULT_TEMP))
        top_p = float(data.get("top_p", 1.0 if use_sensitive_preset else DEFAULT_TOP_P))
        top_k = int(data.get("top_k", 40 if use_sensitive_preset else DEFAULT_TOP_K))
        # Optional stops: user can pass list[str]; otherwise none
        stop = data.get("stop")
        if isinstance(stop, list):
            # decode bytes safely if any
            norm_stop = []
            for s in stop:
                if isinstance(s, bytes):
                    try:
                        norm_stop.append(s.decode("utf-8", "ignore"))
                    except Exception:
                        continue
                elif isinstance(s, str):
                    norm_stop.append(s)
            stop = norm_stop
        else:
            stop = None

        # If user selected strict one-line JSON, enforce newline stop to cut anything after the JSON line.
        if fmt == "json_minified":
            stop = stop or ["\n"]
            temperature = 0.0
            top_p = 1.0
            top_k = 40
            max_tokens = int(data.get("max_tokens", 1024))  # plenty, we stop at newline anyway

        # Sensitive preset (legacy) remains, but avoid overly aggressive stops that break JSON
        if use_sensitive_preset and not stop and fmt not in ("json_minified", "json_pretty"):
            # Avoid stops that can truncate JSON arbitrarily
            stop = None

        llm = _get_llm()
        t0 = time.time()
        resp = llm(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            stop=stop
        )
        dt = time.time() - t0

        text = ""
        try:
            text = resp.get("choices", [{}])[0].get("text", "")
        except Exception:
            text = ""

        first_line = ""
        if isinstance(text, str):
            # 'raw output'로서 전체 텍스트는 full_output에 넣고,
            # 사람이 보기 쉽도록 첫 줄을 별도로 제공
            first_line = text.splitlines()[0] if text.splitlines() else text

        return jsonify({
            "model": (
                f"{os.path.basename(BASE_MODEL_PATH)} + {os.path.basename(LORA_PATH)}"
                if (LORA_PATH or "").strip()
                else os.path.basename(BASE_MODEL_PATH)
            ),
            "params": {
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "stop": stop,
                "time_s": round(dt, 3),
                "format": fmt,
            },
            "prompt": prompt,
            "output": first_line,
            "full_output": text
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ----------------------- Main -----------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Minimal RAW I/O LLM server")
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    print(f"RAW I/O server on http://{args.host}:{args.port}")
    _warmup_llm()
    app.run(host=args.host, port=args.port, debug=False)
