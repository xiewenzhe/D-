"""One-command reproduction of the independently verified Q3 incumbent."""
from run_q3_joint import load, solve_from_q2_artifact
from q3_figures import main as figures


if __name__ == "__main__":
    solve_from_q2_artifact(load())
    figures()
