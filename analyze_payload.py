#!/usr/bin/env python3
import os
import json
import requests
import sys

SERVER_URL = "http://localhost:8000/complete"

def extract_first_json(text: str):
    """full_output에서 첫 번째 JSON 객체만 추출"""
    depth, start = 0, -1
    for i, ch in enumerate(text):
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
    return None

def main():
    if len(sys.argv) != 2:
        print("사용법: python analyze_payload.py <payload.json 파일 경로>")
        sys.exit(1)

    file_path = sys.argv[1]
    if not os.path.exists(file_path):
        print(f"파일을 찾을 수 없습니다: {file_path}")
        sys.exit(1)

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"[*] 서버 요청 중... ({file_path})")
    resp = requests.post(SERVER_URL, json=data, timeout=180)
    if resp.status_code != 200:
        print(f"[!] 요청 실패: {resp.status_code}")
        print(resp.text)
        sys.exit(1)

    result = resp.json()
    full_output = result.get("full_output", "")
    parsed = extract_first_json(full_output)

    print("\n===== RAW full_output =====")
    print(full_output.strip())

    print("\n===== Parsed JSON =====")
    if parsed:
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
    else:
        print("⚠️ JSON 파싱 실패")

if __name__ == "__main__":
    main()