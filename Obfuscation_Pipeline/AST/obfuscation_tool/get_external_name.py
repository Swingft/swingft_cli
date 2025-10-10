import os
import json

P_SAME_NAME = set()

def get_members(node):
    P_SAME_NAME.add(node.get("A_name"))

    params = node.get("I_parameters", [])
    for param in params:
        if param != "_":
            P_SAME_NAME.add(param)

    members = node.get("G_members", [])
    for member in members:
        params = member.get("I_parameters", [])
        for param in params:
            if param != "_":
                P_SAME_NAME.add(param)
        P_SAME_NAME.add(member.get("A_name"))
        
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
    
    return P_SAME_NAME
