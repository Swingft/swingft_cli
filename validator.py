import os
import sys

def check_permissions(input_path, output_path):
    # Check input path existence and read permission
    if not os.path.exists(input_path):
        print(f"Error: Input path does not exist: {input_path}")
        sys.exit(1)
    if not os.access(input_path, os.R_OK):
        print(f"Error: No read permission for input path: {input_path}")
        sys.exit(1)
    # Check output path write permission
    if os.path.isdir(input_path):
        # If input is a directory, output should be a directory
        output_dir = output_path
        if os.path.exists(output_dir):
            if not os.access(output_dir, os.W_OK):
                print(f"Error: No write permission for output directory: {output_dir}")
                sys.exit(1)
        else:
            try:
                os.makedirs(output_dir, exist_ok=True)
            except Exception as e:
                print(f"Error: Could not create output directory: {output_dir}\n{e}")
                sys.exit(1)
    else:
        # If input is a file, check output file or its parent directory
        if os.path.exists(output_path):
            if not os.access(output_path, os.W_OK):
                print(f"Error: No write permission for output file: {output_path}")
                sys.exit(1)
        else:
            output_dir = os.path.dirname(output_path) or '.'
            if os.path.exists(output_dir):
                if not os.access(output_dir, os.W_OK):
                    print(f"Error: No write permission for output directory: {output_dir}")
                    sys.exit(1)
            else:
                try:
                    os.makedirs(output_dir, exist_ok=True)
                except Exception as e:
                    print(f"Error: Could not create output directory: {output_dir}\n{e}")
                    sys.exit(1)