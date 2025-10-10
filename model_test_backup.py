import json
import os
import re
import argparse
from typing import Optional
from pathlib import Path
import sys
sys.path.append(os.path.abspath("../../ConsoleLLM_Portable"))
from flask import Flask, request, jsonify
from flask_cors import CORS
from llama_cpp import Llama, LlamaGrammar

# === 모델 로드 (지연 로딩) ===
llm_base = None
llm_sensitive = None
llm_exclude_swift = None

def get_llm_base():
    global llm_base
    if llm_base is None:
        llm_base = Llama(
            model_path="models/base_model.gguf",
            n_gpu_layers=12,    # 더 줄임
            n_ctx=2048,        # 더 줄임
        )
    return llm_base

def get_llm_sensitive():
    global llm_sensitive
    if llm_sensitive is None:
        llm_sensitive = Llama(
            model_path="models/base_model.gguf",
            lora_base="models/base_model.gguf",
            lora_path="models/lora_sensitive.gguf",
            n_gpu_layers=5,
            n_ctx=1024,
        )
    return llm_sensitive

def get_llm_exclude_swift():
    global llm_exclude_swift
    if llm_exclude_swift is None:
        llm_exclude_swift = Llama(
            model_path="models/base_model.gguf",
            lora_base="models/base_model.gguf",
            lora_path="models/lora_exclude_swift.gguf",
            n_gpu_layers=12,
            n_ctx=4096,  # 컨텍스트 윈도우 증가
            verbose=False,  # 로그 줄임
        )
    return llm_exclude_swift

def cleanup_models():
    """모델 메모리 정리"""
    global llm_base, llm_sensitive, llm_exclude_swift
    if llm_base:
        del llm_base
        llm_base = None
    if llm_sensitive:
        del llm_sensitive
        llm_sensitive = None
    if llm_exclude_swift:
        del llm_exclude_swift
        llm_exclude_swift = None
    import gc
    gc.collect()

# === FastAPI 앱 ===
app = FastAPI()

class PromptRequest(BaseModel):
    prompt: str
    max_tokens: int = 256
    temperature: float = 0.7

@app.post("/generate")
def generate(req: PromptRequest):
    output = get_llm_base()(
        req.prompt,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
    )
    return {"text": output["choices"][0]["text"]}


# === 민감도 분석 엔드포인트 ===

class AnalyzeRequest(BaseModel):
    identifiers: list[str]
    max_tokens: int = 256
    temperature: float = 0.2


class AnalyzeSwiftRequest(BaseModel):
    instruction: str
    input: dict
    max_tokens: int = 256
    temperature: float = 0.0

@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    # 각 식별자에 대해 개별적으로 처리
    results = []

    for identifier in req.identifiers:
        prompt = (
            "You are an assistant that decides whether a single Swift identifier must be excluded from source-level obfuscation.\n"
            "Return ONLY a single-line JSON object with keys exactly: name (string), exclude (boolean), reason (string).\n"
            "No explanations, no markdown, no backticks, no surrounding text. Output must end right after the closing brace '}'.\n"
            "Decision rules: Exclude UI components, delegates, public APIs, @objc methods, protocol requirements.\n"
            f"Identifier: \"{identifier}\""
        )

        raw = get_llm_sensitive()(
            prompt,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
        )["choices"][0]["text"]

        print(f"Model raw output for {identifier}: {raw}")  # 디버그 출력

        # JSON 파싱
        try:
            # JSON 객체 찾기
            json_match = re.search(r'\{[^}]*"exclude"[^}]*\}', raw)
            if json_match:
                parsed = json.loads(json_match.group(0))
                results.append({
                    "identifier": parsed.get("name", identifier),
                    "exclude": parsed.get("exclude", False),
                    "reason": parsed.get("reason", "Model analysis")
                })
            else:
                # Fallback: 전체 텍스트에서 JSON 찾기
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    results.append({
                        "identifier": parsed.get("name", identifier),
                        "exclude": parsed.get("exclude", False),
                        "reason": parsed.get("reason", "Model analysis")
                    })
                else:
                    raise ValueError("No valid JSON found")
        except Exception as e:
            print(f"JSON parsing failed for {identifier}: {e}")
            # Fallback: 규칙 기반 분석
            if any(keyword in identifier.lower() for keyword in ['viewcontroller', 'datasource', 'delegate', 'button', 'label']):
                results.append({
                    "identifier": identifier,
                    "exclude": True,
                    "reason": "UI component or delegate method - should not be obfuscated"
                })
            else:
                results.append({
                    "identifier": identifier,
                    "exclude": False,
                    "reason": "Internal implementation - safe to obfuscate"
                })

    return {"results": results}


import re, json

@app.post("/analyze_swift")
def analyze_swift(req: AnalyzeSwiftRequest):
    # input_part.json 형식에서 데이터 추출
    swift_code = req.input.get("swift_code", "")
    symbol_info = req.input.get("symbol_info", {})
    instruction = req.instruction
    
    # symbol_info에서 식별자들 추출
    identifiers = []
    if "decisions" in symbol_info:
        decisions = symbol_info["decisions"]
        for category in ["classes", "properties", "methods", "initializers", "structs", "enums", "protocols"]:
            if category in decisions:
                for item in decisions[category]:
                    if isinstance(item, dict) and "symbol_name" in item:
                        identifiers.append(item["symbol_name"])
    
    if not identifiers:
        return {"result": []}
    
    # 전체 분석을 한 번에 처리
    prompt = (
        f"{instruction}\n\n"
        f"Swift Code:\n{swift_code}\n\n"
        f"Symbol Info: {json.dumps(symbol_info, ensure_ascii=False)}"
    )
    
    raw = get_llm_exclude_swift()(
        prompt,
        max_tokens=8192,  # 토큰 수 대폭 증가
        temperature=req.temperature,
    )["choices"][0]["text"]
    
    # 첫 번째 완전한 JSON 찾아서 조기 종료
    print(f"=== JSON 검색 시작 ===")
    print(f"Raw output contains 'results': {'\"results\"' in raw}")
    print(f"Raw output contains 'error': {'\"error\"' in raw}")

    if '"results"' in raw:
        # {"results": [...] 패턴 찾기
        start_idx = raw.find('{"results"')
        print(f"Found start pattern at index: {start_idx}")

        if start_idx != -1:
            # 중괄호 카운트로 JSON 끝 찾기
            brace_count = 0
            json_end = start_idx
            for i, char in enumerate(raw[start_idx:], start_idx):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        json_end = i + 1
                        break

            print(f"JSON end found at index: {json_end}")
            print(f"Original length: {len(raw)}, Extracted length: {json_end - start_idx}")

            # 첫 번째 완전한 JSON만 사용
            raw = raw[start_idx:json_end]
            print(f"=== 첫 번째 완전한 JSON 추출로 조기 종료 ===")
        else:
            print(f"=== JSON 패턴을 찾을 수 없음 ===")
    else:
        print(f"=== 'results' 키를 찾을 수 없음 ===")
    
    print(f"=== Model raw output ===")
    print(f"Raw text: {repr(raw)}")
    print(f"Raw text (display): {raw}")
    print(f"Length: {len(raw)}")
    print("=" * 50)

    # JSON 파싱 및 결과 반환
    try:
        parsed = json.loads(raw)
        results = parsed.get("results", [])

        # 결과 변환: identifier -> name으로 매핑
        converted_results = []
        for result in results:
            converted_results.append({
                "name": result.get("name", ""),
                "exclude": result.get("exclude", False),
                "reason": result.get("reason", "")
            })

        return {"results": converted_results}

    except json.JSONDecodeError as e:
        print(f"=== JSON 파싱 실패: {e} ===")
        return {"raw_output": raw, "error": "JSON parsing failed"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)