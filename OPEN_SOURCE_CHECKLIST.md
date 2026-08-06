# Open-Source Readiness Checklist

This checklist identifies everything to consider before making this repository public.
Items are grouped by priority based on open-source best practices.

---

## 🔴 Must Do

These are the minimum requirements before going public.

### Repository Files

- [ ] **Add a LICENSE file** — The repo has a copyright notice in source files but no `LICENSE` file. Choose an appropriate OSI-approved license (e.g., MIT, Apache 2.0) and add it to the root. Without it, the project is legally "all rights reserved" by default.
- [ ] **Add a README.md** — `pyproject.toml` references a `README.md` but none exists. It should include: what the project does, installation instructions, basic usage (with examples), supported geocoding providers, how to configure API keys (env vars, `.env` file), and required Python version.
- [ ] **Audit commit history for secrets** — Before making the repo public, scan the full git history for any accidental commits of API keys, credentials, or internal data using a tool like `git-secrets`, `trufflehog`, or `gitleaks`.
- [ ] **Review test data files** — The `public/` directory contains Excel files (`Canada Test Data.xlsx`, `Mexico Test Data.xlsx`, `U.S. Test Data.xlsx`). Confirm these contain no real PII, internal addresses, or proprietary data before exposing them publicly.
- [ ] **Decide on dependency separation** — Currently all dependencies (black, pylint, pytest, coverage, pdoc) are in `[tool.poetry.dependencies]` alongside runtime deps. Move dev/test/lint tools to `[tool.poetry.group.dev.dependencies]` so users installing the package don't pull in unnecessary tooling.
- [ ] **Resolve the copyright year** — Source files say `Copyright (c) 2026` but the current year is 2026. Confirm this is intentional and consistent across all files.

### GitHub Repository Settings

- [ ] **Enable secret scanning** — Turn on GitHub's native secret scanning (Settings → Security → Secret scanning) before or immediately after making the repo public.
- [ ] **Enable push protection** — Enable push protection in the same secret scanning settings panel to block future secret commits.
- [ ] **Set repository visibility to public carefully** — Review all open issues, PR descriptions, and comments before switching visibility; these all become public instantly.
- [ ] **Add a branch protection rule for `main`** — Require pull request reviews and passing status checks before merging. (Settings → Branches → Add rule)

---

## 🟡 Should Do

Important for community trust and usability, but not blocking.

### Repository Files

- [ ] **Add a `CONTRIBUTING.md`** — Describe how to set up the development environment, run tests, submit bug reports, and open pull requests. Include the branch naming convention and commit message style.
- [ ] **Add a `CHANGELOG.md`** — Document what has changed between versions, following a format like [Keep a Changelog](https://keepachangelog.com/).
- [ ] **Add a `SECURITY.md`** — Provide a responsible disclosure policy (e.g., "please email security@example.com for vulnerabilities rather than opening a public issue"). GitHub will surface this in the Security tab.
- [ ] **Add a `.env.example` file** — Show the expected environment variables (`GEOCODIO_API_KEY`, `GOOGLE_GEOCODING_API_KEY`) without real values, so new contributors know what to configure.
- [ ] **Add issue and PR templates** — Create `.github/ISSUE_TEMPLATE/bug_report.md`, `.github/ISSUE_TEMPLATE/feature_request.md`, and `.github/pull_request_template.md` to guide contributors.
- [ ] **Publish API documentation** — The CI already generates pdoc output as an artifact. Configure GitHub Pages (or another static host) to serve it at a public URL and link to it from the README.
- [ ] **Add a `CODE_OF_CONDUCT.md`** — Adopt the [Contributor Covenant](https://www.contributor-covenant.org/) or similar to set community expectations.

### Code Quality

- [ ] **Separate runtime from dev dependencies in `pyproject.toml`** — (See "Must Do" above — this also affects `should do` usability for downstream consumers if the package is ever published to PyPI.)
- [ ] **Fix the Python version comment mismatch** — Source file headers say `# -.- dependencies: Python 3.8+ -.-` but `pyproject.toml` requires `>=3.10.0`. Update the comments to reflect the actual requirement.
- [ ] **Add type checking (mypy)** — The codebase uses type annotations throughout; add mypy to the CI pipeline to catch type errors.
- [ ] **Add CodeQL or similar SAST scanning** — Enable GitHub's CodeQL analysis (Settings → Security → Code scanning) for automated vulnerability detection on every PR.

### GitHub Repository Settings

- [ ] **Enable Dependabot for Python dependencies** — The existing `dependabot.yml` only covers GitHub Actions. Add a `pip`/`poetry` ecosystem entry to keep Python dependencies patched automatically.
- [ ] **Configure Dependabot security updates** — Ensure Dependabot is configured to open PRs for security-only updates immediately, not just on the daily/weekly schedule.
- [ ] **Add required status checks to branch protection** — Specifically require the `Build and Test` CI job to pass before merging to `main`.
- [ ] **Restrict who can push directly to `main`** — Even as an open-source project, direct pushes to `main` should be limited to admins only.
- [ ] **Enable vulnerability alerts** — Turn on Dependabot alerts (Settings → Security → Dependabot alerts) if not already enabled.

---

## 🟢 Nice to Have

Lower-priority improvements that improve project maturity over time.

### Repository Files

- [ ] **Add a `pyproject.toml` entry point** — Define `[tool.poetry.scripts]` so users can invoke `geocoder` from the command line after `pip install`, rather than running `python geocoder.py`.
- [ ] **Consider publishing to PyPI** — If external users should be able to `pip install pangaea-geocoder` (or similar), configure the package properly and add a release workflow. Set `package-mode = true` in `pyproject.toml` and add classifiers, keywords, etc.
- [ ] **Add a `CODEOWNERS` file** — Define who is responsible for reviewing changes to specific parts of the codebase (`.github/CODEOWNERS`).
- [ ] **Add badges to README** — Once the repo is public, add CI status, license, and (if published) PyPI version badges.
- [ ] **Consider adding a `CITATION.cff` file** — If academic or professional citation is relevant, this file makes it easy for users to cite the project.

### CI / GitHub Actions

- [ ] **Pin GitHub Actions to a specific commit SHA** — Currently actions like `actions/checkout@v7` are pinned by tag (mutable). Pinning to full commit SHAs improves supply-chain security.
- [ ] **Add a release workflow** — Automate changelog generation and tagging on version bumps, or create a GitHub Release when a version tag is pushed.
- [ ] **Upload documentation to GitHub Pages** — Instead of just uploading pdoc output as an artifact, deploy it to GitHub Pages automatically on merge to `main`.
- [ ] **Add a code coverage badge and Codecov integration** — Upload coverage reports to Codecov or a similar service to display a coverage badge in the README.
- [ ] **Expand CI matrix** — Consider testing against multiple Python versions (3.10, 3.11, 3.12, 3.13) to verify compatibility across the supported range.

### GitHub Repository Settings

- [ ] **Add repository topics/tags** — Add relevant topics (e.g., `geocoding`, `python`, `excel`, `address-validation`) so the repo is discoverable.
- [ ] **Write a repository description** — Set a short description in the GitHub repository settings.
- [ ] **Configure the repository website URL** — Link to documentation or a project site once available.
- [ ] **Enable Discussions** — If community Q&A is desired, enable GitHub Discussions as an alternative to filing issues for support questions.
- [ ] **Set up a project board or roadmap** — A GitHub Project board can help communicate what is planned, in progress, and done.
