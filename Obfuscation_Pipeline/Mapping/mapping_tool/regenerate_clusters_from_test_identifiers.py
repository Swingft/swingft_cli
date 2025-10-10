#!/usr/bin/env python3
"""
test_identifiers.json 기반으로 중복 제거 후 클러스터 재생성
- kind별로 Jaro-Winkler 임계치를 자동으로 낮추며(~0.75까지) 목표 클러스터 수(기본 500개) 이하가 되도록 조정
- 결과물을 clusters_{kind}.json / cluster_index_{kind}.json / safe_pool_{kind}.txt 로 저장

실행 예:
  python3 regenerate_clusters_from_test_identifiers.py \
    --test-identifiers /path/to/test_identifiers.json \
    --output-dir name_clusters_autotuned \
    --target-clusters 500 \
    --jw-start 0.88 --jw-min 0.75 --jw-step 0.01 \
    --max-compare 60000
"""

import argparse
import json
from pathlib import Path
import sys
from typing import List

# 원본 클러스터링 유틸 사용 (네 기존 코드의 import 경로와 동일)
sys.path.append('/Users/lanian/Desktop/S_DEV/git_crwaling')
from cluster_identifiers import (
    cluster_names,              # (identifiers, jw_threshold, max_compare) -> List[List[str]]
    cluster_rep_and_tokens      # (cluster: List[str]) -> (rep: str, tokens: List[str])
)

KINDS = ['class', 'struct', 'enum', 'protocol', 'extension', 'typealias', 'function', 'variable']

def split_oversized_clusters(clusters: List[List[str]],
                             max_cluster_size: int,
                             jw_seed: float,
                             split_step: float,
                             split_max: float,
                             max_compare: int) -> List[List[str]]:
    """
    Any cluster with size > max_cluster_size will be recursively re-clustered
    with *stricter* JW thresholds (increasing from jw_seed by split_step),
    up to split_max. This prevents single mega-clusters by forcing them to split.
    Returns a new list of clusters (flattened).
    """
    if max_cluster_size <= 0:
        return clusters

    new_clusters: List[List[str]] = []
    for c in clusters:
        if len(c) <= max_cluster_size:
            new_clusters.append(c)
            continue
        # progressively tighten JW threshold to split large cluster
        jw_inner = jw_seed
        parts = [c]
        while True:
            # stop if all parts are under the cap or jw reached ceiling
            if all(len(p) <= max_cluster_size for p in parts) or jw_inner >= split_max:
                break
            jw_inner = min(split_max, round(jw_inner + split_step, 6))
            next_parts: List[List[str]] = []
            for p in parts:
                if len(p) > max_cluster_size:
                    sub = cluster_names(p, jw_threshold=jw_inner, max_compare=max_compare)
                    # ensure deterministic ordering inside this loop
                    sub.sort(key=lambda cc: (-len(cc), cc[0].lower()))
                    next_parts.extend(sub)
                else:
                    next_parts.append(p)
            parts = next_parts
        new_clusters.extend(parts)
    # stable sort: largest first then alpha
    new_clusters.sort(key=lambda c: (-len(c), c[0].lower()))
    return new_clusters


def load_test_identifiers(path: Path) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    # 기대 구조: {"counts": {...}, "unique_counts": {...}, "buckets": {kind: [names...]}}
    if 'buckets' not in data or not isinstance(data['buckets'], dict):
        raise ValueError("test_identifiers.json: 'buckets' 키가 없거나 형식이 다릅니다.")
    return data['buckets']


def dedup_identifiers(buckets: dict) -> dict:
    """각 kind별 리스트에서 공백/빈값 제거 + 중복 제거(set) + 정렬"""
    out = {}
    for kind in KINDS:
        names = buckets.get(kind, []) or []
        # strip + truthy
        names = [s.strip() for s in names if isinstance(s, str) and s.strip()]
        # set dedup
        uniq = sorted(set(names), key=lambda s: s.lower())
        out[kind] = uniq
    return out


def autotune_by_target(identifiers, jw_start: float, jw_min: float, jw_step: float,
                       target_clusters: int, max_compare: int):
    """
    jw를 jw_start부터 jw_min까지 step으로 낮추며
    '클러스터 개수 <= target_clusters' 만족하는 첫 지점을 찾음.
    실패하면 마지막 시도 결과를 반환.
    """
    jw = jw_start
    best = None
    best_jw = jw_start
    while True:
        clusters = cluster_names(identifiers, jw_threshold=jw, max_compare=max_compare)
        best = (jw, clusters)
        print(f"    [auto] jw={jw:.3f} → clusters={len(clusters)}")
        if len(clusters) <= target_clusters:
            return jw, clusters
        jw_next = round(jw - jw_step, 6)
        if jw_next < jw_min:
            print(f"    [auto] min jw({jw_min:.3f}) 도달 — 조건 미충족. 마지막 결과 사용.")
            return best
        jw = jw_next


def build_index(clusters):
    """
    cluster_index_* 형식 구성:
    [
      {"size": N, "rep": "...", "tokens": [...], "members": [...]},
      ...
    ]
    """
    index = []
    for c in clusters:
        rep, tokens = cluster_rep_and_tokens(c)
        index.append({
            "size": len(c),
            "rep": rep,
            "tokens": tokens,
            "members": c
        })
    return index


def save_outputs(kind: str, clusters, index, safe_pool, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / f"clusters_{kind}.json", 'w', encoding='utf-8') as f:
        json.dump(clusters, f, indent=2, ensure_ascii=False)
    with open(out_dir / f"cluster_index_{kind}.json", 'w', encoding='utf-8') as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    with open(out_dir / f"safe_pool_{kind}.txt", 'w', encoding='utf-8') as f:
        for name in safe_pool:
            f.write(name + "\n")


def main():
    ap = argparse.ArgumentParser(description="test_identifiers.json → 중복 제거 + JW 자동튜닝 클러스터 생성")
    ap.add_argument("--test-identifiers", required=True, help="test_identifiers.json 경로")
    ap.add_argument("--output-dir", default="name_clusters_autotuned", help="결과 출력 디렉터리")
    ap.add_argument("--target-clusters", type=int, default=500, help="kind별 목표 클러스터 수 (이하가 되면 정지)")
    ap.add_argument("--jw-start", type=float, default=0.88, help="자동튜닝 시작 Jaro-Winkler 임계치")
    ap.add_argument("--jw-min", type=float, default=0.75, help="자동튜닝 최저 Jaro-Winkler 임계치")
    ap.add_argument("--jw-step", type=float, default=0.01, help="임계치 감소 간격")
    ap.add_argument("--max-compare", type=int, default=60000, help="최대 비교 쌍 수")
    ap.add_argument("--max-cluster-size", type=int, default=300,
                    help="클러스터 최대 크기(cap). 초과 클러스터는 내부에서 JW 임계치를 높여 재클러스터링")
    ap.add_argument("--split-jw-step", type=float, default=0.02,
                    help="오버사이즈 클러스터 분할 시 내부 JW 임계치 증가 간격")
    ap.add_argument("--split-jw-max", type=float, default=0.95,
                    help="오버사이즈 클러스터 분할 시 내부 JW 임계치 상한")
    args = ap.parse_args()

    test_path = Path(args.test_identifiers)
    out_dir = Path(args.output_dir)

    print(f"[LOAD] {test_path}")
    buckets = load_test_identifiers(test_path)
    print("[DEDUP] 각 kind별 중복 제거 및 정렬")
    deduped = dedup_identifiers(buckets)

    print("="*72)
    print(f"TARGET per-kind clusters ≤ {args.target_clusters}")
    print(f"JW start={args.jw_start}  min={args.jw_min}  step={args.jw_step}  max_compare={args.max_compare}")
    print("="*72)

    for kind in KINDS:
        idents = deduped.get(kind, [])
        if not idents:
            print(f"\n[{kind}] 식별자 없음 — 건너뜀")
            continue

        print(f"\n[{kind}] {len(idents)} identifiers — 자동 튜닝 시작")
        jw_used, clusters = autotune_by_target(
            idents,
            jw_start=args.jw_start,
            jw_min=args.jw_min,
            jw_step=args.jw_step,
            target_clusters=args.target_clusters,
            max_compare=args.max_compare
        )
        # 클러스터를 크기 내림차순 + 대표사전순으로 정렬해 주면 재현성 ↑
        clusters.sort(key=lambda c: (-len(c), c[0].lower()))
        # 과대(mega) 클러스터 분해 단계: 하나에 너무 많이 몰리는 현상 방지
        before_cnt = len(clusters)
        before_max = max(len(c) for c in clusters) if clusters else 0
        if before_max > args.max_cluster_size:
            clusters = split_oversized_clusters(
                clusters=clusters,
                max_cluster_size=args.max_cluster_size,
                jw_seed=jw_used,
                split_step=args.split_jw_step,
                split_max=args.split_jw_max,
                max_compare=args.max_compare,
            )
            after_cnt = len(clusters)
            after_max = max(len(c) for c in clusters) if clusters else 0
            print(f"    [split] clusters: {before_cnt} → {after_cnt}, max_size: {before_max} → {after_max}, jw_seed={jw_used:.3f}")
        else:
            print(f"    [split] skip (max_size={before_max} ≤ cap {args.max_cluster_size})")

        # 인덱스/세이프풀 생성
        index = build_index(clusters)
        safe_pool = idents  # 중복 제거 후 전체 사용

        # 저장
        save_outputs(kind, clusters, index, safe_pool, out_dir)
        print(f"    → saved: clusters={len(clusters)}, safe_pool={len(safe_pool)}, jw={jw_used:.3f}")

    print("\nDONE.")


if __name__ == "__main__":
    main()