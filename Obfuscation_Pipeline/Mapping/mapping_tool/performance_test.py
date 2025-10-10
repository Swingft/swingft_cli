#!/usr/bin/env python3
"""
성능 비교 테스트 스크립트
Legacy 방식 vs 최적화된 방식의 성능 비교

사용법:
  python3 performance_test.py --targets targets.json --exclude project_identifiers.json
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple


def run_mapping_script(script_path: str, targets: str, output: str, exclude: str = None, 
                      cluster_threshold: float = None) -> Tuple[float, bool]:
    """매핑 스크립트 실행 및 시간 측정"""
    cmd = [
        "python3", script_path,
        "--targets", targets,
        "--output", output,
        "--seed", "42"  # 동일한 시드로 일관성 보장
    ]
    
    if exclude:
        cmd.extend(["--exclude", exclude])
    
    if cluster_threshold is not None:
        cmd.extend(["--cluster-threshold", str(cluster_threshold)])
    
    start_time = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)  # 5분 타임아웃
        end_time = time.time()
        
        if result.returncode == 0:
            return end_time - start_time, True
        else:
            print(f"스크립트 실행 실패: {result.stderr}", file=sys.stderr)
            return end_time - start_time, False
    except subprocess.TimeoutExpired:
        print(f"스크립트 실행 타임아웃 (5분 초과)", file=sys.stderr)
        return 300.0, False


def compare_results(legacy_output: str, optimized_output: str) -> Dict[str, any]:
    """결과 비교 분석"""
    try:
        with open(legacy_output, 'r', encoding='utf-8') as f:
            legacy_result = json.load(f)
        
        with open(optimized_output, 'r', encoding='utf-8') as f:
            optimized_result = json.load(f)
        
        comparison = {
            "legacy_total_mappings": 0,
            "optimized_total_mappings": 0,
            "legacy_kinds": {},
            "optimized_kinds": {},
            "mapping_differences": []
        }
        
        # 전체 매핑 수 계산
        for kind, mappings in legacy_result.items():
            if isinstance(mappings, list):
                comparison["legacy_total_mappings"] += len(mappings)
                comparison["legacy_kinds"][kind] = len(mappings)
        
        for kind, mappings in optimized_result.items():
            if isinstance(mappings, list):
                comparison["optimized_total_mappings"] += len(mappings)
                comparison["optimized_kinds"][kind] = len(mappings)
        
        # 매핑 차이 분석
        for kind in set(legacy_result.keys()) | set(optimized_result.keys()):
            legacy_mappings = legacy_result.get(kind, [])
            optimized_mappings = optimized_result.get(kind, [])
            
            if len(legacy_mappings) != len(optimized_mappings):
                comparison["mapping_differences"].append({
                    "kind": kind,
                    "legacy_count": len(legacy_mappings),
                    "optimized_count": len(optimized_mappings)
                })
        
        return comparison
        
    except Exception as e:
        print(f"결과 비교 실패: {e}", file=sys.stderr)
        return {}


def main():
    parser = argparse.ArgumentParser(description="성능 비교 테스트")
    parser.add_argument("--targets", required=True, help="타겟 리스트 JSON 파일")
    parser.add_argument("--exclude", help="제외(화이트리스트) JSON 파일")
    parser.add_argument("--thresholds", nargs="+", type=float, default=[0.1, 0.3, 0.5], 
                       help="테스트할 클러스터 임계치들 (기본: 0.1 0.3 0.5)")
    parser.add_argument("--iterations", type=int, default=3, help="각 테스트 반복 횟수 (기본: 3)")
    
    args = parser.parse_args()
    
    # 입력 검증
    targets_path = Path(args.targets)
    if not targets_path.exists():
        print(f"타겟 파일을 찾을 수 없습니다: {targets_path}", file=sys.stderr)
        sys.exit(1)
    
    if args.exclude:
        exclude_path = Path(args.exclude)
        if not exclude_path.exists():
            print(f"제외 파일을 찾을 수 없습니다: {exclude_path}", file=sys.stderr)
            sys.exit(1)
    
    print("=" * 80)
    print("🚀 성능 비교 테스트 시작")
    print("=" * 80)
    
    # 테스트 결과 저장
    results = {
        "legacy": [],
        "optimized": {}
    }
    
    # 1. Legacy 방식 테스트
    print("\n📊 Legacy 방식 테스트 중...")
    legacy_times = []
    for i in range(args.iterations):
        output_file = f"mapping_result_legacy_{i}.json"
        elapsed_time, success = run_mapping_script(
            "service_mapping_legacy.py", 
            args.targets, 
            output_file, 
            args.exclude
        )
        legacy_times.append(elapsed_time)
        if success:
            print(f"  반복 {i+1}: {elapsed_time:.3f}초 ✅")
        else:
            print(f"  반복 {i+1}: {elapsed_time:.3f}초 ❌")
    
    results["legacy"] = legacy_times
    
    # 2. 최적화된 방식 테스트 (다양한 임계치)
    for threshold in args.thresholds:
        print(f"\n⚡ 최적화된 방식 테스트 (임계치: {threshold})...")
        optimized_times = []
        for i in range(args.iterations):
            output_file = f"mapping_result_optimized_{threshold}_{i}.json"
            elapsed_time, success = run_mapping_script(
                "service_mapping.py", 
                args.targets, 
                output_file, 
                args.exclude,
                threshold
            )
            optimized_times.append(elapsed_time)
            if success:
                print(f"  반복 {i+1}: {elapsed_time:.3f}초 ✅")
            else:
                print(f"  반복 {i+1}: {elapsed_time:.3f}초 ❌")
        
        results["optimized"][threshold] = optimized_times
    
    # 3. 결과 분석 및 출력
    print("\n" + "=" * 80)
    print("📈 성능 비교 결과")
    print("=" * 80)
    
    # Legacy 방식 통계
    legacy_avg = sum(results["legacy"]) / len(results["legacy"])
    legacy_min = min(results["legacy"])
    legacy_max = max(results["legacy"])
    
    print(f"\n🔴 Legacy 방식:")
    print(f"  평균 시간: {legacy_avg:.3f}초")
    print(f"  최소 시간: {legacy_min:.3f}초")
    print(f"  최대 시간: {legacy_max:.3f}초")
    
    # 최적화된 방식 통계
    print(f"\n🟢 최적화된 방식:")
    for threshold, times in results["optimized"].items():
        avg_time = sum(times) / len(times)
        min_time = min(times)
        max_time = max(times)
        improvement = ((legacy_avg - avg_time) / legacy_avg) * 100
        
        print(f"  임계치 {threshold}:")
        print(f"    평균 시간: {avg_time:.3f}초 (개선: {improvement:+.1f}%)")
        print(f"    최소 시간: {min_time:.3f}초")
        print(f"    최대 시간: {max_time:.3f}초")
    
    # 최고 성능 임계치 찾기
    best_threshold = None
    best_avg_time = float('inf')
    for threshold, times in results["optimized"].items():
        avg_time = sum(times) / len(times)
        if avg_time < best_avg_time:
            best_avg_time = avg_time
            best_threshold = threshold
    
    if best_threshold:
        best_improvement = ((legacy_avg - best_avg_time) / legacy_avg) * 100
        print(f"\n🏆 최고 성능: 임계치 {best_threshold} ({best_avg_time:.3f}초, {best_improvement:+.1f}% 개선)")
    
    # 결과 비교 (첫 번째 반복 결과)
    if args.iterations > 0:
        print(f"\n🔍 결과 품질 비교:")
        legacy_output = "mapping_result_legacy_0.json"
        optimized_output = f"mapping_result_optimized_{best_threshold}_0.json"
        
        if Path(legacy_output).exists() and Path(optimized_output).exists():
            comparison = compare_results(legacy_output, optimized_output)
            if comparison:
                print(f"  Legacy 매핑 수: {comparison['legacy_total_mappings']}")
                print(f"  최적화 매핑 수: {comparison['optimized_total_mappings']}")
                
                if comparison["mapping_differences"]:
                    print("  매핑 수 차이:")
                    for diff in comparison["mapping_differences"]:
                        print(f"    {diff['kind']}: Legacy {diff['legacy_count']} vs 최적화 {diff['optimized_count']}")
                else:
                    print("  매핑 수 동일 ✅")
    
    print("\n" + "=" * 80)
    print("✅ 성능 테스트 완료")
    print("=" * 80)


if __name__ == "__main__":
    main()
