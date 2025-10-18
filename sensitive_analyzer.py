#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
sensitive_analyzer.py

Sensitive 모드 전용 분석기 - 스레드 안전성 추가
"""

import os
import json
import re
import threading
from typing import List, Dict, Any, Optional
from pathlib import Path
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor

from ..core.base_analyzer import BaseAnalyzer
from ..core.model_loader import OptimizedModelLoader
from ..core.utils import (
    extract_sensitive_identifiers,
    save_identifiers_to_txt,
    clean_and_deduplicate_identifiers
)


class SensitiveAnalyzer(BaseAnalyzer):
    """보안 취약점 분석 전용 클래스 - 스레드 안전"""

    def __init__(self, base_model_path: str, lora_path: str = None,
                 model_loader: Optional[OptimizedModelLoader] = None,
                 n_ctx: int = 4096, n_gpu_layers: int = 0, n_threads: int = None,
                 enable_4bit_kv_cache: bool = True):
        super().__init__(base_model_path, lora_path, model_loader,
                         n_ctx, n_gpu_layers, n_threads, enable_4bit_kv_cache)

        # 스레드 안전성을 위한 락 추가
        self.model_lock = threading.Lock()

        current_dir = Path(__file__).parent.parent
        self.ast_analyzer_path = current_dir / "ast_analyzers" / "sensitive" / "SwiftASTAnalyzer"

        print(f"SensitiveAnalyzer 초기화 - AST 분석기: {self.ast_analyzer_path}")

    def create_model_input(self, swift_file_path: str, ast_json: str) -> tuple[str, str]:
        """보안 분석용 모델 입력 프롬프트 생성"""
        try:
            with open(swift_file_path, 'r', encoding='utf-8') as f:
                swift_code = f.read()
        except Exception:
            swift_code = "// Could not read source code"

        system_prompt = ""
        instruction = "In the following Swift code, find all identifiers related to sensitive logic. Provide the names and reasoning as a JSON object."

        try:
            symbol_info_pretty = json.dumps(json.loads(ast_json), indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            symbol_info_pretty = ast_json

        input_content = f"""**Swift Source Code:**
```swift
{swift_code}
```

**AST Symbol Information (JSON):**
```
{symbol_info_pretty}
```"""

        user_prompt = f"{instruction}\n\n{input_content}"

        return system_prompt, user_prompt

    def generate_analysis(self, swift_file_path: str) -> Dict[str, Any]:
        """
        단일 Swift 파일에 대한 분석 수행 (스레드 안전)
        """
        ast_json = self.run_swift_analyzer(swift_file_path)
        if not ast_json:
            return {
                "file_path": swift_file_path,
                "error": "AST analysis failed",
                "reasoning": "",
                "identifiers": []
            }

        system_prompt, user_prompt = self.create_model_input(swift_file_path, ast_json)

        try:
            # 스레드 안전하게 모델 사용
            with self.model_lock:
                model = self._load_model()

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]

                response = model.create_chat_completion(
                    messages=messages,
                    temperature=0.2,
                    top_p=0.95,
                    max_tokens=4096,
                )

                raw_output = response['choices'][0]['message']['content']

            reasoning, identifiers = self.extract_json_from_output(raw_output)

            return {
                "file_path": swift_file_path,
                "reasoning": reasoning,
                "identifiers": identifiers,
                "raw_output": raw_output,
                "ast_json": ast_json
            }

        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"Error in generate_analysis for {swift_file_path}: {str(e)}")

            return {
                "file_path": swift_file_path,
                "error": f"Model inference failed: {e}",
                "error_detail": error_detail,
                "reasoning": "",
                "identifiers": []
            }

    def extract_json_from_output(self, text: str) -> tuple[str, List[str]]:
        """모델 출력에서 JSON 추출 및 파싱"""
        if not text:
            return "", []

        try:
            start_index = text.find('{')
            end_index = text.rfind('}')
            if start_index != -1 and end_index != -1 and start_index < end_index:
                json_str = text[start_index:end_index + 1]
                data = json.loads(json_str)

                reasoning = data.get("reasoning", "")
                identifiers = data.get("identifiers", [])

                if isinstance(reasoning, str) and isinstance(identifiers, list):
                    return reasoning, [str(item) for item in identifiers]
        except (json.JSONDecodeError, AttributeError):
            pass

        reasoning_str = ""
        identifiers_list = []

        reasoning_match = re.search(r'["\']reasoning["\']\s*:\s*["\'](.*?)["\']', text, re.DOTALL)
        if reasoning_match:
            reasoning_str = reasoning_match.group(1).strip()

        identifiers_match = re.search(r'["\']identifiers["\']\s*:\s*\[(.*?)\]', text, re.DOTALL)
        if identifiers_match:
            content_str = identifiers_match.group(1).strip()
            if content_str:
                items = content_str.split(',')
                identifiers_list = [item.strip().strip('"\' ') for item in items if item.strip()]

        return reasoning_str, identifiers_list

    def analyze_project(self, project_path: str = None, config_path: str = None,
                        output_dir: str = "./output_sensitive", max_workers: int = 1,
                        save_individual_files: bool = False) -> Dict[str, Any]:
        """
        전체 프로젝트 보안 분석

        config의 exclude.obfuscation에 있는 식별자를 포함한 파일만 분석
        """
        print(f"\n=== SensitiveAnalyzer: 보안 취약점 분석 시작 ===")

        if max_workers > 1:
            print(f"Warning: max_workers={max_workers}는 지원되지 않습니다. 1로 설정합니다.")
            max_workers = 1

        project_input_path = self.resolve_project_path(project_path, config_path)

        # config 파일에서 exclude.obfuscation 읽기
        target_identifiers = []
        if config_path:
            config = self.load_swingft_config(config_path)
            target_identifiers = config.get('exclude', {}).get('obfuscation', [])

            if target_identifiers:
                print(f"Found {len(target_identifiers)} target identifiers from config:")
                for identifier in target_identifiers:
                    print(f"  - {identifier}")
            else:
                print("Warning: No identifiers found in exclude.obfuscation")
                print("Sensitive analysis requires target identifiers to run.")
                return {
                    "files_analyzed": 0,
                    "results": [],
                    "message": "No target identifiers specified in config"
                }
        else:
            print("Error: config_path is required for sensitive analysis")
            print("Please provide swingft_config.json path using --config option")
            return {
                "files_analyzed": 0,
                "results": [],
                "message": "Config file required but not provided"
            }

        # target_identifiers를 포함한 Swift 파일 찾기
        print(f"\nSearching for files containing target identifiers...")
        swift_files = self.find_swift_files_with_identifiers(project_input_path, target_identifiers)

        if not swift_files:
            print("No Swift files found containing the target identifiers")
            print("\nTarget identifiers were:")
            for identifier in target_identifiers:
                print(f"  - {identifier}")
            return {
                "files_analyzed": 0,
                "results": [],
                "message": "No files found with target identifiers"
            }

        print(f"Found {len(swift_files)} files containing target identifiers:")
        for swift_file in swift_files:
            print(f"  - {os.path.basename(swift_file)}")

        os.makedirs(output_dir, exist_ok=True)

        if save_individual_files:
            print(f"\nDebug mode: 개별 JSON 파일들도 {output_dir}에 저장됩니다.")

        self.preload_model()

        print(f"\nStarting security analysis (sequential processing)...")
        results = []

        for idx, swift_file in enumerate(swift_files, 1):
            print(f"\nProcessing [{idx}/{len(swift_files)}]: {os.path.basename(swift_file)}")

            try:
                result = self.generate_analysis(swift_file)
                results.append(result)

                if save_individual_files:
                    filename = os.path.basename(swift_file).replace('.swift', '_sensitive.json')
                    output_path = os.path.join(output_dir, filename)
                    with open(output_path, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)

                if 'error' in result:
                    print(f"  ✗ {result['error']}")
                else:
                    identifiers_found = len(result['identifiers'])
                    if identifiers_found > 0:
                        print(f"  ✓ {identifiers_found} sensitive identifiers found:")
                        for identifier in result['identifiers'][:5]:  # 처음 5개만 표시
                            print(f"    - {identifier}")
                        if identifiers_found > 5:
                            print(f"    ... and {identifiers_found - 5} more")
                    else:
                        print(f"  ✓ No sensitive identifiers found")

            except Exception as e:
                print(f"  ✗ Exception - {e}")
                results.append({
                    "file_path": swift_file,
                    "error": str(e),
                    "reasoning": "",
                    "identifiers": []
                })

        successful_results = [r for r in results if 'error' not in r]
        failed_results = [r for r in results if 'error' in r]

        all_sensitive_identifiers = []
        for result in successful_results:
            identifiers = extract_sensitive_identifiers(result)
            all_sensitive_identifiers.extend(identifiers)

        unique_sensitive_identifiers = clean_and_deduplicate_identifiers(all_sensitive_identifiers)

        sensitive_txt_path = os.path.join(output_dir, "sensitive_id.txt")
        save_identifiers_to_txt(unique_sensitive_identifiers, sensitive_txt_path)

        total_sensitive_identifiers = len(all_sensitive_identifiers)

        summary = {
            "mode": "sensitive",
            "target_identifiers_from_config": target_identifiers,
            "files_analyzed": len(swift_files),
            "successful": len(successful_results),
            "failed": len(failed_results),
            "total_sensitive_identifiers_found": total_sensitive_identifiers,
            "unique_sensitive_identifiers": unique_sensitive_identifiers,
        }

        if save_individual_files:
            summary["results"] = results

        summary_path = os.path.join(output_dir, "summary_sensitive.json")
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        print(f"\n=== Security Analysis Complete ===")
        print(f"Target identifiers: {len(target_identifiers)}")
        print(f"Files processed: {len(swift_files)}")
        print(f"Successful: {len(successful_results)}")
        print(f"Failed: {len(failed_results)}")
        print(f"Total sensitive identifiers found: {total_sensitive_identifiers}")
        print(f"Unique sensitive identifiers: {len(unique_sensitive_identifiers)}")
        print(f"\nResults saved to: {output_dir}")
        print(f"Identifiers saved to: {sensitive_txt_path}")

        if save_individual_files:
            print(f"개별 JSON 파일들도 저장되었습니다.")

        return summary