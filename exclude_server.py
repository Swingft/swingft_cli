#!/usr/bin/env python3
"""
Exclude Server: /exclude (obfuscation exclusion)

IMPORTANT:
  - This server returns **only raw LLM outputs** and does NOT attempt any JSON parsing,
    validation, or normalization of the model's text. The client is expected to
    parse/process the raw text returned in the "raw" field.
  - Input formats supported:
      1) Flat:  { "swift_code": "...", "symbol_info": {...}, "identifiers": ["A","B",...] }
      2) Nested: { "instruction": "...", "input": { "swift_code": "...", "symbol_info": {...}, "identifiers": [...] } }
"""

import os
import sys
import json
import re
import argparse
from typing import Optional, List, Dict, Any
sys.path.append(os.path.abspath("../../ConsoleLLM_Portable"))

from flask import Flask, request, jsonify
from flask_cors import CORS
from llama_cpp import Llama, LlamaGrammar

app = Flask(__name__)
CORS(app)

# ===== Model / runtime configuration (can be overridden via env) =====
BASE_MODEL_PATH = os.getenv("BASE_MODEL_PATH", "models/base_model.gguf")
LORA_EXCLUDE    = os.getenv("LORA_EXCLUDE",   "models/lora_exclude_swift.gguf")
N_CTX           = int(os.getenv("N_CTX", "4096"))
N_THREADS       = int(os.getenv("N_THREADS", "8"))

_llm: Optional[Llama] = None
def _get_llm() -> Llama:
    global _llm
    if _llm is None:
        _llm = Llama(
            model_path=BASE_MODEL_PATH,
            lora_path=LORA_EXCLUDE,
            n_ctx=N_CTX,
            n_threads=N_THREADS,
            logits_all=False,
            verbose=False
        )
    return _llm

# -------------------- Grammar helpers (kept for optional use) --------------------
def _build_exclude_json_array_grammar():
    """Return a grammar object if available; caller may pass it to the model,
    but note we will NOT parse/validate the model output on the server side."""
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "exclude": {"type": "boolean"},
                "reason": {"type": "string"}
            },
            "required": ["name", "exclude", "reason"],
            "additionalProperties": False
        }
    }
    try:
        return LlamaGrammar.from_json_schema(schema)
    except Exception:
        return None

# -------------------- Minimal utils for AST extraction --------------------
def _extract_identifiers_from_symbol_info(symbol_info: Dict[str, Any]) -> List[str]:
    ids: List[str] = []
    if not isinstance(symbol_info, dict):
        return ids
    decisions = symbol_info.get("decisions") if isinstance(symbol_info.get("decisions"), dict) else None
    if decisions:
        for key in ("classes","structs","enums","enumCases","methods","properties","initializers","extensions"):
            arr = decisions.get(key)
            if isinstance(arr, list):
                for item in arr:
                    if isinstance(item, dict):
                        name = item.get("symbol_name") or item.get("name")
                        if isinstance(name, str) and name:
                            ids.append(name)
        # dedupe while preserving order
        seen = set()
        out: List[str] = []
        for x in ids:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out
    # fallback: top-level keys
    for k in symbol_info.keys():
        if k not in ("meta","decisions"):
            ids.append(str(k))
    return ids

# -------------------- Core: call LLM and return raw strings --------------------
def _call_exclude_llm_raw(identifiers: List[str], symbol_info: Optional[Dict[str, Any]], swift_code: Optional[str]) -> Dict[str, Any]:
    """
    Call the LLM and return raw outputs only.

    Returns a dict with shape:
      - batch mode success:
          { "mode": "batch", "batch_text": "<raw model text>" }
      - fallback per-identifier:
          { "mode": "per_identifier", "per_identifier": [ { "name": id, "text": "<raw>" }, ... ] }
      - on errors, 'error' key may appear with a message.
    """
    llm = _get_llm()

    # Try batch mode (single call) if grammar available (we still won't parse)
    array_grammar = _build_exclude_json_array_grammar()
    swift_ctx = (swift_code or "").strip()
    if len(swift_ctx) > 1600:
        swift_ctx = swift_ctx[:1600] + "\n..."

    # Build a compact symbol meta block for context (not parsed by server)
    def _compact_meta_list() -> str:
        lines: List[str] = []
        if not isinstance(symbol_info, dict):
            return ""
        for name in identifiers:
            # Try to find matching symbol metadata
            found = None
            decs = symbol_info.get("decisions") if isinstance(symbol_info.get("decisions"), dict) else None
            if isinstance(decs, dict):
                for key in ("classes","structs","enums","enumCases","methods","properties","initializers","extensions"):
                    arr = decs.get(key)
                    if isinstance(arr, list):
                        for item in arr:
                            if isinstance(item, dict) and (item.get("symbol_name") == name or item.get("name") == name):
                                found = item
                                break
                        if found:
                            break
            if not found:
                direct = symbol_info.get(name)
                if isinstance(direct, dict):
                    found = direct
            try:
                s = json.dumps(found, ensure_ascii=False) if found is not None else ""
            except Exception:
                s = str(found)
            if len(s) > 240:
                s = s[:240] + "..."
            lines.append(f"- name: {name}\n  meta: {s}")
        return "\n".join(lines)

    meta_block = _compact_meta_list()

    # Batch mode attempt: ask model to return a JSON array (we will NOT parse it here)
    if array_grammar is not None:
        prompt = (
            "You are an assistant that decides whether Swift identifiers must be excluded from source-level obfuscation.\n"
            "Return ONLY a JSON array. Each element MUST be an object with keys exactly: name (string), exclude (boolean), reason (string).\n"
            "Do NOT include any extra text or explanation. The client will parse the raw text returned.\n"
            f"Identifiers: {json.dumps(identifiers, ensure_ascii=False)}\n"
            f"SymbolMeta (compact):\n{meta_block}\n\n"
            f"SwiftContext:\n{swift_ctx}\n"
        )
        try:
            response = llm(
                prompt,
                max_tokens=max(256, min(2048, 64 * len(identifiers))),
                temperature=0.0,
                top_p=1.0,
                # Do NOT rely on stop tokens to produce complete JSON; we will return raw text as-is.
                grammar=array_grammar
            )
            text = response.get("choices", [{}])[0].get("text", "")
            # Return raw batch text directly (no parsing)
            return {"mode": "batch", "batch_text": text}
        except Exception as e:
            # fall through to per-identifier mode, but include an error note
            batch_err = str(e)
    else:
        batch_err = "array_grammar_unavailable"

    # Per-identifier fallback: call LLM once per identifier and return raw outputs
    per_list: List[Dict[str, str]] = []
    for identifier in identifiers:
        # build a focused prompt for each identifier
        # include compact metadata for that identifier (best-effort)
        identifier_meta = ""
        if isinstance(symbol_info, dict):
            found = None
            decs = symbol_info.get("decisions") if isinstance(symbol_info.get("decisions"), dict) else None
            if isinstance(decs, dict):
                for key in ("classes","structs","enums","enumCases","methods","properties","initializers","extensions"):
                    arr = decs.get(key)
                    if isinstance(arr, list):
                        for item in arr:
                            if isinstance(item, dict) and (item.get("symbol_name") == identifier or item.get("name") == identifier):
                                found = item
                                break
                        if found:
                            break
            if not found:
                direct = symbol_info.get(identifier)
                if isinstance(direct, dict):
                    found = direct
            try:
                identifier_meta = json.dumps(found, ensure_ascii=False) if found is not None else ""
            except Exception:
                identifier_meta = str(found) if found is not None else ""
            if len(identifier_meta) > 1200:
                identifier_meta = identifier_meta[:1200] + "..."

        prompt = (
            "You are an assistant that decides whether a single Swift identifier must be excluded from source-level obfuscation.\n"
            "Return ONLY a single-line JSON object with keys exactly: name (string), exclude (boolean), reason (string).\n"
            "Do NOT include any extra text or explanation. The client will parse the raw text returned.\n"
            f'Identifier: "{identifier}"\n'
            f"SymbolMeta: {identifier_meta}\n"
            f"SwiftContext:\n{swift_ctx}\n"
        )
        try:
            response = llm(
                prompt,
                max_tokens=192,
                temperature=0.0,
                top_p=1.0
            )
            text = response.get("choices", [{}])[0].get("text", "")
            per_list.append({"name": identifier, "text": text})
        except Exception as e:
            per_list.append({"name": identifier, "text": "", "error": str(e)})

    # If batch attempt previously errored, include that info
    out: Dict[str, Any] = {"mode": "per_identifier", "per_identifier": per_list}
    if batch_err:
        out["batch_attempt_error"] = batch_err
    return out

# -------------------- HTTP endpoints --------------------
@app.route('/exclude', methods=['POST'])
def exclude():
    """
    Accept a payload and return raw LLM outputs. No server-side JSON parsing of LLM text is performed.
    """
    try:
        data = request.get_json(silent=True) or {}

        # Support nested schema: { instruction, input: { ... } }
        payload = dict(data)
        if isinstance(data.get("input"), dict):
            inp = data["input"]
            for k in ("swift_code", "symbol_info", "identifiers"):
                if k not in payload and k in inp:
                    payload[k] = inp[k]

        identifiers = payload.get("identifiers")
        if identifiers is None:
            sym = payload.get("symbol_info")
            if isinstance(sym, dict) and sym:
                ids = _extract_identifiers_from_symbol_info(sym)
                identifiers = ids if ids else [str(k) for k in sym.keys()]
            else:
                return jsonify({"error": "'identifiers' field is required or provide 'symbol_info' with keys to analyze"}), 400

        if isinstance(identifiers, dict):
            identifiers = list(identifiers.keys())
        elif not isinstance(identifiers, list):
            return jsonify({"error": "'identifiers' must be a list (or provide 'symbol_info' dict)"}), 400

        identifiers = [str(x).strip() for x in identifiers if str(x).strip()]
        if not identifiers:
            return jsonify({"error": "No identifiers provided"}), 400

        symbol_info = payload.get("symbol_info") if isinstance(payload.get("symbol_info"), dict) else None
        swift_code  = payload.get("swift_code")  if isinstance(payload.get("swift_code"),  str)  else None

        # Call LLM and return raw output (server does NOT parse the returned text).
        raw_output = _call_exclude_llm_raw(identifiers, symbol_info, swift_code)

        # --- Console log for raw LLM output (visible in terminal) ---
        try:
            print("\n=== [/exclude] LLM RAW OUTPUT ===", flush=True)
            # Pretty-print with UTF-8; cap overly long outputs to keep logs usable
            _raw_for_log = raw_output
            _raw_text = json.dumps(_raw_for_log, ensure_ascii=False, indent=2)
            if len(_raw_text) > 8000:
                _raw_text = _raw_text[:8000] + "\n... [truncated]"
            print(_raw_text, flush=True)
            print("=== [/exclude] END RAW OUTPUT ===\n", flush=True)
        except Exception as _e:
            print(f"[/exclude] Logging error: {_e}", flush=True)

        return jsonify({"raw": raw_output})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    try:
        gram_ok = _build_exclude_json_array_grammar() is not None
    except Exception:
        gram_ok = False
    return jsonify({"status": "healthy", "exclude_array_grammar_available": bool(gram_ok)})

# -------------------- CLI / main --------------------
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Exclude Server (/exclude) - returns raw LLM output only")
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    print(f"Exclude (raw) server on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)