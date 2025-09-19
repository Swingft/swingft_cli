import json

def load_exception_names(path="exception_list.json"):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {item["A_name"] for item in data}

def load_identifiers(path="identifiers.txt"):
    identifiers = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("- "):
                identifiers.append(line[2:].strip())
    return identifiers

if __name__ == "__main__":
    exception_names = load_exception_names()
    identifiers = load_identifiers()

    diff = [ident for ident in identifiers if ident not in exception_names]

    with open("diff_identifiers.txt", "w", encoding="utf-8") as out:
        out.write("=== Identifiers not in exception list ===\n")
        for ident in diff:
            out.write(f"{ident}\n")
    print("결과가 diff_identifiers.txt 파일에 저장되었습니다.")

    print("=== Identifiers not in exception list ===")
    for ident in diff:
        print(ident)