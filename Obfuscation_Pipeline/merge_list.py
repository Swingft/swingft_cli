import os
import json

LLM_ID = []

def check_llm_find_id(node):
    name = node.get("A_name")
    if name in LLM_ID:
        node["isException"] = 1
    
    members = node.get("G_members", [])
    for member in members:
        m_name = member.get("A_name")
        if m_name in LLM_ID:
            member["isException"] = 1
        if member.get("G_members"):
            check_llm_find_id(member)

# 자식 노드가 자식 노드를 가지는 경우
def repeat_match_node(data):
    if data is None: 
            return
    node = data.get("node", data)
    if not node:
        node = data
    extensions = data.get("extension", [])
    children = data.get("children", [])
    
    check_llm_find_id(node)

    for extension in extensions:
        repeat_match_node(extension)
    for child in children:
        repeat_match_node(child)

def merge_llm_and_rule():
    llm_output = "../llm_output.txt"
    if os.path.exists(llm_output):
        with open(llm_output, "r", encoding="utf-8") as f:
            for line in f:
                LLM_ID.append(line.strip())

        file_path = "../AST-Code/output/ast_node.json"
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            if isinstance(data, list):
                for item in data:
                    repeat_match_node(item)
            
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)