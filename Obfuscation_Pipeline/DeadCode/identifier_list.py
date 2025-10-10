import os
import json

large_identifiers = []
small_identifiers = []

def read_identifier_list():
    global large_identifiers, small_identifiers
    id_path = "./DeadCode/identifiers.txt"
    mapping_path = "mapping_result.json"
    used_id = []

    if os.path.exists(mapping_path):
        with open(mapping_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for _, items in data.items():
            for item in items:
                before = item.get("target")
                after = item.get("replacement")
                used_id.append(before)
                used_id.append(after)

    if os.path.exists(id_path):
        with open(id_path, "r", encoding="utf-8") as f:
            for line in f:
                item = line.strip()
                if len(item) < 5 or "_" in item or item in used_id:
                    continue
                if item[0].isupper():
                    large_identifiers.append(item)
                else:
                    small_identifiers.append(item)