"""Refresh current Q3/Q4 and Q3 figures from audited Q1/Q2 artifacts.

Q1 and Q2 artifacts are intentionally kept as their independently audited inputs.
For just Q3/Q4, invoke run_q3_joint.py directly.
"""
from __future__ import annotations
from pathlib import Path
from common import ROOT


def main():
    required=(ROOT/"results"/"q1_reproduced"/"solution.json",
              ROOT/"results"/"q2_improved"/"schedule.json")
    missing=[str(p) for p in required if not p.is_file()]
    if missing:
        raise FileNotFoundError("Missing audited upstream artifact: "+", ".join(missing))
    from run_q3_joint import main as run_q3
    from q3_figures import main as make_figures
    run_q3()
    make_figures()


if __name__=="__main__":
    main()
