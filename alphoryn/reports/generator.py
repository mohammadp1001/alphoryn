"""HTML report generator for Alphoryn session reports.

Uses Jinja2 to render per-strategy HTML reports from a context object
matching contracts/report-context.md. Output path:
  {output_dir}/run-{run_id}/session-{seq}.html
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates" / "reports"
_TEMPLATE_MAP = {
    "MEAN_REVERSION": "mean_reversion.html.j2",
    "MOMENTUM": "momentum.html.j2",
}


class ReportGenerator:
    """Renders and writes session HTML reports."""

    def __init__(self, output_dir: str = "reports") -> None:
        self._output_dir = Path(output_dir)
        self._env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=False,  # noqa: S701 — reports are internal HTML, not user-facing web
        )

    def render(self, run_id: str, session_seq: str, context: dict) -> str:
        """Render and return the HTML string for a session report."""
        strategy = context.get("strategy", "MOMENTUM")
        template_name = _TEMPLATE_MAP.get(strategy, "momentum.html.j2")
        template = self._env.get_template(template_name)
        return template.render(**context)

    def write(self, run_id: str, session_seq: str, context: dict) -> str:
        """Render the report and write it to disk; return the absolute path."""
        html = self.render(run_id, session_seq, context)
        out_path = self._output_dir / run_id / f"{session_seq}.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html, encoding="utf-8")
        return str(out_path)
