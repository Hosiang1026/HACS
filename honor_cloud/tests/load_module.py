import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(filename: str):
    path = ROOT / filename
    name = f"honor_test_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module
