"""Adapter to existing #377 plan-review implementation, not a second planner."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"workbench_plan_r0"))
from plan import review
def preview(intent,spec):
    def load(path):
        if path.is_symlink() or not path.is_file() or path.stat().st_size>2000000:raise ValueError("invalid preview input")
        value=json.loads(path.read_bytes(),parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        if not isinstance(value,dict):raise ValueError("expected JSON object")
        return value
    return review(load(intent),load(spec))
