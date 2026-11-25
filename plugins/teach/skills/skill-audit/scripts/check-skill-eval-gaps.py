#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from core_src import add_core_src, find_core_src  # noqa: E402

add_core_src(script=Path(__file__))

from dev10x.teach.skills.audit.eval_gaps_cli import main  # noqa: E402

if __name__ == "__main__":
    core_src = find_core_src(script=Path(__file__))
    repo_root = core_src.parent if core_src is not None else Path.cwd()
    sys.exit(main(argv=sys.argv[1:], repo_root=repo_root))
