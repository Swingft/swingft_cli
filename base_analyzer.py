#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
base_analyzer.py

모듈화된 베이스 분석기 클래스
"""

import json
import os
import subprocess
import threading
from typing import List, Dict, Optional, Tuple, Any
import re
import glob
from pathlib import Path

from .model_loader import OptimizedModelLoader, get_model_loader


class BaseAnalyzer:
    """공통 분석기 베이스 클래스 - 모듈화된 버전"""

    def __init__(self, base_model_path: str, lora_path: str = None,
                 model_loader: Optional[OptimizedModelLoader] = None,
                 n_ctx: int = 4096, n_gpu_layers: int = 0, n_threads: int = None,
                 enable_4bit_kv_cache: bool = True):
        """
        베이스 분석기 초기화

        Args:
            base_model_path: base_model.gguf 경로
            lora_path: LoRA 어댑터 경로 (선택사항)
            model_loader: 모델 로더 인스턴스 (선택사항)
            n_ctx: 컨텍스트 크기
            n_gpu_layers: GPU 레이어 수
            n_threads: CPU 스레드 수
            enable_4bit_kv_cache: 4비트 KV 캐시 활성화
        """
        self.base_model_path = base_model_path
        self.lora_path = lora_path
        self.model_config = {
            "n_ctx": n_ctx,
            "n_gpu_layers": n_gpu_layers,
            "n_threads": n_threads,
            "enable_4bit_kv_cache": enable_4bit_kv_cache
        }

        # 모델 로더 설정
        self.model_loader = model_loader or get_model_loader()

        # AST 분석기 경로 (하위 클래스에서 설정)
        self.ast_analyzer_path = None

        print(f"BaseAnalyzer 초기화 완료")
        print(f"  - Base model: {base_model_path}")
        print(f"  - LoRA adapter: {lora_path}")

    def _load_model(self):
        """모델 로딩 (모델 로더 사용)"""
        return self.model_loader.load_model(
            base_model_path=self.base_model_path,
            lora_path=self.lora_path,
            **self.model_config
        )

    def preload_model(self):
        """메인 스레드에서 모델을 미리 로드"""
        print("Pre-loading model into memory...")
        try:
            self._load_model()
            print("Model pre-loading complete.")
        except Exception as e:
            print(f"Model pre-loading failed: {e}")
            raise

    def load_swingft_config(self, config_path: str = None) -> Dict[str, Any]:
        """swingft_config.json 로드 (선택사항)"""
        if not config_path:
            print("Config file not provided, using minimal configuration")
            return {"project": {"input": None}}

        if not os.path.exists(config_path):
            print(f"Warning: Config file not found: {config_path}")
            return {"project": {"input": None}}

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            print(f"Config loaded from: {config_path}")
            return config
        except Exception as e:
            print(f"Warning: Failed to load config from {config_path}: {e}")
            return {"project": {"input": None}}

    def run_swift_analyzer(self, swift_file_path: str, analyzer_path: Optional[str] = None) -> Optional[str]:
        """
        SwiftASTAnalyzer를 실행하여 AST 정보 추출

        Args:
            swift_file_path: Swift 파일 경로
            analyzer_path: AST 분석기 실행 파일 경로 (선택사항)
        """
        if analyzer_path is None:
            analyzer_path = self.ast_analyzer_path

        if not analyzer_path or not os.path.exists(analyzer_path):
            print(f"Warning: AST analyzer not found at {analyzer_path}")
            return None

        try:
            command_str = f'"{analyzer_path}" "{swift_file_path}"'

            process = subprocess.run(
                command_str,
                shell=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=60
            )

            if process.returncode != 0:
                error_message = process.stderr.strip()
                print(f"Warning: AST analyzer failed for {swift_file_path}. Error: {error_message}")
                return None

            output = process.stdout.strip()
            if not output:
                return None

            first_bracket = output.find('[')
            first_brace = output.find('{')

            if first_bracket == -1 and first_brace == -1:
                return None

            if first_bracket != -1 and (first_bracket < first_brace or first_brace == -1):
                json_start = first_bracket
            else:
                json_start = first_brace

            json_part = output[json_start:]

            try:
                json.loads(json_part)
                return json_part
            except json.JSONDecodeError:
                return None

        except subprocess.TimeoutExpired:
            print(f"Warning: AST analysis timed out for {swift_file_path}")
            return None
        except Exception as e:
            print(f"Warning: AST analysis failed for {swift_file_path}: {e}")
            return None

    def extract_json_from_output(self, text: str) -> Tuple[str, List[str]]:
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

    def find_swift_files_with_identifiers(self, project_path: str, identifiers: List[str]) -> List[str]:
        """프로젝트에서 특정 식별자를 포함한 Swift 파일들을 찾음"""
        matching_files = []
        swift_files = glob.glob(os.path.join(project_path, "**/*.swift"), recursive=True)

        print(f"Scanning {len(swift_files)} Swift files for identifiers: {identifiers}")

        for swift_file in swift_files:
            try:
                with open(swift_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                for identifier in identifiers:
                    if identifier.endswith('*'):
                        prefix = identifier[:-1]
                        if prefix in content:
                            matching_files.append(swift_file)
                            break
                    elif identifier.startswith('**'):
                        matching_files.append(swift_file)
                        break
                    elif identifier in content:
                        matching_files.append(swift_file)
                        break

            except (UnicodeDecodeError, OSError) as e:
                print(f"Warning: Could not read {swift_file}: {e}")
                continue

        unique_files = list(set(matching_files))
        print(f"Found {len(unique_files)} files containing the specified identifiers")
        return unique_files

    def get_all_swift_files(self, project_path: str) -> List[str]:
        """프로젝트의 모든 Swift 파일들을 찾음"""
        swift_files = glob.glob(os.path.join(project_path, "**/*.swift"), recursive=True)
        print(f"Found {len(swift_files)} Swift files in project")
        return swift_files

    def resolve_project_path(self, project_path: str = None, config_path: str = None) -> str:
        """
        프로젝트 경로 결정 (CLI 인자 우선, 그 다음 config 파일)

        Args:
            project_path: CLI에서 제공된 프로젝트 경로 (우선순위 높음)
            config_path: config 파일 경로

        Returns:
            최종 프로젝트 경로

        Raises:
            ValueError: 프로젝트 경로를 결정할 수 없는 경우
        """
        if project_path:
            if not os.path.exists(project_path):
                raise ValueError(f"Project directory not found: {project_path}")
            if not os.path.isdir(project_path):
                raise ValueError(f"Project path is not a directory: {project_path}")
            print(f"Using project path from CLI: {project_path}")
            return project_path

        # config 파일에서 프로젝트 경로 읽기
        config = self.load_swingft_config(config_path)
        project_input_path = config.get('project', {}).get('input')

        if not project_input_path:
            raise ValueError("프로젝트 경로를 지정해주세요. --project 인자를 사용하거나 config 파일에 project.input을 설정하세요.")

        if not os.path.exists(project_input_path):
            raise ValueError(f"Project directory from config not found: {project_input_path}")

        print(f"Using project path from config: {project_input_path}")
        return project_input_path

    def generate_analysis(self, swift_file_path: str) -> Dict[str, Any]:
        """
        단일 Swift 파일에 대한 분석 수행 (하위 클래스에서 구현)

        Args:
            swift_file_path: Swift 파일 경로

        Returns:
            분석 결과 딕셔너리
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
            return {
                "file_path": swift_file_path,
                "error": f"Model inference failed: {e}",
                "reasoning": "",
                "identifiers": []
            }

    def create_model_input(self, swift_file_path: str, ast_json: str) -> tuple[str, str]:
        """
        모델 입력 프롬프트 생성 (하위 클래스에서 구현)

        Args:
            swift_file_path: Swift 파일 경로
            ast_json: AST JSON 데이터

        Returns:
            (system_prompt, user_prompt) 튜플
        """
        raise NotImplementedError("Subclasses must implement create_model_input")

    def analyze_project(self, project_path: str = None, config_path: str = None,
                        output_dir: str = "./output", max_workers: int = 4) -> Dict[str, Any]:
        """
        전체 프로젝트 분석 (하위 클래스에서 구현)

        Args:
            project_path: Swift 프로젝트 디렉토리 경로 (우선순위 높음)
            config_path: swingft_config.json 경로 (선택사항)
            output_dir: 출력 디렉토리
            max_workers: 병렬 처리 워커 수

        Returns:
            분석 결과 요약
        """
        raise NotImplementedError("Subclasses must implement analyze_project")