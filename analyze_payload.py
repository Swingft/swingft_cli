#!/usr/bin/env python3
import os
import sys
import json
from typing import Any, Dict

try:
    from llama_cpp import Llama
except Exception as e:
    print("llama-cpp-python 미설치: pip install llama-cpp-python", file=sys.stderr)
    raise


def extract_first_json(text: str):
    """full_output에서 첫 번째 JSON 객체만 추출"""
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
                    return json.loads(text[start:i+1])
                except json.JSONDecodeError:
                    break

    # Fallback: try to find a ```json fenced block
    try:
        import re
        m = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", text or "", re.MULTILINE)
        if m:
            return json.loads(m.group(1))
    except Exception:
        pass

    return None



def build_prompt_from_cli_payload(p: Dict[str, Any]) -> str:
    code = p.get("swift_code", "")
    ident = p.get("target_identifier", "")
    ast_list = p.get("ast_symbols") or []
    ast = ast_list[0] if isinstance(ast_list, list) and ast_list else {}
    try:
        ast_json = json.dumps(ast, ensure_ascii=False, indent=2)
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
        f"**Swift Source Code:**\n```swift\n{code}\n```\n\n"
        f"**AST Symbol Information (Target: `{ident}`):**\n```json\n{ast_json}\n```\n\n"
        f"**Target Identifier:** `{ident}`\n\n{guard}"
    )

def build_prompt(payload: Dict[str, Any]) -> str:
    try:
        # New CLI schema detection
        if (
            isinstance(payload, dict)
            and "swift_code" in payload
            and "ast_symbols" in payload
            and "target_identifier" in payload
        ):
            return build_prompt_from_cli_payload(payload)
        # Fallback: raw JSON dump
        return json.dumps(payload, ensure_ascii=False)
    except Exception:
        return str(payload)


def load_llm() -> Llama:
    base_model = os.getenv("BASE_MODEL_PATH", "./models/base_model.gguf")
    lora_path = os.getenv("LORA_PATH", os.path.join("./models", "lora_sensitive_single.gguf"))
    n_ctx = int(os.getenv("N_CTX", "8192"))
    n_threads = int(os.getenv("N_THREADS", str(os.cpu_count() or 8)))
    n_gpu_layers = int(os.getenv("N_GPU_LAYERS", "12"))  # 0=CPU only

    kwargs = dict(
        model_path=base_model,
        n_ctx=n_ctx,
        n_threads=n_threads,
        logits_all=False,
        verbose=False,
    )
    # 선택적 인자들만 추가
    if lora_path and str(lora_path).strip():
        kwargs["lora_path"] = lora_path
    if n_gpu_layers:
        kwargs["n_gpu_layers"] = n_gpu_layers

    return Llama(**kwargs)


def run_inference(llm: Llama, prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    max_tokens = int(payload.get("max_tokens", os.getenv("MAX_TOKENS", "512")))
    temperature = float(payload.get("temperature", os.getenv("TEMPERATURE", "0.0")))
    top_p = float(payload.get("top_p", os.getenv("TOP_P", "1.0")))
    stop = payload.get("stop")
    # Do not force stop tokens; some models begin with code fences and would yield empty output.
    if not stop:
        stop = None

    resp = llm(
        prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        stop=stop,
    )
    full_text = (resp.get("choices", [{}])[0] or {}).get("text", "")
    first_line = full_text.splitlines()[0] if isinstance(full_text, str) and full_text.splitlines() else full_text
    return {
        "input": prompt,
        "output": first_line,
        "full_output": full_text,
        "params": {
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stop": stop,
        },
    }


def main():
    if len(sys.argv) != 2:
        print("사용법: python analyze_payload.py <payload.json 파일 경로>")
        sys.exit(1)

    file_path = sys.argv[1]
    if not os.path.exists(file_path):
        print(f"파일을 찾을 수 없습니다: {file_path}")
        sys.exit(1)

    with open(file_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    prompt = build_prompt(payload)
    llm = load_llm()

    print(f"[*] 로컬 llama.cpp 호출 중... ({file_path})")
    result = run_inference(llm, prompt, payload)

    full_output = result.get("full_output", "")
    parsed = extract_first_json(full_output)

    print("\n===== RAW full_output =====")
    print((full_output or "").strip())

    print("\n===== Parsed JSON =====")
    if parsed:
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
    else:
        print("⚠️ JSON 파싱 실패")


if __name__ == "__main__":
    main()