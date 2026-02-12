"""Interactive TUI-based configuration setup using Textual."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    RadioButton,
    RadioSet,
    Select,
    Static,
)

if TYPE_CHECKING:
    from pathlib import Path

    from textual.binding import Binding


# ASCII Art Logo for Nit
NIT_LOGO = "[bold cyan]███╗   ██╗██╗████████╗[/bold cyan] [dim]AI-powered testing & quality[/dim]"


class StepContainer(Container):
    """Base container for wizard steps."""

    def __init__(
        self,
        step_number: int,
        total_steps: int,
        title: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.step_number = step_number
        self.total_steps = total_steps
        self.step_title = title

    def compose(self) -> ComposeResult:
        """Yield inline navigation header, then step-specific fields."""
        with Horizontal(id="step-nav-row"):
            yield Button("← Back", variant="default", id="prev-btn")
            yield Static(
                f"[bold cyan]Step {self.step_number}/{self.total_steps}:"
                f"[/bold cyan] {self.step_title}",
                classes="step-header",
                id="step-header-text",
            )
            yield Button(
                "Next →",
                variant="primary",
                id="next-btn",
                classes="primary-button",
            )
        yield from self.compose_fields()

    def compose_fields(self) -> ComposeResult:
        """Override in subclasses to yield step-specific fields."""
        yield from ()


class Step1Platform(StepContainer):
    """Step 1: Platform Integration."""

    def compose_fields(self) -> ComposeResult:
        """Create child widgets."""
        yield Static(
            "[dim]Choose how nit connects to LLM providers[/dim]",
            classes="step-description",
        )

        yield Label("Platform Mode:", classes="field-label")
        with RadioSet(id="platform_mode"):
            yield RadioButton(
                "Platform Mode - Managed keys via proxy",
                id="mode_platform",
            )
            yield RadioButton(
                "BYOK - Bring Your Own Key + platform reporting",
                id="mode_byok",
            )
            yield RadioButton(
                "Disabled - Fully local (no platform)",
                id="mode_disabled",
            )

        yield Label("Platform URL:", classes="field-label")
        yield Input(
            placeholder="https://platform.getnit.dev",
            id="platform_url",
            classes="field-input",
        )

        yield Label("Platform API Key:", classes="field-label")
        yield Input(
            placeholder="Leave empty to configure later",
            password=True,
            id="platform_api_key",
            classes="field-input",
        )


class Step2LLM(StepContainer):
    """Step 2: LLM Configuration."""

    def compose_fields(self) -> ComposeResult:
        """Create child widgets."""
        yield Static(
            "[dim]Configure your AI model and provider[/dim]",
            classes="step-description",
        )

        yield Label("Mode:", classes="field-label")
        yield Select[str](
            options=[
                ("Built-in (API)", "builtin"),
                ("Claude CLI", "cli"),
                ("Ollama", "ollama"),
                ("Custom Command", "custom"),
            ],
            value="builtin",
            id="llm_mode",
            classes="field-select",
        )

        with Vertical(id="llm-api-fields"):
            yield Label("Provider:", classes="field-label")
            yield Select[str](
                options=[
                    ("OpenAI (GPT-4, etc.)", "openai"),
                    ("Anthropic (Claude)", "anthropic"),
                    ("Ollama (Local)", "ollama"),
                ],
                value="openai",
                id="llm_provider",
                classes="field-select",
            )

            yield Label("API Key:", classes="field-label")
            yield Input(
                placeholder="Or use NIT_LLM_API_KEY environment variable",
                password=True,
                id="llm_api_key",
                classes="field-input",
            )

        yield Label("Model:", classes="field-label")
        yield Input(
            placeholder="e.g., gpt-4o, claude-sonnet-4-5, llama3.1",
            value="gpt-4o",
            id="llm_model",
            classes="field-input",
        )

    @on(Select.Changed, "#llm_mode")
    def _on_mode_changed(self, event: Select.Changed) -> None:
        """Show/hide provider and API key fields based on selected mode."""
        api_fields = self.query_one("#llm-api-fields", Vertical)
        api_fields.display = event.value == "builtin"


class Step3Git(StepContainer):
    """Step 3: Git/PR Automation."""

    def compose_fields(self) -> ComposeResult:
        """Create child widgets."""
        yield Static(
            "[dim]Configure automatic git operations and PR creation[/dim]",
            classes="step-description",
        )

        with Horizontal(classes="checkbox-grid"):
            with Vertical(classes="checkbox-col"):
                yield Checkbox(
                    "Auto-commit generated tests/fixes",
                    id="git_auto_commit",
                )
                yield Checkbox(
                    "Auto-create GitHub issues for bugs",
                    id="git_create_issues",
                )
            with Vertical(classes="checkbox-col"):
                yield Checkbox(
                    "Auto-create PRs for changes",
                    id="git_auto_pr",
                )
                yield Checkbox(
                    "Auto-create separate fix PRs",
                    id="git_create_fix_prs",
                )

        yield Label("Branch Prefix:", classes="field-label")
        yield Input(
            placeholder="nit/",
            value="nit/",
            id="git_branch_prefix",
            classes="field-input",
        )


class Step4Report(StepContainer):
    """Step 4: Report & Output Configuration."""

    def compose_fields(self) -> ComposeResult:
        """Create child widgets."""
        yield Static(
            "[dim]Choose how nit displays and shares results[/dim]",
            classes="step-description",
        )

        yield Label("Output Format:", classes="field-label")
        with RadioSet(id="report_format"):
            yield RadioButton(
                "Terminal - Rich console output",
                id="format_terminal",
            )
            yield RadioButton("JSON - Machine-readable", id="format_json")
            yield RadioButton("HTML - Static reports", id="format_html")
            yield RadioButton("Markdown - Documentation", id="format_markdown")

        yield Label("Slack Webhook (optional):", classes="field-label")
        yield Input(
            placeholder="https://hooks.slack.com/services/...",
            id="report_slack_webhook",
            classes="field-input",
        )


class Step5E2E(StepContainer):
    """Step 5: E2E Testing Configuration."""

    def compose_fields(self) -> ComposeResult:
        """Create child widgets."""
        yield Static(
            "[dim]Configure end-to-end testing (optional)[/dim]",
            classes="step-description",
        )

        yield Checkbox("Enable E2E testing", id="e2e_enabled")

        yield Label("Base URL:", classes="field-label")
        yield Input(
            placeholder="http://localhost:3000",
            id="e2e_base_url",
            classes="field-input",
        )


class Step6Coverage(StepContainer):
    """Step 6: Coverage Thresholds Configuration."""

    def compose_fields(self) -> ComposeResult:
        """Create child widgets."""
        yield Static(
            "[dim]Configure coverage thresholds for quality gates[/dim]",
            classes="step-description",
        )

        yield Label("Line Coverage Threshold (%):", classes="field-label")
        yield Input(
            placeholder="80",
            value="80",
            id="coverage_line_threshold",
            classes="field-input",
        )

        yield Label("Branch Coverage Threshold (%):", classes="field-label")
        yield Input(
            placeholder="75",
            value="75",
            id="coverage_branch_threshold",
            classes="field-input",
        )

        yield Label("Function Coverage Threshold (%):", classes="field-label")
        yield Input(
            placeholder="85",
            value="85",
            id="coverage_function_threshold",
            classes="field-input",
        )

        yield Label(
            "Complexity Threshold (for high-priority gaps):",
            classes="field-label",
        )
        yield Input(
            placeholder="10",
            value="10",
            id="coverage_complexity_threshold",
            classes="field-input",
        )


class Step7Sentry(StepContainer):
    """Step 7: Sentry Observability Configuration."""

    def compose_fields(self) -> ComposeResult:
        """Create child widgets."""
        yield Static(
            "[dim]Configure Sentry error tracking and observability (optional)[/dim]",
            classes="step-description",
        )

        yield Checkbox("Enable Sentry error tracking", id="sentry_enabled")

        yield Label("Sentry DSN:", classes="field-label")
        yield Input(
            placeholder="https://key@o0.ingest.sentry.io/0",
            id="sentry_dsn",
            classes="field-input",
        )

        yield Label("Traces Sample Rate (0.0-1.0):", classes="field-label")
        yield Input(
            placeholder="0.0",
            value="0.0",
            id="sentry_traces_sample_rate",
            classes="field-input",
        )

        yield Label("Profiles Sample Rate (0.0-1.0):", classes="field-label")
        yield Input(
            placeholder="0.0",
            value="0.0",
            id="sentry_profiles_sample_rate",
            classes="field-input",
        )

        yield Checkbox("Enable Sentry Logs", id="sentry_enable_logs")


class Step8Docs(StepContainer):
    """Step 8: Documentation Generation Configuration."""

    def compose_fields(self) -> ComposeResult:
        """Create child widgets."""
        yield Static(
            "[dim]Configure how nit generates and manages documentation[/dim]",
            classes="step-description",
        )

        yield Checkbox("Enable documentation generation", id="docs_enabled", value=True)
        yield Checkbox("Write docstrings back to source files", id="docs_write_to_source")
        yield Checkbox(
            "Check for doc/code mismatches",
            id="docs_check_mismatch",
            value=True,
        )

        yield Label("Docstring Style:", classes="field-label")
        yield Select[str](
            options=[
                ("Auto-detect", ""),
                ("Google", "google"),
                ("NumPy", "numpy"),
            ],
            value="",
            id="docs_style",
            classes="field-select",
        )

        yield Label("Doc Framework Override:", classes="field-label")
        yield Select[str](
            options=[
                ("Auto-detect", ""),
                ("Sphinx (Python)", "sphinx"),
                ("TypeDoc (TypeScript)", "typedoc"),
                ("JSDoc (JavaScript)", "jsdoc"),
                ("Doxygen (C/C++)", "doxygen"),
                ("GoDoc (Go)", "godoc"),
                ("RustDoc (Rust)", "rustdoc"),
                ("MkDocs (Markdown)", "mkdocs"),
            ],
            value="",
            id="docs_framework",
            classes="field-select",
        )

        yield Label("Output Directory (optional):", classes="field-label")
        yield Input(
            placeholder="Leave empty for inline docstrings only",
            id="docs_output_dir",
            classes="field-input",
        )


class ConfigWizard(App[dict[str, Any] | None]):
    """Multi-step wizard for nit configuration."""

    CSS = """
    Screen {
        background: $surface;
        align: center middle;
    }

    #wizard-container {
        width: 140;
        height: auto;
        max-width: 95%;
        border: thick $primary;
        background: $panel;
        padding: 1 4;
    }

    #header-row {
        height: auto;
        align: center middle;
        margin: 0 0 1 0;
    }

    #logo {
        width: auto;
        shrink: 0;
        overflow: visible;
    }

    #header-row ProgressBar {
        width: 1fr;
        margin: 0 0 0 2;
    }

    ProgressBar {
        margin: 0;
    }

    #step-nav-row {
        height: auto;
        align: center middle;
        margin: 0 0 1 0;
    }

    #step-nav-row .step-header {
        width: 1fr;
        text-align: center;
        text-style: bold;
    }

    #step-nav-row Button {
        min-width: 12;
        margin: 0 1;
    }

    .step-description {
        text-align: center;
        margin: 0 0 1 0;
        color: $text-muted;
    }

    .field-label {
        margin: 0;
        color: $accent;
        text-style: bold;
    }

    .field-input, .field-select {
        width: 100%;
        margin: 0;
    }

    .checkbox-grid {
        height: auto;
        margin: 0 0 1 0;
    }

    .checkbox-col {
        width: 50%;
        height: auto;
    }

    Checkbox {
        margin: 0 1 0 1;
    }

    RadioButton {
        margin: 0;
    }

    .primary-button {
        background: $accent;
        border: solid $accent;
    }

    StepContainer {
        height: auto;
        padding: 0;
    }

    #llm-api-fields {
        height: auto;
    }
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+n", "next", "Next"),
        ("ctrl+p", "prev", "Previous"),
        ("f1", "help", "Help"),
    ]

    STEPS: ClassVar[list[tuple[str, type[StepContainer]]]] = [
        ("Platform Integration", Step1Platform),
        ("LLM Configuration", Step2LLM),
        ("Git/PR Automation", Step3Git),
        ("Report Output", Step4Report),
        ("E2E Testing", Step5E2E),
        ("Coverage Thresholds", Step6Coverage),
        ("Documentation", Step8Docs),
        ("Sentry Observability", Step7Sentry),
    ]

    def __init__(self, project_root: Path) -> None:
        super().__init__()
        self.project_root = project_root
        self.current_step = 0
        self.config_data: dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header(show_clock=False)
        with ScrollableContainer(id="wizard-container"):
            # Logo + progress bar on same row
            with Horizontal(id="header-row"):
                yield Static(NIT_LOGO, id="logo")
                yield ProgressBar(
                    total=len(self.STEPS),
                    show_eta=False,
                    id="progress-bar",
                )

            # Step content (dynamically replaced)
            yield Container(id="step-content")

        yield Footer()

    def on_mount(self) -> None:
        """Called when app starts."""
        self.title = "nit Configuration Wizard"
        self.sub_title = f"Project: {self.project_root}"
        self._show_step(0)

    def _show_step(self, step_index: int) -> None:
        """Display a specific step."""
        self.current_step = step_index
        step_title, step_class = self.STEPS[step_index]

        # Update progress bar
        progress_bar = self.query_one("#progress-bar", ProgressBar)
        progress_bar.update(progress=step_index + 1)

        # Replace step content
        container = self.query_one("#step-content", Container)
        container.remove_children()
        container.mount(step_class(step_index + 1, len(self.STEPS), step_title))

        # Update inline navigation buttons
        prev_btn = self.query_one("#prev-btn", Button)
        next_btn = self.query_one("#next-btn", Button)

        # Hide Back on first step
        prev_btn.display = step_index > 0

        # Show Finish on last step
        if step_index == len(self.STEPS) - 1:
            next_btn.label = "Finish"
            next_btn.variant = "success"
        else:
            next_btn.label = "Next →"
            next_btn.variant = "primary"

    @on(Button.Pressed, "#prev-btn")
    def _on_prev_pressed(self) -> None:
        """Handle Back button press."""
        self.action_prev()

    @on(Button.Pressed, "#next-btn")
    def _on_next_pressed(self) -> None:
        """Handle Next/Finish button press."""
        self.action_next()

    def action_prev(self) -> None:
        """Go to previous step."""
        if self.current_step > 0:
            self._collect_current_step()
            self._show_step(self.current_step - 1)

    def action_next(self) -> None:
        """Go to next step, or finish on the last step."""
        self._collect_current_step()
        if self.current_step < len(self.STEPS) - 1:
            self._show_step(self.current_step + 1)
        else:
            self.exit(result=self.config_data)

    def action_cancel(self) -> None:
        """Cancel configuration."""
        self.exit(result=None)

    def _collect_current_step(self) -> None:
        """Collect data from the currently visible step's widgets."""
        collectors = [
            self._collect_platform,
            self._collect_llm,
            self._collect_git,
            self._collect_report,
            self._collect_e2e,
            self._collect_coverage,
            self._collect_docs,
            self._collect_sentry,
        ]
        collectors[self.current_step]()

    def _collect_platform(self) -> None:
        platform_mode_btn = self.query_one("#platform_mode", RadioSet).pressed_button
        mode_map = {"mode_platform": "platform", "mode_byok": "byok"}
        platform_mode = "disabled"
        if platform_mode_btn and platform_mode_btn.id:
            platform_mode = mode_map.get(platform_mode_btn.id, "disabled")
        self.config_data["platform"] = {
            "mode": platform_mode,
            "url": self.query_one("#platform_url", Input).value,
            "api_key": self.query_one("#platform_api_key", Input).value,
        }

    def _collect_llm(self) -> None:
        self.config_data["llm"] = {
            "provider": str(self.query_one("#llm_provider", Select).value),
            "model": self.query_one("#llm_model", Input).value,
            "api_key": self.query_one("#llm_api_key", Input).value,
            "mode": str(self.query_one("#llm_mode", Select).value),
        }

    def _collect_git(self) -> None:
        self.config_data["git"] = {
            "auto_commit": bool(self.query_one("#git_auto_commit", Checkbox).value),
            "auto_pr": bool(self.query_one("#git_auto_pr", Checkbox).value),
            "create_issues": bool(self.query_one("#git_create_issues", Checkbox).value),
            "create_fix_prs": bool(self.query_one("#git_create_fix_prs", Checkbox).value),
            "branch_prefix": self.query_one("#git_branch_prefix", Input).value,
        }

    def _collect_report(self) -> None:
        report_format_btn = self.query_one("#report_format", RadioSet).pressed_button
        format_map = {
            "format_json": "json",
            "format_html": "html",
            "format_markdown": "markdown",
        }
        report_format = "terminal"
        if report_format_btn and report_format_btn.id:
            report_format = format_map.get(report_format_btn.id, "terminal")

        # Auto-derive upload flag from platform config (Step 1)
        platform_data = self.config_data.get("platform", {})
        upload = platform_data.get("mode", "disabled") != "disabled"

        self.config_data["report"] = {
            "format": report_format,
            "upload_to_platform": upload,
            "slack_webhook": self.query_one("#report_slack_webhook", Input).value,
        }

    def _collect_e2e(self) -> None:
        self.config_data["e2e"] = {
            "enabled": bool(self.query_one("#e2e_enabled", Checkbox).value),
            "base_url": self.query_one("#e2e_base_url", Input).value,
        }

    def _collect_coverage(self) -> None:
        self.config_data["coverage"] = {
            "line_threshold": float(
                self.query_one("#coverage_line_threshold", Input).value or "80"
            ),
            "branch_threshold": float(
                self.query_one("#coverage_branch_threshold", Input).value or "75"
            ),
            "function_threshold": float(
                self.query_one("#coverage_function_threshold", Input).value or "85"
            ),
            "complexity_threshold": int(
                self.query_one("#coverage_complexity_threshold", Input).value or "10"
            ),
        }

    def _collect_docs(self) -> None:
        self.config_data["docs"] = {
            "enabled": bool(self.query_one("#docs_enabled", Checkbox).value),
            "write_to_source": bool(self.query_one("#docs_write_to_source", Checkbox).value),
            "check_mismatch": bool(self.query_one("#docs_check_mismatch", Checkbox).value),
            "style": str(self.query_one("#docs_style", Select).value),
            "framework": str(self.query_one("#docs_framework", Select).value),
            "output_dir": self.query_one("#docs_output_dir", Input).value,
            "exclude_patterns": [],
            "max_tokens": 4096,
        }

    def _collect_sentry(self) -> None:
        self.config_data["sentry"] = {
            "enabled": bool(self.query_one("#sentry_enabled", Checkbox).value),
            "dsn": self.query_one("#sentry_dsn", Input).value,
            "traces_sample_rate": float(
                self.query_one("#sentry_traces_sample_rate", Input).value or "0.0"
            ),
            "profiles_sample_rate": float(
                self.query_one("#sentry_profiles_sample_rate", Input).value or "0.0"
            ),
            "enable_logs": bool(self.query_one("#sentry_enable_logs", Checkbox).value),
        }


def run_tui_init(project_root: Path) -> dict[str, Any] | None:
    """Run the interactive TUI configuration wizard.

    Args:
        project_root: Project root directory.

    Returns:
        Configuration dictionary if saved, None if cancelled.
    """
    app = ConfigWizard(project_root)
    return app.run()
