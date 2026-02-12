# Dashboard

nit can generate interactive HTML dashboards for visualizing test results, coverage metrics, and trends.

## Generating a dashboard

```bash
# Generate an HTML dashboard
nit report --html

# Generate and serve locally
nit report --html --serve

# Serve on a custom port
nit report --html --serve --port 3000
```

## Dashboard contents

The HTML dashboard includes:

- **Test results summary** — pass/fail/error counts with trend charts
- **Coverage metrics** — line, branch, and function coverage with file-level breakdowns
- **Bug findings** — detected bugs with severity, location, and description
- **Drift alerts** — code changes that may indicate regressions
- **Trend data** — historical coverage and test result trends

## Configuration

```yaml
report:
  format: html                   # Default output format
  html_output_dir: .nit/reports  # Output directory
  serve_port: 8080               # Port for local serving
```

## Output location

Reports are written to the `html_output_dir` (default: `.nit/reports/`). The main file is `index.html`.

## Trend data

Use the `--days` flag to control how much historical data is included:

```bash
nit report --html --days 30
```

This pulls from nit's analytics history stored in `.nit/memory/`.

## CI integration

In CI, generate the dashboard and upload it as an artifact:

```yaml
- name: Run nit
  run: nit --ci pick --format json

- name: Generate dashboard
  run: nit report --html

- name: Upload dashboard
  uses: actions/upload-artifact@v4
  with:
    name: nit-dashboard
    path: .nit/reports/
```
