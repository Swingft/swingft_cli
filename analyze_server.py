#!/usr/bin/env python3
"""
Ultra-minimal Analyze Server

Single endpoint: POST /analyze

Text-in → Text-out only.

Accepted inputs (pick the first that exists):
  - { "text": "..." }            # sent as-is to the model
  - { "identifiers": ["foo"] }   # uses the first identifier string
  - { "input": { "text": "..." } } or { "input": { "identifiers": [...] } }

Returns:
  { "text": "<raw model output>" }

No wrapping, no parsing, no fallback, no format constraints.
"""

import os
import json
import argparse
from typing import Optional, List, Dict, Any

from flask import Flask, request, jsonify
from flask_cors import CORS
from llama_cpp import Llama

app = Flask(__name__)
CORS(app)

# ===== Model / runtime configuration =====
ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
DEFAULT_MODEL_DIR = os.getenv("MODEL_DIR", os.path.join(ROOT_DIR, "models"))
BASE_MODEL_PATH = os.getenv("BASE_MODEL_PATH", os.path.join(DEFAULT_MODEL_DIR, "base_model.gguf"))
LORA_SENSITIVE  = os.getenv("LORA_SENSITIVE",  os.path.join(DEFAULT_MODEL_DIR, "lora_sensitive2.gguf"))
N_CTX           = int(os.getenv("N_CTX", "4096"))
N_THREADS       = int(os.getenv("N_THREADS", "8"))

_llm: Optional[Llama] = None
def _get_llm() -> Llama:
    global _llm
    if _llm is None:
        _llm = Llama(
            model_path=BASE_MODEL_PATH,
            lora_path=LORA_SENSITIVE,
            n_ctx=N_CTX,
            n_threads=N_THREADS,
            logits_all=False,
            verbose=False
        )
    return _llm

def _warmup_llm() -> None:
    try:
        _get_llm()("warmup", max_tokens=4, temperature=0.0, top_p=1.0)
    except Exception:
        pass


# ===== Helpers =====
def _llm_text(prompt_text: str) -> str:
    """Send raw text to model and return raw text. No constraints."""
    llm = _get_llm()
    resp = llm(prompt_text, max_tokens=512, temperature=0.0, top_p=1.0)
    return resp.get("choices", [{}])[0].get("text", "") or ""


# ===== HTTP endpoint =====
@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        data = request.get_json(silent=True) or {}

        # Select input. If only identifier is provided, wrap with a simple prompt template.
        text = None
        # 1) direct text
        if isinstance(data.get("text"), str) and data.get("text").strip():
            text = data.get("text")
        # 2) identifiers at top-level
        elif isinstance(data.get("identifiers"), list) and data.get("identifiers"):
            ident = str(data["identifiers"][0]).strip()
            if ident:
                text = (
                    "Task: Decide if this Swift identifier is security-sensitive. "
                    "Provide a brief reasoning in plain text.\n\n"
                    f"Identifier: {ident}"
                )
        # 3) nested input
        elif isinstance(data.get("input"), dict):
            inp = data.get("input")
            if isinstance(inp.get("text"), str) and inp.get("text").strip():
                text = inp.get("text")
            elif isinstance(inp.get("identifiers"), list) and inp.get("identifiers"):
                ident = str(inp["identifiers"][0]).strip()
                if ident:
                    text = (
                        "Task: Decide if this Swift identifier is security-sensitive. "
                        "Provide a brief reasoning in plain text.\n\n"
                        f"Identifier: {ident}"
                    )

        if not isinstance(text, str) or not text.strip():
            return jsonify({"error": "provide 'text' or non-empty 'identifiers'"}), 400

        raw = _llm_text(text)

        # Console RAW log (single line header + full raw)
        try:
            print("\n=== [/analyze] LLM RAW OUTPUT ===", flush=True)
            print(f"{raw}", flush=True)
            print("=== [/analyze] END RAW OUTPUT ===\n", flush=True)
        except Exception:
            pass

        return jsonify({"text": raw})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===== Main =====
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Ultra-minimal Analyze Server (/analyze)")
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    print(f"Analyze server on http://{args.host}:{args.port}")
    _warmup_llm()
    app.run(host=args.host, port=args.port, debug=False)
#!/usr/bin/env python3
"""
Analyze Server: /analyze (identifier sensitivity)

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
import argparse
from typing import Optional, List, Dict, Any
import re
sys.path.append(os.path.abspath("../../ConsoleLLM_Portable"))

from flask import Flask, request, jsonify
from flask_cors import CORS
from llama_cpp import Llama, LlamaGrammar

app = Flask(__name__)
CORS(app)

# ===== Model / runtime configuration (can be overridden via env) =====
# 프로젝트 루트 기준의 models 디렉터리를 기본값으로 사용
ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
DEFAULT_MODEL_DIR = os.getenv("MODEL_DIR", os.path.join(ROOT_DIR, "models"))
BASE_MODEL_PATH = os.getenv("BASE_MODEL_PATH", os.path.join(DEFAULT_MODEL_DIR, "base_model.gguf"))
LORA_SENSITIVE  = os.getenv("LORA_SENSITIVE",  os.path.join(DEFAULT_MODEL_DIR, "lora_sensitive.gguf"))
N_CTX           = int(os.getenv("N_CTX", "4096"))
N_THREADS       = int(os.getenv("N_THREADS", "8"))

_llm: Optional[Llama] = None
def _get_llm() -> Llama:
    global _llm
    if _llm is None:
        _llm = Llama(
            model_path=BASE_MODEL_PATH,
            lora_path=LORA_SENSITIVE,
            n_ctx=N_CTX,
            n_threads=N_THREADS,
            logits_all=False,
            verbose=False
        )
    return _llm

"""Exclude 전용 LLM 제거: 단일 민감도 경로만 유지"""

def _warmup_llm() -> None:
    """모델 첫 호출 시 비정상 토큰 방출을 줄이기 위한 워밍업 호출."""
    try:
        llm = _get_llm()
        # 매우 짧은 토큰을 한 번 발생시켜 로딩 오버헤드를 해소
        llm("warmup", max_tokens=256, temperature=0.0, top_p=1.0)
    except Exception:
        pass

# -------------------- Optional grammar (raw만 반환하지만 프롬프트 가이드용) --------------------
"""배열 문법 제거: 단일 오브젝트 문법만 유지"""

def _build_single_sensitive_grammar():
    # Raw 모드에서는 문법을 사용하지 않음. 호환성을 위해 None 반환
    return None

"""exclude 전용 문법 제거"""

def _extract_json_obj(text: str) -> Optional[dict]:
    # Raw 모드: 더 이상 서버에서 파싱하지 않음
    return None

def _parse_sensitive_raw(text: str) -> Optional[Dict[str, Any]]:
    """Parse model raw output into {"sensitive": bool, "reason": str}."""
    if not isinstance(text, str):
        return None
    s = text.strip()
    if not s:
        return None
    if s.startswith("{") and s.endswith("}"):
        try:
            obj = json.loads(s)
            if isinstance(obj, dict) and isinstance(obj.get("sensitive"), bool):
                reason = obj.get("reason") or ""
                return {"sensitive": bool(obj["sensitive"]), "reason": str(reason)}
        except Exception:
            pass
    low = s.lower()
    sep = "\t" if "\t" in s else " "
    parts = s.split(sep, 1)
    head, tail = parts[0], parts[1] if len(parts) > 1 else ""
    if head.lower().startswith("true"):
        return {"sensitive": True, "reason": tail.strip()}
    if head.lower().startswith("false"):
        return {"sensitive": False, "reason": tail.strip()}
    if head.lower().startswith("yes"):
        return {"sensitive": True, "reason": tail.strip()}
    if head.lower().startswith("no"):
        return {"sensitive": False, "reason": tail.strip()}
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
        seen, out = set(), []
        for x in ids:
            if x not in seen:
                seen.add(x); out.append(x)
        return out
    # fallback: top-level keys
    for k in symbol_info.keys():
        if k not in ("meta","decisions"):
            ids.append(str(k))
    return ids

"""레거시 RAW/배치 경로 제거됨"""

def _call_single_sensitive_llm(identifiers: List[str], symbol_info: Optional[Dict[str, Any]], swift_code: Optional[str], user_reasoning: Optional[str] = None) -> List[Dict[str, Any]]:
    llm = _get_llm()
    grammar = None  # Raw 모드: 문법 미사용
    swift_ctx = (swift_code or "").strip()
    if len(swift_ctx) > 1600:
        swift_ctx = swift_ctx[:1600] + "\n..."

    def _compact_meta_list() -> str:
        lines: List[str] = []
        if not isinstance(symbol_info, dict):
            return ""
        for name in identifiers:
            found = None
            decs = symbol_info.get("decisions") if isinstance(symbol_info.get("decisions"), dict) else None
            if isinstance(decs, dict):
                for key in ("classes","structs","enums","enumCases","methods","properties","initializers","extensions"):
                    arr = decs.get(key)
                    if isinstance(arr, list):
                        for item in arr:
                            if isinstance(item, dict) and (item.get("symbol_name") == name or item.get("name") == name):
                                found = item; break
                    if found: break
            if not found:
                direct = symbol_info.get(name) if isinstance(symbol_info, dict) else None
                if isinstance(direct, dict):
                    found = direct
            try:
                s = json.dumps(found, ensure_ascii=False) if found is not None else ""
            except Exception:
                s = str(found)
            if len(s) > 240: s = s[:240] + "..."
            lines.append(f"- name: {name}\n  meta: {s}")
        return "\n".join(lines)

    meta_block = _compact_meta_list()

    results: List[Dict[str, Any]] = []
    for identifier in identifiers:
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
                                found = item; break
                    if found: break
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

        # 모델 학습 입력 형식(JSON)으로 래핑: reasoning + identifiers(단일) + symbolMeta + swiftContext
        prompt_obj = {
            "reasoning": (user_reasoning or "Answer ONLY with true or false (boolean) as the first token indicating if the identifier is security-sensitive. Consider true only for actual secrets (api keys, passwords, tokens, encryption keys, auth credentials). Normal identifiers like dateFormatter/viewModel/controller are NOT secrets (false). Do not return JSON."),
            "identifiers": [identifier],
            "symbolMeta": identifier_meta,
            "swiftContext": swift_ctx
        }
        try:
            prompt = json.dumps(prompt_obj, ensure_ascii=False)
        except Exception:
            prompt = f'{"reasoning":"Analyze the code and list security-sensitive identifiers.","identifiers":["{identifier}"]}'
        try:
            response = llm(
                prompt,
                max_tokens=24,
                temperature=0.0,
                top_p=1.0
            )
            text = response.get("choices", [{}])[0].get("text", "")
            # Normalize: take the first non-empty line
            if isinstance(text, str):
                # Some models emit a leading newline as the very first token; avoid returning empty.
                lines = [ln for ln in text.splitlines() if ln.strip()]
                if lines:
                    text = lines[0].strip()
            if not isinstance(text, str) or not text.strip():
                # Heuristic fallback to avoid empty outputs breaking clients
                # Mark as non-sensitive by default and include an explicit reason
                text = "false\tno model output; defaulting to non-sensitive"
            if text == "false\tno model output; defaulting to non-sensitive":
                try:
                    print(f"[debug] Empty generation for '{identifier}'. Prompt head: {prompt[:240]}", flush=True)
                except Exception:
                    pass
            results.append({"name": identifier, "raw": text})
        except Exception as e:
            results.append({"name": identifier, "raw": f"ERROR: {str(e)}"})
    return results

"""exclude 전용 호출 제거"""

# -------------------- HTTP endpoints --------------------
@app.route('/analyze', methods=['POST'])
def analyze():
    """
    Accept a payload and return PARSED sensitivity results (per-identifier objects with name/sensitive/reason).
    The server will also print each identifier's raw LLM output to the console for debugging.
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

        user_reasoning = payload.get("reasoning") if isinstance(payload.get("reasoning"), str) else None

        items = _call_single_sensitive_llm(identifiers, symbol_info, swift_code, user_reasoning=user_reasoning)

        # --- Console log for raw LLM output (visible in terminal) ---
        try:
            print("\n=== [/analyze] LLM RAW OUTPUT ===", flush=True)
            for it in items:
                raw = it.get("raw","")
                nm = it.get("name","")
                if isinstance(raw, str) and len(raw) > 4000:
                    raw_show = raw[:4000] + "\n... [truncated]"
                else:
                    raw_show = raw
                print(f"[{nm}] {raw_show}", flush=True)
            print("=== [/analyze] END RAW OUTPUT ===\n", flush=True)
        except Exception as _e:
            print(f"[/analyze] Logging error: {_e}", flush=True)

        # Raw 모드 응답: 식별자별 원문 텍스트를 반환
        resp = {"raw": [{"name": it.get("name"), "text": it.get("raw", "")} for it in items]}
        if len(items) == 1:
            # 단일 식별자 요청 시 편의를 위해 최상위 text 필드 제공
            one = items[0].get("raw", "")
            if not isinstance(one, str) or not one.strip():
                one = "false\tno model output; defaulting to non-sensitive"
            resp["text"] = one
        return jsonify(resp)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    try:
        gram_ok = _build_single_sensitive_grammar() is not None
    except Exception:
        gram_ok = False
    return jsonify({"status": "healthy", "single_sensitive_grammar_available": bool(gram_ok)})

@app.route('/analyze_parsed', methods=['POST'])
def analyze_parsed():
    try:
        data = request.get_json(silent=True) or {}

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

        strict_instruction = (
            "You are a classifier. Return only one line as 'true\\t<reason>' or 'false\\t<reason>'. "
            "Use 'true' only for identifiers that are secrets (keys, tokens, credentials)."
        )
        items = _call_single_sensitive_llm(identifiers, symbol_info, swift_code, user_reasoning=strict_instruction)

        print("\n=== [/analyze_parsed] LLM RAW OUTPUT ===", flush=True)
        for it in items:
            raw = it.get("raw","")
            nm = it.get("name","")
            if isinstance(raw, str) and len(raw) > 4000:
                raw_show = raw[:4000] + "\n... [truncated]"
            else:
                raw_show = raw
            print(f"[{nm}] {raw_show}", flush=True)
        print("=== [/analyze_parsed] END RAW OUTPUT ===\n", flush=True)

        results = []
        for it in items:
            name = it.get("name")
            raw = it.get("raw", "")
            parsed = _parse_sensitive_raw(raw)
            if parsed is None:
                fallback_reason = raw.strip() or "no parseable model output; defaulting to non-sensitive"
                parsed = {"sensitive": False, "reason": fallback_reason}
            results.append({
                "identifier": name,
                "sensitive": bool(parsed["sensitive"]),
                "reason": parsed["reason"]
            })

        resp = {"results": results}
        if len(results) == 1:
            resp.update(results[0])
        return jsonify(resp)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

"""레거시 /exclude_parsed 제거"""

# -------------------- CLI / main --------------------
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Analyze Server (/analyze) - returns raw LLM output only")
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    print(f"Analyze (raw) server on http://{args.host}:{args.port}")
    # 서버 시작 전 워밍업 수행
    _warmup_llm()
    app.run(host=args.host, port=args.port, debug=False)