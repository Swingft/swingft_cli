from __future__ import annotations

import json
import os
from typing import Any


def post_complete(payload: dict) -> tuple[bool, str]:
    """Send payload dict verbatim to LLM /complete endpoint. Return (ok, raw_output_or_error)."""
    import requests
    url = os.environ.get("LLM_COMPLETE_URL", "http://127.0.0.1:8000/complete").strip()
    try:
        resp = requests.post(url, json=payload, timeout=120)
        ctype = resp.headers.get("content-type", "")
        if resp.status_code != 200:
            body = resp.text if isinstance(resp.text, str) else ""
            return False, f"HTTP {resp.status_code} at /complete: {body[:800]}"
        if ctype.startswith("application/json"):
            data = resp.json()
            raw = str(data.get("output") or data.get("full_output") or "")
            return True, raw
        return True, str(resp.text)
    except Exception as e:
        return False, f"REQUEST ERROR: {e}"


def build_structured_input(swift_code: str, symbol_info) -> str:
    try:
        if isinstance(symbol_info, (dict, list)):
            pretty = json.dumps(symbol_info, ensure_ascii=False, indent=2)
        elif isinstance(symbol_info, str) and symbol_info.strip():
            try:
                pretty = json.dumps(json.loads(symbol_info), ensure_ascii=False, indent=2)
            except Exception:
                pretty = symbol_info
        else:
            pretty = "[]"
    except Exception:
        pretty = "[]"
    swift = swift_code if isinstance(swift_code, str) else ""
    return (
        "**Swift Source Code:**\n"
        "```swift\n" + swift + "\n```\n\n"
        "**AST Symbol Information (JSON):**\n"
        "```\n" + pretty + "\n```"
    )


def call_exclude_server_parsed(identifiers, symbol_info=None, swift_code=None):
    try:
        import requests  # type: ignore
        use_requests = True
    except Exception:
        use_requests = False

    # Preferred structured
    try:
        if isinstance(identifiers, (list, tuple)) and len(identifiers) == 1 and (swift_code or symbol_info is not None):
            instr = "In the following Swift code, find all identifiers related to sensitive logic. Provide the names and reasoning as a JSON object."
            input_blob = build_structured_input(swift_code or "", symbol_info)
            url_struct = os.environ.get("SWINGFT_SENSITIVE_SERVER_URL_STRUCTURED", "").strip() or "http://localhost:8000/analyze_structured"
            payload_struct = {"instruction": instr, "input": input_blob}

            if use_requests:
                resp = requests.post(url_struct, json=payload_struct, timeout=60)
                status = resp.status_code
                body = resp.text or ""
            else:
                import urllib.request, urllib.error
                req = urllib.request.Request(
                    url_struct,
                    data=json.dumps(payload_struct).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=60) as r:
                    status = r.getcode()
                    body = r.read().decode("utf-8", errors="replace")

            if status == 200 and body:
                try:
                    j = json.loads(body)
                except Exception:
                    j = {}

                parsed_payload = None
                if isinstance(j, dict) and "output" in j:
                    try:
                        parsed_payload = json.loads(str(j.get("output") or "").strip())
                    except Exception:
                        parsed_payload = None
                elif isinstance(j, dict) and ("identifiers" in j or "reasoning" in j):
                    parsed_payload = j
                else:
                    try:
                        parsed_payload = json.loads(body)
                    except Exception:
                        parsed_payload = None

                if isinstance(parsed_payload, dict):
                    idents = parsed_payload.get("identifiers") or []
                    reason = str(parsed_payload.get("reasoning", "") or "")
                    out = []
                    for nm in idents:
                        nm_s = str(nm).strip()
                        if not nm_s:
                            continue
                        out.append({"name": nm_s, "exclude": True, "reason": reason})
                    return out
    except Exception as e:
        print(f"  - 경고: structured 분석 호출 실패: {e}")

    # Fallback legacy
    url = os.environ.get("SWINGFT_SENSITIVE_SERVER_URL", "http://localhost:8000/analyze_parsed").strip()
    payload = {"identifiers": list(identifiers)}
    if isinstance(symbol_info, dict) or isinstance(symbol_info, list):
        payload["symbol_info"] = symbol_info
    if isinstance(swift_code, str):
        payload["swift_code"] = swift_code

    try:
        if use_requests:
            resp = requests.post(url, json=payload, timeout=60)
            status = resp.status_code
            if status != 200:
                print(f"  - 경고: sensitive 서버 응답 오류 HTTP {status}")
                return None
            data = resp.json()
        else:
            import urllib.request, urllib.error
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                status = r.getcode()
                body = r.read().decode("utf-8", errors="replace")
            if status != 200:
                print(f"  - 경고: sensitive 서버 응답 오류 HTTP {status}")
                return None
            try:
                data = json.loads(body)
            except Exception as je:
                print(f"  - 경고: sensitive 서버 JSON 파싱 실패: {je}")
                return None

        results = data.get("results")
        if isinstance(results, list):
            out = []
            for it in results:
                if isinstance(it, dict):
                    name = str((it.get("name") or it.get("identifier") or "")).strip()
                    ex = bool(it.get("exclude", it.get("sensitive", False)))
                    reason = str(it.get("reason", ""))
                    if name:
                        out.append({"name": name, "exclude": ex, "reason": reason})
            return out
        return None
    except Exception as e:
        print(f"  - 경고: sensitive 서버 호출 실패: {e}")
        return None



# --- Snippet and AST analyzer helpers (moved from loader) ---
def find_first_swift_file_with_identifier(project_dir: str, ident: str):
    try:
        import os
        for root, dirs, files in os.walk(project_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in {'build', 'DerivedData'}]
            for fn in files:
                if not fn.lower().endswith('.swift'):
                    continue
                fp = os.path.join(root, fn)
                try:
                    with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                        text = f.read()
                    if ident in text:
                        return fp, text
                except Exception:
                    continue
    except Exception:
        return None
    return None


def make_snippet(text: str, ident: str, ctx_lines: int = 30) -> str:
    try:
        lines = text.splitlines()
        hit = None
        for i, ln in enumerate(lines):
            if ident in ln:
                hit = i
                break
        if hit is None:
            return text[:8000]
        lo = max(0, hit - ctx_lines)
        hi = min(len(lines), hit + ctx_lines + 1)
        snippet = "\n".join(lines[lo:hi])
        if len(snippet) > 8000:
            snippet = snippet[:8000] + "\n... [truncated]"
        return snippet
    except Exception:
        return text[:8000]


def _verbose() -> bool:
    try:
        import os as _os
        v = _os.environ.get("SWINGFT_PREFLIGHT_VERBOSE", "")
        return str(v).strip().lower() in {"1","true","yes","y","on"}
    except Exception:
        return False


def _locate_swift_ast_analyzer():
    """Find SwiftASTAnalyzer binary by probing common locations and limited walk. Cached."""
    global _ANALYZER_PATH_CACHE
    if _ANALYZER_PATH_CACHE is not None:
        return _ANALYZER_PATH_CACHE
    try:
        from pathlib import Path as _P
        override = os.environ.get('SWINGFT_AST_ANALYZER_PATH', '').strip()
        if override and _P(override).exists():
            _ANALYZER_PATH_CACHE = _P(override)
            return _ANALYZER_PATH_CACHE
        cwd = _P(os.getcwd())
        candidates = [
            cwd / 'ast_analyzers' / 'sensitive' / 'SwiftASTAnalyzer',
            cwd / 'ast_analyzers' / 'SwiftASTAnalyzer',
            cwd / '.swingft' / 'tools' / 'SwiftASTAnalyzer',
            cwd / 'tools' / 'SwiftASTAnalyzer',
            cwd / 'bin' / 'SwiftASTAnalyzer',
        ]
        for c in candidates:
            if c.exists():
                _ANALYZER_PATH_CACHE = c
                return _ANALYZER_PATH_CACHE
        # limited walk with pruned dirs
        prune = {'.git', '.venv', 'node_modules', 'DerivedData', 'build', '.build', 'Obfuscation_Pipeline'}
        max_depth = 4
        base_parts = len(cwd.parts)
        for root, dirs, files in os.walk(str(cwd)):
            # prune
            pd = []
            for d in list(dirs):
                if d in prune:
                    pd.append(d)
            for d in pd:
                dirs.remove(d)
            # depth limit
            if len(_P(root).parts) - base_parts > max_depth:
                dirs[:] = []
                continue
            if 'SwiftASTAnalyzer' in files:
                p = _P(root) / 'SwiftASTAnalyzer'
                if p.exists():
                    _ANALYZER_PATH_CACHE = p
                    return _ANALYZER_PATH_CACHE
    except Exception:
        pass
    _ANALYZER_PATH_CACHE = None
    return None


def run_swift_ast_analyzer(swift_file_path: str):
    """Execute local Swift AST analyzer binary and parse JSON from stdout."""
    try:
        import subprocess, os
        from pathlib import Path
        analyzer_path = _locate_swift_ast_analyzer()
        if not analyzer_path or not Path(analyzer_path).exists():
            if _verbose():
                print(f"Warning: AST analyzer not found at {analyzer_path}")
            return None
        command_str = f'"{str(analyzer_path)}" "{swift_file_path}"'
        proc = subprocess.run(
            command_str,
            shell=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=60,
        )
        if proc.returncode != 0:
            err = (proc.stderr or '').strip()
            if _verbose():
                print(f"Warning: AST analyzer failed for {swift_file_path}. Error: {err}")
            return None
        out = (proc.stdout or '').strip()
        if not out:
            return None
        lb = out.find('[')
        lb2 = out.find('{')
        if lb == -1 and lb2 == -1:
            return None
        json_start = lb if (lb != -1 and (lb < lb2 or lb2 == -1)) else lb2
        json_part = out[json_start:]
        import json as _json
        try:
            data = _json.loads(json_part)
            return data
        except Exception:
            return None
    except subprocess.TimeoutExpired:
        if _verbose():
            print(f"Warning: AST analysis timed out for {swift_file_path}")
        return None
    except Exception as e:
        if _verbose():
            print(f"Warning: AST analysis failed for {swift_file_path}: {e}")
        return None


# --- Local LLM inference (analyze_payload 스타일) ---
def _extract_first_json(text: str):
    try:
        import json as _json
        depth, start = 0, -1
        for i, ch in enumerate(text or ""):
            if ch == '{':
                if start < 0:
                    start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and start >= 0:
                    try:
                        return _json.loads((text[start:i+1]))
                    except Exception:
                        break
        # fenced block fallback
        try:
            import re
            m = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", text or "", re.MULTILINE)
            if m:
                return _json.loads(m.group(1))
        except Exception:
            pass
    except Exception:
        pass
    return None


def _build_prompt_for_identifier(swift_code: str, target_identifier: str, ast_symbols) -> str:
    try:
        import json as _json
        ast = None
        if isinstance(ast_symbols, list) and ast_symbols:
            ast = ast_symbols[0]
        elif isinstance(ast_symbols, dict):
            ast = ast_symbols
        else:
            ast = {}
        ast_json = "{}"
        try:
            ast_json = _json.dumps(ast, ensure_ascii=False, indent=2)
        except Exception:
            ast_json = "{}"
    except Exception:
        ast_json = "{}"
    instr = (
        "Analyze whether the target identifier in the Swift code is security-sensitive. "
        "Provide your judgment and reasoning."
    )
    guard = (
        "Respond with a single JSON object only. No code fences. "
        "Keys: is_sensitive, reasoning."
    )
    return (
        f"{instr}\n\n"
        f"**Swift Source Code:**\n```swift\n{swift_code or ''}\n```\n\n"
        f"**AST Symbol Information (Target: `{target_identifier}`):**\n```json\n{ast_json}\n```\n\n"
        f"**Target Identifier:** `{target_identifier}`\n\n{guard}"
    )


_LLM_SINGLETON = None
_ANALYZER_PATH_CACHE = None


def _load_llm_singleton():
    global _LLM_SINGLETON
    if _LLM_SINGLETON is not None:
        return _LLM_SINGLETON
    try:
        from llama_cpp import Llama  # type: ignore
    except Exception:
        return None
    import os as _os
    base_model = _os.getenv("BASE_MODEL_PATH", "./models/base_model.gguf")
    lora_path = _os.getenv("LORA_PATH", _os.path.join("./models", "lora_sensitive_single.gguf"))
    n_ctx = int(_os.getenv("N_CTX", "8192"))
    n_threads = int(_os.getenv("N_THREADS", str(os.cpu_count() or 8)))
    n_gpu_layers = int(_os.getenv("N_GPU_LAYERS", "12"))
    kwargs = dict(
        model_path=base_model,
        n_ctx=n_ctx,
        n_threads=n_threads,
        logits_all=False,
        verbose=False,
    )
    if lora_path and str(lora_path).strip():
        kwargs["lora_path"] = lora_path
    if n_gpu_layers:
        kwargs["n_gpu_layers"] = n_gpu_layers
    try:
        _LLM_SINGLETON = Llama(**kwargs)
    except Exception:
        _LLM_SINGLETON = None
    return _LLM_SINGLETON


def run_local_llm_exclude(identifier: str, swift_code: str, ast_symbols) -> list | None:
    """Return list[{name, exclude(bool), reason}] based on local llama inference.
    If llama not available or parsing fails, return None.
    """
    llm = _load_llm_singleton()
    if llm is None:
        return None
    prompt = _build_prompt_for_identifier(swift_code or "", identifier, ast_symbols)
    try:
        max_tokens = int(os.getenv("MAX_TOKENS", "512"))
        temperature = float(os.getenv("TEMPERATURE", "0.0"))
        top_p = float(os.getenv("TOP_P", "1.0"))
        resp = llm(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stop=None,
        )
        full_text = (resp.get("choices", [{}])[0] or {}).get("text", "")
        parsed = _extract_first_json(full_text or "")
        if isinstance(parsed, dict):
            is_sensitive = bool(parsed.get("is_sensitive", True))
            reason = str(parsed.get("reasoning", "") or "")
            return [{"name": identifier, "exclude": is_sensitive, "reason": reason}]
    except Exception:
        return None
    return None


# --- Fallback: pull symbol info from pipeline AST output ---
def find_ast_entry_from_pipeline(project_root: str, ident: str):
    try:
        import os as _os, json as _json
        from pathlib import Path as _P
        env_ast = _os.environ.get("SWINGFT_AST_NODE_PATH", "").strip()
        candidates = []
        if env_ast:
            candidates.append(env_ast)
        # common default locations
        candidates.extend([
            str(_P(os.getcwd()) / "Obfuscation_Pipeline" / "AST" / "output" / "ast_node.json"),
            str(_P(os.getcwd()) / "AST" / "output" / "ast_node.json"),
        ])
        ast_path = next((p for p in candidates if _P(p).exists()), None)
        if not ast_path:
            return None
        with open(ast_path, 'r', encoding='utf-8') as f:
            data = _json.load(f)
        # minimal presence check; we don't depend on schema here
        # return a synthesized entry focusing on the target identifier name
        return {"symbolName": ident, "symbolKind": "unknown", "source": "pipeline_ast"}
    except Exception:
        return None


def resolve_ast_symbols(project_root: str, swift_path: str | None, ident: str):
    """Best-effort AST symbol info for LLM prompt.
    Order: analyzer (if available) -> pipeline ast_node.json minimal entry -> None
    Returns either a dict or list compatible with downstream usage.
    """
    try:
        if swift_path:
            res = run_swift_ast_analyzer(swift_path)
            if res:
                return res
    except Exception:
        pass
    fb = find_ast_entry_from_pipeline(project_root, ident)
    if fb:
        return [fb]
    return None
