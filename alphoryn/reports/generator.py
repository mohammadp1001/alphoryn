"""HTML report generator for Alphoryn session reports.

Uses Jinja2 to render per-strategy HTML reports from a context object
matching contracts/report-context.md. Output path:
  {output_dir}/run-{N}/session-{seq}.html
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates" / "reports"
class ReportGenerator:
    """Renders and writes session HTML reports."""

    def __init__(self, output_dir: str = "reports") -> None:
        self._output_dir = Path(output_dir)
        self._env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=False,  # noqa: S701 — reports are internal HTML, not user-facing web
        )

    def render(self, session_id: str, context: dict) -> str:
        """Render and return the HTML string for a session report."""
        template = self._env.get_template("session.html.j2")
        return template.render(**context)

    def write(self, session_id: str, context: dict) -> str:
        """Render the report and write it to disk; return the path.

        *session_id* is the composite ``run-{N}/session-{seq}`` identifier, which
        already carries the run directory — so it maps straight onto the output
        path. Taking the run separately used to double-nest it (issue #133).
        """
        html = self.render(session_id, context)
        out_path = self._output_dir / f"{session_id}.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html, encoding="utf-8")
        return str(out_path)
