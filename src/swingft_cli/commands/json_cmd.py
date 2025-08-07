"""
json_cmd.py: Generate an example exclusion configuration JSON.
"""

import json
import sys

def handle_generate_json(json_path: str) -> None:
    """
    예시 제외목록 JSON 파일을 생성합니다.

    생성되는 JSON 구조 예시:
        "_comment_path": "Specify the absolute path to your project. The output path is optional.",
        "project": {
            "input": "",
            "output": ""
        },
        "options": { ... },
        "_comment_exclude": "The following section is optional and can be customized as needed.",
        "exclude": { ... },
        "_comment_include": "You can explicitly include items to always obfuscate/encrypt, regardless of global settings.",
        "include": { ... }
    """
    example = {
        "options": {
            "Obfuscation_classNames": True,
            "Obfuscation_methodNames": True,
            "Obfuscation_variableNames": True,
            "Obfuscation_controlFlow": True,
            "Delete_debug_symbols": True,
            "Encryption_strings": True
        },
        "_comment_exclude": "The following section is optional and can be customized as needed.",
        "exclude": {
            "obfuscation": [
                {"name": "AppDelegate", "type": "class", "includeMembers": True},
                {"name": "ViewController", "type": "class", "includeMembers": False},
                {"name": "MyImportantClass", "type": "class", "includeMembers": False},
                {"name": "logError", "type": "function", "includeMembers": False},
                {"name": "userName", "type": "variable"},
                {"name": "titleText", "type": "property"}
            ],
            "encryption": [
                "someStrings"
            ]
        },
        "_comment_include": "You can explicitly include items to always obfuscate/encrypt, regardless of global settings.",
        "include": {
            "obfuscation": [
                {"name": "ForceObfuscateClass", "type": "class", "includeMembers": True},
                {"name": "forceLog", "type": "function", "includeMembers": False},
                {"name": "userId", "type": "variable"},
                {"name": "titleName", "type": "property"}
            ]
        }
    }
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(example, f, indent=2, ensure_ascii=False)
        print(f"Example exclusion JSON file has been created: {json_path}")
    except Exception as e:
        print(f"Error writing JSON to {json_path}: {e}", file=sys.stderr)
        sys.exit(1)