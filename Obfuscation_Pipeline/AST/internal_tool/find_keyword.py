import os
import json

KEYWORD = set()

def get_keyworkd(node):
    kind = node.get("B_kind")
    access = node.get("C_accessLevel")
    attr = node.get("D_attributes", [])
    KEYWORD.add(kind)
    KEYWORD.add(access)
    KEYWORD.update(attr)

# 자식 노드가 자식 노드를 가지는 경우
def repeat_match_member(data):
    if data is None: 
        return
    node = data.get("node", data)
    extensions = data.get("extension", [])
    children = data.get("children", [])

    get_keyworkd(node)
    for extension in extensions:
        repeat_match_member(extension)
    for child in children:
        repeat_match_member(child)


# node 처리
def find_node(data):
    if isinstance(data, list):
        for item in data:
            repeat_match_member(item)

    elif isinstance(data, dict):
        for _, node in data.items():
            get_keyworkd(node)

def find_keyword():
    input_file_1 = "./AST/output/inheritance_node.json"
    input_file_2 = "./AST/output/no_inheritance_node.json"
    output_file = "./AST/output/keyword_list.txt"
    
    if os.path.exists(input_file_1):
        with open(input_file_1, "r", encoding="utf-8") as f:
            nodes = json.load(f)
        find_node(nodes)
    if os.path.exists(input_file_2):
        with open(input_file_2, "r", encoding="utf-8") as f:
            nodes = json.load(f)
        find_node(nodes)
    
    with open(output_file, "w", encoding="utf-8") as f:
        for candidate in KEYWORD:
            f.write(f"{candidate}\n")
