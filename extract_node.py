#!/usr/bin/env python3
"""
extract_node.py
AST JSON에서 지정한 A_name을 포함하는 '묶음(최상위 엔트리 전체)'을 찾아 파일로 저장.

사용 예:
  # 첫 번째 일치 묶음만 저장
  python3 extract_node.py --input ast_node.json --name ChooseViewController --output outdir

  # 일치하는 모든 묶음 저장
  python3 extract_node.py --input ast_node.json --name ChooseViewController --output outdir --all
"""

import argparse
import json
import os
import sys
from typing import Any, List, Optional


def contains_target(item: Any, target: str) -> bool:
    """item 하위에 A_name == target 이 하나라도 있으면 True."""
    if isinstance(item, dict):
        if item.get("A_name") == target:
            return True
        node = item.get("node")
        if isinstance(node, dict) and node.get("A_name") == target:
            return True

        # 흔히 쓰는 컨테이너 키 우선 탐색
        for key in ("children", "extension", "G_members", "node"):
            if key in item and contains_target(item[key], target):
                return True

        # 남은 값들도 안전하게 스캔
        for v in item.values():
            if contains_target(v, target):
                return True

    elif isinstance(item, list):
        for elem in item:
            if contains_target(elem, target):
                return True

    return False


def find_top_level_bundles(data: List[Any], target: str) -> List[Any]:
    """최상위 배열(data)에서 target을 포함하는 엔트리들을 모두 반환."""
    results = []
    for entry in data:
        try:
            if contains_target(entry, target):
                results.append(entry)
        except RecursionError:
            # 비정상 순환 구조 방어
            continue
    return results


def main():
    ap = argparse.ArgumentParser(description="AST JSON에서 A_name으로 최상위 묶음 추출")
    ap.add_argument("-i", "--input", required=True, help="입력 JSON 경로 (예: ast_node.json)")
    ap.add_argument("-n", "--name", required=True, help="찾을 A_name (정확 일치)")
    ap.add_argument("-o", "--output", default=".", help="출력 디렉터리 (기본: 현재 폴더)")
    ap.add_argument("--all", action="store_true", help="일치하는 모든 묶음을 각각 저장")
    args = ap.parse_args()

    if not os.path.isfile(args.input):
        print(f"입력 파일을 찾을 수 없음: {args.input}", file=sys.stderr)
        sys.exit(2)

    try:
        with open(args.input, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"JSON 파싱 실패: {e}", file=sys.stderr)
        sys.exit(3)

    if not isinstance(data, list):
        print("최상위 구조가 배열이어야 함.", file=sys.stderr)
        sys.exit(4)

    bundles = find_top_level_bundles(data, args.name)
    if not bundles:
        print(f"A_name == {args.name} 포함 묶음 없음", file=sys.stderr)
        sys.exit(5)

    os.makedirs(args.output, exist_ok=True)

    written_paths: List[str] = []
    if args.all:
        for idx, bundle in enumerate(bundles, start=1):
            out_path = os.path.join(args.output, f"{args.name}_{idx}.json")
            with open(out_path, "w", encoding="utf-8") as out:
                json.dump(bundle, out, ensure_ascii=False, indent=2)
            written_paths.append(out_path)
    else:
        out_path = os.path.join(args.output, f"{args.name}.json")
        with open(out_path, "w", encoding="utf-8") as out:
            json.dump(bundles[0], out, ensure_ascii=False, indent=2)
        written_paths.append(out_path)

    # 표준출력에 경로 나열
    for p in written_paths:
        print(p)


if __name__ == "__main__":
    main()