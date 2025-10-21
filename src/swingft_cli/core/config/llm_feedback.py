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


