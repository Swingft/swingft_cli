import json

def write_config_json(json_path):
    """
    예시 제외목록 JSON 파일을 생성합니다.

        "_comment_path": "Specify the absolute path to your project. The output path is optional.",
        "project": {
            "input": "",
            "output": ""
        },


    """
    example = {
        "options": {
            "Obfuscation_classNames": True,
            "Obfuscation_methodNames": True,
            "Obfuscation_variableNames": True,
            "Obfuscation_controlFlow": True,
            "Encryption_strings": True
        },
        "_comment_exclude": "The following section is optional and can be customized as needed.",
        "exclude": {
            "obfuscation": [
                "AppDelegate",
                "ViewController",
                "MyImportantClass"
            ],
            "encryption": [
                "someStrings"
            ]
        }
    }
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(example, f, indent=2, ensure_ascii=False)
    print(f"Example exclusion JSON file has been created: {json_path}")