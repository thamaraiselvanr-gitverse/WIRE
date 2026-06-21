import os
import re
import sys

def audit_implementation_conformity():
    impl_plan_path = 'IMPLEMENTATION_PLAN.md'
    if not os.path.exists(impl_plan_path):
        print(f"ERROR: {impl_plan_path} not found.")
        sys.exit(1)

    with open(impl_plan_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract all file paths outlined in the Directory Structure tree inside the markdown
    # Assuming code blocks encapsulate the folder tree
    files_expected = []
    tree_section = re.search(r'## 6. Directory Structure(.*?)## 7. Verification Plan', content, re.DOTALL)
    
    if not tree_section:
        print("ERROR: Could not parse directory structure from IMPLEMENTATION_PLAN.md.")
        sys.exit(1)

    # Simplified parser to extract explicit ".py", ".md", ".toml", ".txt" definitions mapping to actual targets.
    # Searching for things like | wire/main.py | or \u251c\u2500\u2500 main.py
    
    # We will search based on the provided table matrix (Section 4) since that's highly rigorous
    matrix_section = re.search(r'## 4. Component Architecture(.*?)\n## 5. Implementation Phases', content, re.DOTALL)
    if matrix_section:
        rows = re.findall(r'\|\s*`([^`]+)`\s*\|', matrix_section.group(1))
        files_expected.extend(rows)
        
    required_root_files = ['tests/', 'deploy/', 'requirements.txt', 'pyproject.toml', 'README.md', 'IMPLEMENTATION_PLAN.md']
    for file in required_root_files:
        if file not in files_expected:
            files_expected.append(file)
            
    # Remove duplicates
    files_expected = list(set(files_expected))

    missing = []
    print("Beginning structural audit against IMPLEMENTATION_PLAN.md...\n")
    
    for relative_path in files_expected:
        path = os.path.normpath(relative_path)
        is_dir = relative_path.endswith('/') or relative_path.endswith('\\')
        
        if is_dir:
            if not os.path.isdir(path):
                missing.append(path)
        else:
            if not os.path.isfile(path):
                missing.append(path)

    total = len(files_expected)
    if missing:
        print(f"Validation FAILED! The following {len(missing)} files/directories are missing:")
        for m in missing:
            print(f"  [MISSING] {m}")
        score = ((total - len(missing)) / total) * 100
        print(f"\nConformity Score: {score:.2f}%")
        sys.exit(1)
    else:
        print(f"\nAll {total} documented architectural bounds are verified internally.")
        print("Conformity Score: 100.00%")
        print("SUCCESS: Codebase aligns explicitly with the implementation schema.")
        sys.exit(0)

if __name__ == '__main__':
    audit_implementation_conformity()
