import os, subprocess

EXCLUDE_KEYWORDS = [".build", "pods", "vendor", "thirdparty", "external", "frameworks", "framework", "packages"]

def find_internal_files(directory):
    swift_files = set()
    storyboard_files = set()
    xc_files = set()
    for root, dirs, files in os.walk(directory):
        lower_root = root.lower()
        if any(keyword in lower_root for keyword in EXCLUDE_KEYWORDS):
            continue

        # swift, storyboard
        for file in files:
            if file.endswith(".swift") and file != "Package.swift":
                swift_files.add(os.path.join(root, file))
            if file.endswith(".storyboard"):
                storyboard_files.add(os.path.join(root, file))
        
        # xcassets
        for dir_name in dirs:
            if dir_name.endswith(".xcassets"):
                xcassets_path = os.path.join(root, dir_name)
                for xc_root, xc_dirs, _ in os.walk(xcassets_path):
                    for xc_dir in xc_dirs:
                        if "." in xc_dir:
                            xc_dir = xc_dir.split(".")[0]
                        xc_files.add(xc_dir)

    class_name = set()
    for file in storyboard_files:
        cmd = ["grep", "-Ro", 'customClass="[^"]*"', file]
        result = subprocess.run(cmd, capture_output=True, text=True)
        for line in result.stdout.splitlines():
            class_name.add(line.split('customClass="')[1].rstrip('"'))

    output_path = "./AST/output/xc_list.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        for xc in xc_files:
            f.write(f"{xc}\n")
            f.write(f"{xc.lower()}\n")

    output_path = "./AST/output/storyboard_list.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        for cls in sorted(class_name):
            f.write(f"{cls}\n")

    output_path ="./swift_file_list.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        for swift_file in swift_files:
            f.write(f"{swift_file}\n")