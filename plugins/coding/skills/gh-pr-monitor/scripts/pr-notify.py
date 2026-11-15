#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6.0,<7"]
# ///
"""Thin shim — delegates to dev10x.skills.monitor.pr_notify.

The shim is the composition root (GH-1550): it hands comm's Slack
sender to coding's pr_notify, so the coding module never imports comm.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from dev10x.skills.monitor.pr_notify import *  # noqa: F401, F403
from dev10x.skills.monitor.pr_notify import main

from dev10x.comm.skills.notifications.slack_notify import notify_slack

if __name__ == "__main__":
    main(send_slack=notify_slack)
