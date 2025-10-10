import os
import json

ALL_IDENTIFIER = []
IDENTIFIER = {}
NOT_OBF = []

def get_library_name():
    name_path = "./AST/output/external_name.txt"
    if os.path.exists(name_path):
        with open(name_path, "r", encoding="utf-8") as f:
            for name in f:
                ALL_IDENTIFIER.append(name.strip())

def get_not_obfuscation(node):
    name = node.get("A_name")
    kind = node.get("B_kind")
    if node.get("isException") == 1:
        NOT_OBF.append((name, kind))
    
    if name not in ALL_IDENTIFIER:
        ALL_IDENTIFIER.append(name)
    
    members = node.get("G_members", [])
    for member in members:
        m_name = member.get("A_name")
        m_kind = member.get("B_kind")
        if member.get("isException") == 1:
            NOT_OBF.append((m_name, m_kind))
        
        if m_name not in ALL_IDENTIFIER:
            ALL_IDENTIFIER.append(m_name)

        if member.get("G_members"):
            get_not_obfuscation(member)

def get_identifiers_with_kind(node):
    def is_same(name, kind):
        if name.startswith("`") and name.endswith("`"):
            name = name[1:-1]
        if kind in ["variable", "case", "function"]:
            for k in ["variable", "case", "function"]: 
                if (name, k) in NOT_OBF:
                    return True
        return False
    
    name = node.get("A_name")
    kind = node.get("B_kind")
    if not is_same(name, kind) and (name, kind) not in NOT_OBF:
        if node.get("isException") == 0 and kind != "extension":
            if kind not in IDENTIFIER:
                IDENTIFIER[kind] = set()
            IDENTIFIER[kind].add(name)
    
    members = node.get("G_members", [])
    for member in members:
        m_name = member.get("A_name")
        m_kind = member.get("B_kind")
        if not is_same(m_name, m_kind) and (m_name, m_kind) not in NOT_OBF:
            if member.get("isException") == 0:
                if m_kind not in IDENTIFIER:
                    IDENTIFIER[m_kind] = set()
                IDENTIFIER[m_kind].add(m_name)
            if member.get("G_members"):
                get_identifiers_with_kind(member)

# 자식 노드가 자식 노드를 가지는 경우
def repeat_match_node(data, flag):
    if data is None: 
            return
    node = data.get("node", data)
    if not node:
        node = data
    extensions = data.get("extension", [])
    children = data.get("children", [])
    
    if flag == 1:
        get_not_obfuscation(node)
    else:
        get_identifiers_with_kind(node)

    for extension in extensions:
        repeat_match_node(extension, flag)
    for child in children:
        repeat_match_node(child, flag)

def collect_identifiers():
    file_path = "./AST/output/ast_node.json"
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        if isinstance(data, list):
            for item in data:
                repeat_match_node(item, 1)
            for item in data:
                repeat_match_node(item, 2)

        type_info_path = "type_info.json"
        with open(type_info_path, "w", encoding="utf-8") as f:
            json.dump(IDENTIFIER, f, indent=2, ensure_ascii=False, default=list)

        if "case" in IDENTIFIER:
            if "variable" not in IDENTIFIER:
                IDENTIFIER["variable"] = set()
            IDENTIFIER["variable"].update(IDENTIFIER["case"])
            del IDENTIFIER["case"]
        if "actor" in IDENTIFIER:
            if "class" not in IDENTIFIER:
                IDENTIFIER["class"] = set()
            IDENTIFIER["class"].update(IDENTIFIER["actor"])
            del IDENTIFIER["actor"]

        get_library_name()
        
        return IDENTIFIER, ALL_IDENTIFIER
