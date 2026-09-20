# Contributing to Geocoder

Thank you for contributing. Please keep changes focused, include tests when
behavior changes, and do not commit API keys, credentials, or sensitive address
data. Community participation is governed by the [Code of
Conduct](.github/CODE_OF_CONDUCT.md).

## Development Environment

Geocoder supports Python `>=3.10,<3.15` and uses
[Poetry](https://python-poetry.org/) to manage dependencies.

1. Fork the repository and clone your fork.
2. Create a branch from the current `main` branch.
3. Install the runtime and development dependencies:

   ```bash
   poetry install
   ```

4. Confirm the command-line interface is available:

   ```bash
   poetry run geocoder --help
   ```

Provider integration work may require `GEOCODIO_API_KEY` or
`GOOGLE_GEOCODING_API_KEY`. Set keys in your environment or in a local `.env`
file; never commit that file or its values. Prefer mocked provider responses in
tests so the test suite does not make network requests.

## Tests And Checks

Run the full test suite from the repository root:

```bash
poetry run pytest test
```

Before opening a pull request, run the same checks enforced by CI:

```bash
poetry run black --check .
poetry run pylint *.py */*.py
poetry run mypy src
poetry run coverage run --branch -m pytest test
poetry run coverage report --fail-under=95 ./*.py src/*.py
poetry run pdoc -o ./docs *.py
```

Use `poetry run black .` to format Python files. Add or update focused tests in
`test/` for changed behavior. Do not commit generated `docs/`, coverage output,
SQLite caches, or local credentials.

## Branches And Commits

Create branches from `main` using the established task-based convention:

```text
Task<issue-number>-<short-kebab-case-description>
```

For example, `Task27702-address-validation` or
`Task27956-prevent-repeat-api-calls`. If there is no issue, use a short
descriptive branch name such as `fix-cache-cleanup`.

Write concise, imperative commit subjects. Start with the task number when one
exists, summarize one logical change, and avoid punctuation at the end:

```text
Task27702 validate required address fields
Fix cache cleanup on failed requests
```

Keep unrelated formatting or refactoring out of functional commits. Explain
non-obvious context, compatibility impact, or follow-up work in the commit body
when needed.

## Bug Reports

Search existing issues before opening a new report. Use the [bug report
template](https://github.com/pangaeatech/geocoder/issues/new?template=bug_report.md)
and include:

- A concise summary and reproducible steps.
- Expected and actual behavior, including the complete error or traceback.
- Your OS, Python version, Geocoder commit or version, provider, and command.
- A minimal sanitized workbook or sample rows and relevant logs.

Never attach API keys, credentials, private addresses, or other sensitive data.
Report security vulnerabilities according to [SECURITY.md](SECURITY.md), not in
a public issue.

## Pull Requests

1. Open the pull request against `main` from a focused branch.
2. Complete the [pull request template](.github/pull_request_template.md), link
   the related issue, and describe validation performed.
3. Add or update tests and documentation when the change affects behavior or
   user-facing usage.
4. Ensure the checks above pass and address review feedback.

Keep pull requests small enough to review. Call out provider-specific behavior,
API compatibility concerns, cache effects, and any work that remains for a
follow-up change.
