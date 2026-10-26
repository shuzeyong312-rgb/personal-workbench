"""Check relocated experiments without starting browsers or reading the work DB."""

import subprocess
import sys
from pathlib import Path


def test_poc_imports_and_paths_from_another_directory(tmp_path):
    root = Path(__file__).resolve().parents[2]
    check = r"""
import ast
import importlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
poc = root / 'experiments' / 'poc'
sys.path.insert(0, str(poc))
scripts = sorted(poc.glob('poc_*.py'))
assert len(scripts) == 7
for script in scripts:
    source = script.read_text(encoding='utf-8')
    compile(source, str(script), 'exec')
    module = importlib.import_module(script.stem)
    if hasattr(module, 'ROOT'):
        assert module.ROOT == root
        assert module.DB_PATH == root / 'backend/data/personal_workbench.db'
        profile = getattr(module, 'PROFILE_PATH', getattr(module, 'PROFILE_DIR', None))
        if profile is not None:
            assert profile == root / '.browser-profile'
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'profile_dir' for t in node.targets):
            expression = ast.Expression(node.value)
            assert eval(compile(expression, str(script), 'eval'), vars(module)) == root / '.browser-profile'
"""
    subprocess.run([sys.executable, '-B', '-c', check, str(root)], cwd=tmp_path, check=True)
