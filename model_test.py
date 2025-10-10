#!/usr/bin/env python3
"""
LLM Server for sensitivity analysis
"""
import sys

import json
import os
import re
import argparse
from typing import Optional
from pathlib import Path
sys.path.append(os.path.abspath("../../ConsoleLLM_Portable"))
from flask import Flask, request, jsonify
from flask_cors import CORS
from llama_cpp import Llama, LlamaGrammar

app = Flask(__name__)
CORS(app)

_llm_instance = None
_llm_exclude_instance = None

def _build_json_grammar():
    # Grammar to force a single JSON object: {"name": string, "sensitive": true/false, "reason": string}
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "sensitive": {"type": "boolean"},
            "reason": {"type": "string"}
        },
        "required": ["name", "sensitive", "reason"],
        "additionalProperties": False
    }
    try:
        return LlamaGrammar.from_json_schema(schema)
    except Exception:
        # If grammar is not supported by this llama-cpp build, return None and fall back to regex parsing
        return None

def _build_exclude_json_grammar():
    # Grammar to force a single JSON object: {"name": string, "exclude": true/false, "reason": string}
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "exclude": {"type": "boolean"},
            "reason": {"type": "string"}
        },
        "required": ["name", "exclude", "reason"],
        "additionalProperties": False
    }
    try:
        return LlamaGrammar.from_json_schema(schema)
    except Exception:
        return None

def _build_exclude_json_array_grammar():
    """Grammar to force a JSON array of objects: [{"name": string, "exclude": bool, "reason": string}, ...]"""
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

def _get_llm():
    global _llm_instance
    if _llm_instance is None:
        base_model_path = "models/base_model.gguf"
        lora_sensitive_path = "models/lora_sensitive.gguf"
        _llm_instance = Llama(
            model_path=base_model_path,
            lora_path=lora_sensitive_path,
            n_ctx=4096,
            n_threads=8,
            logits_all=False,
            verbose=False
        )
    return _llm_instance

def _get_exclude_llm():
    global _llm_exclude_instance
    if _llm_exclude_instance is None:
        base_model_path = "models/base_model.gguf"
        lora_exclude_path = "models/lora_exclude.gguf"
        _llm_exclude_instance = Llama(
            model_path=base_model_path,
            lora_path=lora_exclude_path,
            n_ctx=4096,
            n_threads=8,
            logits_all=False,
            verbose=False
        )
    return _llm_exclude_instance


def _extract_json(text: str) -> Optional[dict]:
    # Strip common code fences
    text = re.sub(r"^```(json)?", "", text.strip(), flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()

    # Try direct parse
    try:
        return json.loads(text)
    except Exception:
        pass

    # Try to grab the first JSON object non-greedily
    m = re.search(r"\{.*?\}", text, flags=re.DOTALL)
    if m:
        candidate = m.group(0)
        try:
            return json.loads(candidate)
        except Exception:
            return None
    return None


# Helper: extract identifiers from symbol_info (Gemini/AST or flat)
def _extract_identifiers_from_symbol_info(symbol_info: dict) -> list[str]:
    """Extract identifier names from the symbol_info structure.
    Prefers the Gemini-style {"decisions": { arrays... }} layout.
    Fallback: use top-level keys if they look like identifiers.
    """
    ids: list[str] = []
    if not isinstance(symbol_info, dict):
        return ids

    decisions = symbol_info.get("decisions") if isinstance(symbol_info.get("decisions"), dict) else None
    if decisions:
        for key in ("classes", "structs", "enums", "enumCases", "methods", "properties", "initializers", "extensions"):
            arr = decisions.get(key)
            if isinstance(arr, list):
                for item in arr:
                    if isinstance(item, dict):
                        name = item.get("symbol_name") or item.get("name")
                        if isinstance(name, str) and name:
                            ids.append(name)
        # Deduplicate while preserving order
        seen = set()
        out: list[str] = []
        for x in ids:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    # Fallback: use top-level keys except meta/decisions
    for k in symbol_info.keys():
        if k not in ("meta", "decisions"):
            ids.append(str(k))
    return ids

@app.route('/analyze', methods=['POST'])
def analyze_sensitivity():
    """Analyze identifier sensitivity using actual LLM"""
    try:
        data = request.get_json(silent=True) or {}
        identifiers = data.get('identifiers')
        if identifiers is None:
            return jsonify({"error": "'identifiers' field is required"}), 400
        if not isinstance(identifiers, list):
            return jsonify({"error": "'identifiers' must be a list"}), 400
        # Coerce all items to string to avoid type errors downstream
        identifiers = [str(x) for x in identifiers]
        if len(identifiers) == 0:
            return jsonify({"error": "No identifiers provided"}), 400

        # Call actual LLM for analysis
        results = _call_actual_llm(identifiers)

        if results is None:
            return jsonify({"error": "LLM analysis failed"}), 500

        return jsonify({"results": results})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

def _call_actual_llm(identifiers):
    llm = _get_llm()
    grammar = _build_json_grammar()
    results = []
    for identifier in identifiers:
        prompt = (
            "You are an assistant that classifies whether a single identifier is sensitive.\n"
            "Return ONLY a single-line JSON object with keys exactly: name (string), sensitive (boolean), reason (string).\n"
            "No explanations, no markdown, no backticks, no surrounding text. Output must end right after the closing brace '}'.\n"
            f'Identifier: "{identifier}"'
        )
        try:
            response = llm(
                prompt,
                max_tokens=8192,
                temperature=0.0,
                top_p=1.0,
                stop=["\n\n"],
                grammar=grammar
            )
            text = response.get("choices", [{}])[0].get("text", "").strip()
            parsed = _extract_json(text)
            if parsed is None:
                raise ValueError(f"Model did not return valid JSON: {text[:120]}...")
            results.append(parsed)
        except Exception as e:
            results.append({
                "name": identifier,
                "sensitive": False,
                "reason": f"LLM JSON parse error: {str(e)}" if str(e) else "Invalid JSON from model"
            })
    return results

def _call_exclude_llm(identifiers, symbol_info: dict | None = None, swift_code: str | None = None):
    llm = _get_exclude_llm()

    # Try array grammar first (batch mode)
    array_grammar = _build_exclude_json_array_grammar()

    # Prepare context strings (shortened to keep prompt within context window)
    swift_ctx = (swift_code or "").strip()
    if len(swift_ctx) > 1600:
        swift_ctx = swift_ctx[:1600] + "\n..."

    # Helper to compute compact meta for each identifier
    def _meta_for(identifier: str) -> str:
        meta = {}
        if isinstance(symbol_info, dict):
            direct = symbol_info.get(identifier)
            if isinstance(direct, dict):
                meta = direct
            else:
                decs = symbol_info.get("decisions") if isinstance(symbol_info.get("decisions"), dict) else None
                if decs:
                    for key in ("classes", "structs", "enums", "enumCases", "methods", "properties", "initializers", "extensions"):
                        arr = decs.get(key)
                        if isinstance(arr, list):
                            for item in arr:
                                if isinstance(item, dict) and (item.get("symbol_name") == identifier or item.get("name") == identifier):
                                    meta = item
                                    break
                        if meta:
                            break
        try:
            s = json.dumps(meta, ensure_ascii=False)
        except Exception:
            s = str(meta)
        # keep meta very short per-identifier in batch mode
        return (s[:240] + "...") if len(s) > 240 else s

    # If array grammar is available, do a single batched call
    if array_grammar is not None:
        # Build a compact meta list
        meta_lines = []
        for name in identifiers:
            meta_lines.append(f"- name: {name}\n  meta: {_meta_for(name)}")
        meta_block = "\n".join(meta_lines)

        prompt = (
            "You are an assistant that decides whether Swift identifiers must be excluded from source-level obfuscation.\n"
            "Return ONLY a JSON array. Each element MUST be an object with keys exactly: name (string), exclude (boolean), reason (string).\n"
            "No explanations, no markdown, no backticks, no extra text before or after the JSON. Output must end right after the closing bracket ']'.\n"
            "Decision rules to consider: Objective-C interop (@objc/@dynamic/NSObject/KVC/KVO), reflection/Selector string lookups, Codable/NSCoding keys, SwiftUI state (@State/@Binding), KeyPath-based access, ABI/FFI bridging (@_cdecl), and other runtime name-based resolution risks.\n"
            f"Identifiers: {json.dumps(identifiers, ensure_ascii=False)}\n"
            f"SymbolMeta (compact per identifier):\n{meta_block}\n\n"
            f"SwiftContext:\n{swift_ctx}\n"
        )
        try:
            response = llm(
                prompt,
                max_tokens=max(256, min(2048, 64 * len(identifiers))),
                temperature=0.0,
                top_p=1.0,
                stop=["\n\n"],
                grammar=array_grammar,
            )
            text = response.get("choices", [{}])[0].get("text", "").strip()
            # Parse array JSON directly
            results = json.loads(text)
            # Validate and normalize
            final = []
            valid_names = set(identifiers)
            if not isinstance(results, list):
                raise ValueError("Model did not return a JSON array")
            for item in results:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                exc = item.get("exclude")
                rsn = item.get("reason")
                if isinstance(name, str) and name in valid_names and isinstance(exc, bool) and isinstance(rsn, str):
                    final.append({"name": name, "exclude": exc, "reason": rsn})
            # Ensure we return something for every requested identifier
            missing = [n for n in identifiers if n not in {x["name"] for x in final}]
            for n in missing:
                final.append({"name": n, "exclude": False, "reason": "No result from model for this identifier"})
            return final
        except Exception:
            # Fall through to per-identifier mode if parsing fails
            pass

    # ==== Fallback: per-identifier mode (original behavior) ====
    grammar = _build_exclude_json_grammar()
    results = []
                for identifier in identifiers:
        meta = {}
        if isinstance(symbol_info, dict):
            direct = symbol_info.get(identifier)
            if isinstance(direct, dict):
                meta = direct
            else:
                decs = symbol_info.get("decisions") if isinstance(symbol_info.get("decisions"), dict) else None
                if decs:
                    for key in ("classes", "structs", "enums", "enumCases", "methods", "properties", "initializers", "extensions"):
                        arr = decs.get(key)
                        if isinstance(arr, list):
                            for item in arr:
                                if isinstance(item, dict) and (item.get("symbol_name") == identifier or item.get("name") == identifier):
                                    meta = item
                                    break
                        if meta:
                            break
        try:
            meta_str = json.dumps(meta, ensure_ascii=False)
        except Exception:
            meta_str = str(meta)
        if len(meta_str) > 1200:
            meta_str = meta_str[:1200] + "..."

        prompt = (
            "You are an assistant that decides whether a single Swift identifier must be excluded from source-level obfuscation.\n"
            "Return ONLY a single-line JSON object with keys exactly: name (string), exclude (boolean), reason (string).\n"
            "No explanations, no markdown, no backticks, no surrounding text. Output must end right after the closing brace '}'.\n"
            "Decision rules to consider: Objective-C interop (@objc/@dynamic/NSObject/KVC/KVO), reflection/Selector string lookups, Codable/NSCoding keys, SwiftUI state (@State/@Binding), KeyPath-based access, ABI/FFI bridging (@_cdecl), and other runtime name-based resolution risks.\n"
            f"Identifier: \"{identifier}\"\n"
            f"SymbolMeta: {meta_str}\n"
            f"SwiftContext:\n{swift_ctx}\n"
        )
        try:
            response = llm(
                prompt,
                max_tokens=192,
                temperature=0.0,
                top_p=1.0,
                stop=["\n\n"],
                grammar=grammar
            )
            text = response.get("choices", [{}])[0].get("text", "").strip()
            parsed = _extract_json(text)
            if parsed is None or not isinstance(parsed, dict):
                raise ValueError(f"Model did not return valid JSON: {text[:120]}...")
            if not parsed.get("name"):
                parsed["name"] = identifier
            if "exclude" not in parsed or not isinstance(parsed["exclude"], bool) or "reason" not in parsed or not isinstance(parsed["reason"], str):
                raise ValueError(f"Missing required keys in JSON (got keys: {list(parsed.keys())[:6]})")
            results.append({"name": parsed["name"], "exclude": parsed["exclude"], "reason": parsed["reason"]})
        except Exception as e:
            results.append({"name": identifier, "exclude": False, "reason": f"LLM JSON parse error: {str(e)}" if str(e) else "Invalid JSON from model"})
    return results

@app.route('/exclude', methods=['POST'])
def analyze_exclude():
    """Analyze identifiers for exclusion list using LLM"""
    try:
        data = request.get_json(silent=True) or {}

        # Support original (flat) schema and the user-provided nested schema with top-level { instruction, input: { ... } }
        payload = dict(data)
        if isinstance(data.get("input"), dict):
            # Merge but keep explicit top-level fields if already provided
            inp = data["input"]
            for k in ("swift_code", "symbol_info", "identifiers"):
                if k not in payload and k in inp:
                    payload[k] = inp[k]

        # Primary: explicit identifiers
        identifiers = payload.get('identifiers')

        # Fallbacks: derive from symbol_info
        if identifiers is None:
            sym = payload.get('symbol_info')
            if isinstance(sym, dict) and sym:
                extracted = _extract_identifiers_from_symbol_info(sym)
                if extracted:
                    identifiers = extracted
                else:
                    # Last resort: use top-level keys
                    identifiers = [str(k) for k in sym.keys()]
            else:
                return jsonify({"error": "'identifiers' field is required or provide 'symbol_info' with keys to analyze"}), 400

        # Normalize types
        if isinstance(identifiers, dict):
            identifiers = list(identifiers.keys())
        elif not isinstance(identifiers, list):
            return jsonify({"error": "'identifiers' must be a list (or provide 'symbol_info' dict)"}), 400

        # Coerce all to strings and filter empties
        identifiers = [str(x).strip() for x in identifiers if str(x).strip()]

        if len(identifiers) == 0:
            return jsonify({"error": "No identifiers provided"}), 400

        symbol_info = payload.get('symbol_info') if isinstance(payload.get('symbol_info'), dict) else None
        swift_code = payload.get('swift_code') if isinstance(payload.get('swift_code'), str) else None
        results = _call_exclude_llm(identifiers, symbol_info=symbol_info, swift_code=swift_code)
        if results is None:
            return jsonify({"error": "LLM analysis failed"}), 500
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def _validate_results_schema(results):
    if not isinstance(results, list):
        raise RuntimeError("LLM JSON must be a list")
    for i, item in enumerate(results):
        if not isinstance(item, dict):
            raise RuntimeError(f"LLM JSON item #{i} is not an object")
        for k in ("name", "sensitive", "reason"):
            if k not in item:
                raise RuntimeError(f"LLM JSON item #{i} missing key: {k}")
        if not isinstance(item["name"], str):
            raise RuntimeError(f"LLM JSON item #{i} 'name' must be string")
        if not isinstance(item["sensitive"], bool):
            raise RuntimeError(f"LLM JSON item #{i} 'sensitive' must be boolean")
        if not isinstance(item["reason"], str):
            raise RuntimeError(f"LLM JSON item #{i} 'reason' must be string")

def _load_identifiers_from_config(path: str) -> list[str]:
    """
    Load identifiers from a user-provided config file.
    Supported:
      - JSON file with {"identifiers": [...]}  OR arbitrary JSON object (keys used as identifiers)
      - Plain text file (one identifier per line)
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    if p.suffix.lower() in (".json",):
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            if "identifiers" in data and isinstance(data["identifiers"], list):
                return [str(x) for x in data["identifiers"]]
            # Use top-level keys as identifiers for generic JSON objects
            return [str(k) for k in data.keys()]
        elif isinstance(data, list):
            return [str(x) for x in data]
        else:
            raise ValueError("Unsupported JSON structure; expected list or object.")
    else:
        # Fallback: plain text, one identifier per line
        with open(p, "r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f.readlines()]
        return [ln for ln in lines if ln]

def _interactive_review(identifiers: list[str], out_path: str | None = None) -> None:
    """
    Run interactive Y/N review in the terminal.
    Calls the local analyzer first, then lets the user confirm/override each result.
    Writes a JSON summary if out_path is provided.
    """
    print("\n== Sensitivity Review (interactive) ==")
    results = _call_actual_llm(identifiers)
    reviewed = []
    for item in results:
        name = item.get("name")
        pred_sensitive = bool(item.get("sensitive", False))
        reason = item.get("reason", "")
        default = "y" if pred_sensitive else "n"
        print("\n----------------------------------------")
        print(f"Identifier : {name}")
        print(f"Model says : {'SENSITIVE' if pred_sensitive else 'NOT SENSITIVE'}")
        print(f"Reason     : {reason}")
        ans = input(f"Mark as sensitive? [y/n] (default: {default}) > ").strip().lower()
        if ans not in ("y", "n", ""):
            print("  (Please type 'y' or 'n' or press Enter for default)")
            ans = input(f"Mark as sensitive? [y/n] (default: {default}) > ").strip().lower()
        final_sensitive = pred_sensitive if ans == "" else (ans == "y")
        reviewed.append({
            "name": name,
            "sensitive": final_sensitive,
            "reason": reason,
            "model_sensitive": pred_sensitive
        })
    print("\n== Review complete ==")
    if out_path:
        out_p = Path(out_path)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump({"results": reviewed}, f, ensure_ascii=False, indent=2)
        print(f"Wrote review summary to: {out_p.resolve()}")
    else:
        print(json.dumps({"results": reviewed}, ensure_ascii=False, indent=2))

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        gram_ok = _build_exclude_json_grammar() is not None
    except Exception:
        gram_ok = False
    return jsonify({"status": "healthy", "exclude_grammar": bool(gram_ok)})

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="LLM server / interactive reviewer")
    parser.add_argument("--review", type=str, help="Run interactive Y/N review using the given config file.")
    parser.add_argument("--out", type=str, help="Path to write JSON review summary (used with --review).")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Server host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Server port (default: 8000)")
    args = parser.parse_args()

    if args.review:
        ids = _load_identifiers_from_config(args.review)
        if not ids:
            print("No identifiers found in the provided config.")
            sys.exit(1)
        _interactive_review(ids, args.out)
        sys.exit(0)

    print(f"Starting LLM server on http://{args.host}:{args.port}")
    print("Endpoints:")
    print("  POST /analyze - Analyze identifier sensitivity")
    print("  POST /exclude - Analyze identifier exclusion")
    print("  GET /health - Health check")
    app.run(host=args.host, port=args.port, debug=False)