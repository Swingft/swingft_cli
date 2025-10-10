import os
import json

M_SAME_NAME = set()
P_SAME_NAME = set()
PARAMS = []

# function, variable 정보 수집
def get_members(node):
    if node.get("B_kind") in ["struct", "class", "protocol", "enum"] and node.get("A_name") not in P_SAME_NAME:
        P_SAME_NAME.add(node.get("A_name"))
    else:
        if node.get("A_name") not in M_SAME_NAME:
            M_SAME_NAME.add(node.get("A_name"))
    
    if node.get("B_kind") == "function":
        params = node.get("I_parameters", [])
        for param in params:
            if param != "_":
                if param not in M_SAME_NAME:
                    M_SAME_NAME.add(param)
                if {"A_name": param, "B_kind": "variable"} not in PARAMS:
                    PARAMS.append({"A_name": param, "B_kind": "variable"})

    members = node.get("G_members", [])
    for member in members:
        if member.get("B_kind") == "function":
            params = member.get("I_parameters", [])
            for param in params:
                if param != "_":
                    if param not in M_SAME_NAME:
                        M_SAME_NAME.add(param)
                    if {"A_name": param, "B_kind": "variable"} not in PARAMS:
                        PARAMS.append({"A_name": param, "B_kind": "variable"})
        if member.get("B_kind") in ["function", "variable", "case"] and member.get("A_name") not in M_SAME_NAME:
            M_SAME_NAME.add(member.get("A_name"))
        
        if member.get("G_members"):
            get_members(member)
        
# 자식 노드가 자식 노드를 가지는 경우
def repeat_match_node(item):
    node = item.get("node")
    if not node:
        node = item
    extensions = item.get("extension", [])
    children = item.get("children", [])
    get_members(node)
    for extension in extensions:
        repeat_match_node(extension)
    for child in children:
        repeat_match_node(child)

def get_external_name():
    file_paths = ["./AST/output/external_to_ast"]
    for file_path in file_paths:
        for filename in os.listdir(file_path):
            path = os.path.join(file_path, filename)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            
                if isinstance(data, list):
                    for item in data:
                        repeat_match_node(item)
    
    ast_path = "./AST/output/no_inheritance_node.json"
    if os.path.exists(ast_path):
        with open(ast_path, "r", encoding="utf-8") as f:
            data = json.load(f)  
        
        for param in PARAMS:
            data[param["A_name"]] = param

        with open(ast_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    return M_SAME_NAME, P_SAME_NAME
