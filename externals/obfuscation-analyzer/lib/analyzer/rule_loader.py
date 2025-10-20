import yaml
import sys
from typing import List, Dict, Any


class RuleLoader:
    """YAML 규칙 파일을 로드하고 유효성을 검사합니다."""

    def __init__(self, yaml_path: str):
        self.rules = self._load_from_yaml(yaml_path)

    def _load_from_yaml(self, yaml_path: str) -> List[Dict[str, Any]]:
        """YAML 파일에서 규칙을 로드합니다."""
        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            if not isinstance(data, dict) or 'rules' not in data:
                print(f"❌ Error: YAML 파일은 'rules' 키를 포함해야 합니다: {yaml_path}", file=sys.stderr)
                return []

            rules_list = data.get('rules', [])
            if not isinstance(rules_list, list):
                print(f"❌ Error: 'rules' 키의 값은 리스트여야 합니다: {yaml_path}", file=sys.stderr)
                return []

            return rules_list

        except FileNotFoundError:
            print(f"❌ Error: 규칙 파일을 찾을 수 없습니다: {yaml_path}", file=sys.stderr)
            sys.exit(1)
        except yaml.YAMLError as e:
            print(f"❌ Error: YAML 파싱에 실패했습니다: {yaml_path}\n{e}", file=sys.stderr)
            sys.exit(1)