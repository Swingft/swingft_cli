#!/usr/bin/env python3
"""
원본 클러스터링 방식 기반 클러스터 재생성
git_crwaling/cluster_identifiers.py의 방식을 최대한 유사하게 사용

사용법:
  python3 regenerate_clusters_original.py --input-dir name_clusters --output-dir name_clusters_optimized --target-clusters 1000
"""

import argparse
import json
import random
from pathlib import Path
from typing import List, Dict, Any, Set
from collections import defaultdict
import sys

# 원본 클러스터링 방식 임포트
sys.path.append('/Users/lanian/Desktop/S_DEV/git_crwaling')
from cluster_identifiers import (
    split_ident, norm_tokens, norm_join, prefix4, jaro_winkler,
    UnionFind, blocks_for, pairwise_limited, cluster_names,
    safe_pool, cluster_rep_and_tokens
)


def autotune_threshold(identifiers: List[str],
                       start_jw: float,
                       target_clusters: int,
                       max_compare: int,
                       min_jw: float = 0.78,
                       step: float = 0.01) -> tuple[float, List[List[str]]]:
    """
    점진적으로 Jaro-Winkler 임계치를 낮추며 클러스터 개수가 target_clusters 이하가 되도록 시도.
    - 반환: (최종 임계치, 클러스터 목록)
    - 실패 시: min_jw까지 내려도 조건 미충족이면 (최종 시도 임계치, 마지막 클러스터) 반환
    """
    jw = start_jw
    best_clusters = None
    best_jw = jw
    while True:
        clusters = cluster_names(identifiers, jw_threshold=jw, max_compare=max_compare)
        # 저장해두기
        best_clusters = clusters
        best_jw = jw
        print(f"    [auto] jw={jw:.3f} → {len(clusters)} clusters")
        if len(clusters) <= target_clusters:
            return jw, clusters
        # 더 낮춰서 병합 정도를 올려본다
        next_jw = jw - step
        if next_jw < min_jw:
            print(f"    [auto] min_jw={min_jw:.3f} 도달. 자동 튜닝 종료(조건 미충족).")
            return best_jw, best_clusters
        jw = next_jw


def load_existing_identifiers(cluster_dir: Path, kind: str) -> List[str]:
    """기존 safe_pool에서 식별자 로드"""
    safe_pool_file = cluster_dir / f"safe_pool_{kind}.txt"
    if not safe_pool_file.exists():
        return []
    
    with open(safe_pool_file, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]


def regenerate_clusters_for_kind(identifiers: List[str], kind: str, target_clusters: int, 
                                jw_threshold: float = 0.85, max_compare: int = 50000,
                                auto_tune: bool = False, min_jw: float = 0.78, step: float = 0.01) -> Dict[str, Any]:
    """원본 방식으로 클러스터 재생성"""
    if not identifiers:
        return {"clusters": [], "index": [], "safe_pool": []}
    
    print(f"  [{kind}] {len(identifiers)}개 식별자로 클러스터링...")
    
    # 1. 클러스터링
    if auto_tune:
        jw_threshold, clusters_all = autotune_threshold(
            identifiers, start_jw=jw_threshold, target_clusters=target_clusters,
            max_compare=max_compare, min_jw=min_jw, step=step
        )
        print(f"    [auto] 선택된 jw-threshold={jw_threshold:.3f}")
    else:
        clusters_all = cluster_names(identifiers, jw_threshold=jw_threshold, max_compare=max_compare)
    
    # 2. 클러스터 크기별 정렬 (큰 클러스터 우선)
    clusters_all.sort(key=lambda c: (-len(c), c[0].lower()))
    
    # 3. 목표 클러스터 수에 맞게 조정
    if auto_tune:
        selected_clusters = clusters_all
        print(f"    [auto] 자연스러운 클러스터 수 유지: {len(selected_clusters)}개")
    else:
        if len(clusters_all) > target_clusters:
            # 큰 클러스터들만 선택
            selected_clusters = clusters_all[:target_clusters]
            print(f"    {len(clusters_all)}개 → {len(selected_clusters)}개 클러스터 선택")
        else:
            selected_clusters = clusters_all
            print(f"    {len(selected_clusters)}개 클러스터 유지")
    
    # 4. 클러스터 내 요소 개수는 제한하지 않음 (랜덤 선택용)
    
    # 5. 클러스터 인덱스 생성
    index = []
    for cluster in selected_clusters:
        rep, tokens = cluster_rep_and_tokens(cluster)
        index.append({
            "size": len(cluster),
            "rep": rep,
            "tokens": tokens,
            "members": cluster,
        })
    
    # 5. Safe pool 생성 (모든 식별자 사용)
    safe_pool_names = identifiers  # 모든 식별자 사용
    
    return {
        "clusters": selected_clusters,
        "index": index,
        "safe_pool": safe_pool_names
    }


def save_optimized_clusters(result: Dict[str, Any], output_dir: Path, kind: str):
    """최적화된 클러스터 저장"""
    output_dir.mkdir(exist_ok=True)
    
    # 클러스터 저장
    clusters_file = output_dir / f"clusters_{kind}.json"
    with open(clusters_file, 'w', encoding='utf-8') as f:
        json.dump(result["clusters"], f, indent=2, ensure_ascii=False)
    
    # 클러스터 인덱스 저장
    index_file = output_dir / f"cluster_index_{kind}.json"
    with open(index_file, 'w', encoding='utf-8') as f:
        json.dump(result["index"], f, indent=2, ensure_ascii=False)
    
    # Safe pool 저장
    safe_pool_file = output_dir / f"safe_pool_{kind}.txt"
    with open(safe_pool_file, 'w', encoding='utf-8') as f:
        for name in result["safe_pool"]:
            f.write(f"{name}\n")
    
    print(f"    저장 완료: {len(result['clusters'])}개 클러스터, {len(result['safe_pool'])}개 safe pool")


def main():
    parser = argparse.ArgumentParser(description="원본 방식 기반 클러스터 재생성")
    parser.add_argument("--input-dir", default="name_clusters", help="입력 클러스터 디렉터리")
    parser.add_argument("--output-dir", default="name_clusters_optimized", help="출력 클러스터 디렉터리")
    parser.add_argument("--target-clusters", type=int, default=1000, help="목표 클러스터 개수")
    parser.add_argument("--jw-threshold", type=float, default=0.85, help="Jaro-Winkler 임계치 (낮을수록 더 많은 클러스터)")
    parser.add_argument("--max-compare", type=int, default=50000, help="최대 비교 쌍 수")
    parser.add_argument("--auto-tune", action="store_true", help="클러스터 수가 목표 이하시가 될 때까지 jw 임계치를 자동으로 낮춤")
    parser.add_argument("--min-jw", type=float, default=0.78, help="자동 튜닝 시 하한 Jaro-Winkler 임계치")
    parser.add_argument("--step", type=float, default=0.01, help="자동 튜닝 시 임계치 감소 간격")
    
    args = parser.parse_args()
    
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    
    if not input_dir.exists():
        print(f"입력 디렉터리를 찾을 수 없습니다: {input_dir}", file=sys.stderr)
        sys.exit(1)
    
    kinds = ['class', 'struct', 'enum', 'protocol', 'extension', 'typealias', 'function', 'variable']
    
    print(f"원본 방식 기반 클러스터 재생성 시작")
    print(f"목표: {args.target_clusters}개 클러스터")
    print(f"Jaro-Winkler 임계치: {args.jw_threshold}")
    if args.auto_tune:
        print(f"자동 튜닝: ON (min_jw={args.min_jw}, step={args.step})")
    print("=" * 60)
    
    for kind in kinds:
        print(f"\n[{kind}] 처리 중...")
        
        # 기존 식별자 로드
        identifiers = load_existing_identifiers(input_dir, kind)
        if not identifiers:
            print(f"  {kind}: 식별자 없음, 건너뜀")
            continue
        
        # 클러스터 재생성
        result = regenerate_clusters_for_kind(
            identifiers, kind, args.target_clusters,
            args.jw_threshold, args.max_compare,
            auto_tune=args.auto_tune, min_jw=args.min_jw, step=args.step
        )
        
        # 저장
        save_optimized_clusters(result, output_dir, kind)
    
    print("\n" + "=" * 60)
    print("클러스터 재생성 완료!")
    print(f"결과 저장: {output_dir}")


if __name__ == "__main__":
    main()
