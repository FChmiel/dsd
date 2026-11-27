"""dsd: plans, docs and experiment tracking for agentic data science.

    import dsd
    with dsd.run("xgb-baseline", benchmark="churn-v1", task="T-12", params=cfg) as r:
        r.log({"loss": 0.3}, step=1)
        r.log({"auc": 0.81})
        r.html("report.html", html_string)
"""

__version__ = "0.1.1"

from .tracking import Run, active_run, dataset, finish, log  # noqa: E402
from .tracking import start_run as run  # noqa: E402

init_run = run

__all__ = ["run", "init_run", "log", "finish", "active_run", "dataset", "Run", "__version__"]
