#!/usr/bin/env python3
"""
클러스터 재생성 스크립트
기존 클러스터를 더 큰 클러스터로 재그룹화하여 성능 향상

사용법:
  python3 regenerate_clusters.py --input-dir name_clusters --output-dir name_clusters_optimized --target-clusters 1000
"""

import argparse
import json
import random
from pathlib import Path
from typing import List, Dict, Any, Set
from collections import defaultdict
import sys

# 기존 유틸리티 임포트
from utils.identifier_utils import (
    normalize,
    jaro_winkler,
    tokens_no_stop,
    STOP_TOKENS
)


def calculate_cluster_distance(rep1: str, rep2: str, tokens1: List[str], tokens2: List[str]) -> float:
    """원래 클러스터 거리 계산 방식 사용"""
    tnorm = normalize(rep1)
    rnorm = normalize(rep2)
    
    # Jaro-Winkler 거리
    jw_rep = jaro_winkler(tnorm, rnorm) if rnorm else 0.0
    
    # 토큰 Jaccard 거리
    tset = {t.lower() for t in tokens1 if t and t.lower() not in STOP_TOKENS}
    cset = {t.lower() for t in tokens2 if t and t.lower() not in STOP_TOKENS}
    jac = (len(tset & cset) / max(1, len(tset | cset))) if (tset or cset) else 0.0
    
    # 길이 차이
    len_gap = min(abs(len(tnorm) - len(rnorm)), 8) / 8.0 if rnorm else 1.0
    
    # 접두어/접미어 중복
    prefix_hit = 1.0 if (rnorm[:3] and rnorm[:3] == tnorm[:3]) else 0.0
    suffix_hit = 1.0 if (rnorm[-2:] and rnorm[-2:] == tnorm[-2:]) else 0.0
    
    # 가중치 합산 (원래 방식과 동일)
    w1, w2, w3, w4, w5 = 0.50, 0.25, 0.15, 0.05, 0.05
    distance = w1*(1.0 - jw_rep) + w2*(1.0 - jac) + w3*(len_gap) + w4*(prefix_hit) + w5*(suffix_hit)
    
    return distance


def load_existing_clusters(cluster_dir: Path, kind: str) -> List[Dict[str, Any]]:
    """기존 클러스터 로드"""
    cluster_file = cluster_dir / f"cluster_index_{kind}.json"
    if not cluster_file.exists():
        return []
    
    with open(cluster_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def merge_clusters(clusters: List[Dict[str, Any]], target_count: int) -> List[Dict[str, Any]]:
    """클러스터들을 더 큰 클러스터로 병합"""
    if len(clusters) <= target_count:
        return clusters
    
    # 클러스터를 거리 기반으로 그룹화
    merged_clusters = []
    used_clusters = set()
    
    # 각 클러스터를 대표값으로 사용
    cluster_reps = [(cluster['rep'], cluster) for cluster in clusters if cluster['rep']]
    cluster_reps.sort(key=lambda x: len(x[1].get('members', [])), reverse=True)  # 크기 순 정렬
    
    for rep, cluster in cluster_reps:
        if id(cluster) in used_clusters:
            continue
        
        # 현재 클러스터를 기준으로 유사한 클러스터들 찾기
        merged_members = set(cluster.get('members', []))
        merged_tokens = set(cluster.get('tokens', []))
        merged_size = cluster['size']
        
        # 유사한 클러스터들 찾아서 병합
        for other_rep, other_cluster in cluster_reps:
            if id(other_cluster) in used_clusters:
                continue
            if id(other_cluster) == id(cluster):
                continue
            
            # 거리 계산 (원래 클러스터 거리 계산 방식 사용)
            distance = calculate_cluster_distance(rep, other_rep, cluster.get('tokens', []), other_cluster.get('tokens', []))
            
            # 임계치 이하면 병합 (더 엄격한 기준)
            if distance >= 0.4:  # 40% 이상 유사도
                merged_members.update(other_cluster.get('members', []))
                merged_tokens.update(other_cluster.get('tokens', []))
                merged_size += other_cluster['size']
                used_clusters.add(id(other_cluster))
        
        # 병합된 클러스터 생성
        if merged_members:
            merged_cluster = {
                'size': len(merged_members),
                'rep': rep,
                'tokens': list(merged_tokens),
                'members': list(merged_members)
            }
            merged_clusters.append(merged_cluster)
            used_clusters.add(id(cluster))
        
        # 목표 개수에 도달하면 중단
        if len(merged_clusters) >= target_count:
            break
    
    return merged_clusters


def optimize_cluster_sizes(clusters: List[Dict[str, Any]], min_size: int = 10) -> List[Dict[str, Any]]:
    """너무 작은 클러스터들을 병합하여 최적화"""
    # 크기별로 정렬
    clusters.sort(key=lambda x: x['size'], reverse=True)
    
    optimized = []
    small_clusters = []
    
    for cluster in clusters:
        if cluster['size'] >= min_size:
            optimized.append(cluster)
        else:
            small_clusters.append(cluster)
    
    # 작은 클러스터들을 큰 클러스터에 병합
    for small_cluster in small_clusters:
        if not optimized:
            optimized.append(small_cluster)
            continue
        
        # 가장 유사한 큰 클러스터 찾기
        best_match = None
        best_distance = 0.0  # 거리가 클수록 유사함
        
        for large_cluster in optimized:
            distance = calculate_cluster_distance(
                small_cluster['rep'], 
                large_cluster['rep'],
                small_cluster.get('tokens', []),
                large_cluster.get('tokens', [])
            )
            if distance > best_distance:
                best_distance = distance
                best_match = large_cluster
        
        # 병합 (거리가 클수록 유사함)
        if best_match and best_distance >= 0.3:
            best_match['members'].extend(small_cluster.get('members', []))
            best_match['tokens'].extend(small_cluster.get('tokens', []))
            best_match['size'] = len(best_match['members'])
            # 토큰 중복 제거
            best_match['tokens'] = list(set(best_match['tokens']))
        else:
            optimized.append(small_cluster)
    
    return optimized


def save_optimized_clusters(clusters: List[Dict[str, Any]], output_dir: Path, kind: str):
    """최적화된 클러스터 저장"""
    output_dir.mkdir(exist_ok=True)
    
    # 클러스터 인덱스 저장
    cluster_file = output_dir / f"cluster_index_{kind}.json"
    with open(cluster_file, 'w', encoding='utf-8') as f:
        json.dump(clusters, f, indent=2, ensure_ascii=False)
    
    # Safe pool 생성 (모든 멤버 수집)
    all_members = set()
    for cluster in clusters:
        all_members.update(cluster.get('members', []))
    
    safe_pool_file = output_dir / f"safe_pool_{kind}.txt"
    with open(safe_pool_file, 'w', encoding='utf-8') as f:
        for member in sorted(all_members):
            f.write(f"{member}\n")
    
    print(f"[{kind}] 클러스터 {len(clusters)}개, 멤버 {len(all_members)}개 저장")


def main():
    parser = argparse.ArgumentParser(description="클러스터 재생성 스크립트")
    parser.add_argument("--input-dir", default="name_clusters", help="입력 클러스터 디렉터리")
    parser.add_argument("--output-dir", default="name_clusters_optimized", help="출력 클러스터 디렉터리")
    parser.add_argument("--target-clusters", type=int, default=1000, help="목표 클러스터 개수")
    parser.add_argument("--min-size", type=int, default=10, help="최소 클러스터 크기")
    
    args = parser.parse_args()
    
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    
    if not input_dir.exists():
        print(f"입력 디렉터리를 찾을 수 없습니다: {input_dir}", file=sys.stderr)
        sys.exit(1)
    
    kinds = ['class', 'struct', 'enum', 'protocol', 'extension', 'typealias', 'function', 'variable']
    
    print(f"클러스터 재생성 시작 (목표: {args.target_clusters}개)")
    print("=" * 60)
    
    for kind in kinds:
        print(f"\n[{kind}] 처리 중...")
        
        # 기존 클러스터 로드
        clusters = load_existing_clusters(input_dir, kind)
        if not clusters:
            print(f"  {kind}: 클러스터 없음, 건너뜀")
            continue
        
        print(f"  원본: {len(clusters)}개 클러스터")
        
        # 클러스터 병합
        merged_clusters = merge_clusters(clusters, args.target_clusters)
        print(f"  병합 후: {len(merged_clusters)}개 클러스터")
        
        # 크기 최적화
        optimized_clusters = optimize_cluster_sizes(merged_clusters, args.min_size)
        print(f"  최적화 후: {len(optimized_clusters)}개 클러스터")
        
        # 평균 크기 계산
        avg_size = sum(cluster['size'] for cluster in optimized_clusters) / len(optimized_clusters)
        print(f"  평균 크기: {avg_size:.1f}개")
        
        # 저장
        save_optimized_clusters(optimized_clusters, output_dir, kind)
    
    print("\n" + "=" * 60)
    print("클러스터 재생성 완료!")
    print(f"결과 저장: {output_dir}")


if __name__ == "__main__":
    main()
