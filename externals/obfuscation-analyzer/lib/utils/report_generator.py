import json
from typing import List, Dict, Any

from ..analyzer.graph_loader import SymbolGraph


class ReportGenerator:
    """분석 결과를 파일로 저장하고 요약 정보를 출력합니다."""

    def generate_json(self, results: List[Dict[str, Any]], output_path: str):
        """결과를 JSON 파일로 저장합니다."""
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            print(f"📄 Exclusion list saved to: {output_path}")
        except IOError as e:
            print(f"❌ Error: Failed to write report to {output_path}. {e}")

    def generate_txt(self, results: List[Dict[str, Any]], output_path: str):
        """[추가된 기능] 결과에서 식별자 이름만 추출하여 TXT 파일로 저장합니다."""
        if not output_path:
            return

        try:
            # 'name' 키만 추출하고 set을 사용해 중복을 자동으로 제거합니다.
            identifier_names = {item['name'] for item in results if 'name' in item}

            # 알파벳 순으로 정렬합니다.
            sorted_names = sorted(list(identifier_names))

            with open(output_path, 'w', encoding='utf-8') as f:
                for name in sorted_names:
                    f.write(name + '\n')
            print(f"📄 Exclusion name list saved to: {output_path} ({len(sorted_names)} unique names)")
        except IOError as e:
            print(f"❌ Error: Failed to write TXT report to {output_path}. {e}")

    def print_summary(self, results: List[Dict[str, Any]], graph: SymbolGraph):
        """콘솔에 분석 결과 요약을 출력합니다."""
        total_symbols = len(graph.graph.nodes)
        excluded_count = len(results)
        safe_count = total_symbols - excluded_count

        print("\n" + "=" * 50)
        print("📊 ANALYSIS SUMMARY")
        print("=" * 50)
        print(f"Total Symbols Analyzed: {total_symbols}")
        print(f"Excluded Symbols:       {excluded_count}")
        print(f"Obfuscation Candidates: {safe_count}")
        if total_symbols > 0:
            exclusion_rate = (excluded_count / total_symbols) * 100
            print(f"Exclusion Rate:         {exclusion_rate:.2f}%")
        print("=" * 50)

        reason_counts = {}
        for item in results:
            for reason in item['reasons']:
                rule_id = reason['rule_id']
                reason_counts[rule_id] = reason_counts.get(rule_id, 0) + 1

        if reason_counts:
            print("TOP 5 EXCLUSION REASONS:")
            sorted_reasons = sorted(reason_counts.items(), key=lambda item: item[1], reverse=True)
            for rule_id, count in sorted_reasons[:5]:
                print(f"  - {rule_id:<30} : {count} symbols")
            print("=" * 50)