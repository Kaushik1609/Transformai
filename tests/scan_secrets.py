import os
import re
import sys

FORBIDDEN_PATTERNS = [
    r'sk-[A-Za-z0-9]{20,}',
    r'AIza[0-9A-Za-z\-_]{35}',
    r'AKIA[0-9A-Z]{16}',
    r'ghp_[A-Za-z0-9]{36}',
    r'xoxb-[0-9]{11}-[0-9]{11}',
]

SKIP_DIRS = {'.venv', 'node_modules', '.next', '__pycache__', '.git', '.pytest_cache'}
SKIP_EXTS = {'.pyc', '.pyo', '.exe', '.dll', '.so', '.png', '.jpg', '.ico'}
SCAN_ROOT = os.path.join(os.path.dirname(__file__), '..')

issues = []
scanned = 0

for root, dirs, files in os.walk(SCAN_ROOT):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    for fname in files:
        ext = os.path.splitext(fname)[1]
        if ext in SKIP_EXTS:
            continue
        fpath = os.path.join(root, fname)
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                scanned += 1
                for pat in FORBIDDEN_PATTERNS:
                    if re.search(pat, content):
                        issues.append(f'{fpath}: matched pattern {pat}')
        except Exception:
            pass

print(f'Files scanned: {scanned}')
if issues:
    print('SECURITY ISSUES FOUND:')
    for i in issues:
        print(' ', i)
    sys.exit(1)
else:
    print('SECRET SCAN: PASSED — no hardcoded secrets detected')
