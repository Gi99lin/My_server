# Self-hosted GitHub Actions runner for Gi99lin/ai-testcase-generator.
#
# Base: myoung34/github-runner's Ubuntu 24.04 (noble) build - the newest OS variant
# that image publishes, picked over its default (Ubuntu 20.04 "focal") tag because
# the TMS frontend job installs Playwright browsers with `--with-deps`, and current
# Playwright releases target current Ubuntu LTS packages, not 20.04's.
FROM myoung34/github-runner:ubuntu-noble@sha256:c310e303ef09c037fbf3dca4668a9e2961331e03e0dc7ab0824c9efd91618fab

# The TMS backend CI job runs `psql` directly on the runner (not inside a
# container) to create a throwaway database and exercise an Alembic
# downgrade/upgrade round trip against it. The upstream image has git, curl,
# jq, make, openssl, python3, node and the docker CLI + compose plugin
# already, but no PostgreSQL client.
#
# python-is-python3: ci.yml's e2e job runs a `python -c ...` one-liner
# directly on the runner (checking docker-compose.e2e.yml's resolved license
# mount) to verify the license file is bind-mounted read-only before the
# stack starts. GitHub-hosted Ubuntu runners carry a bare `python` alongside
# `python3`; plain Ubuntu 24.04 deliberately does not - confirmed by running
# this exact job here first (`python: command not found`, exit 127) before
# adding the package.
#
# python3-openpyxl: the e2e suite's lib-15 excel-export spec downloads the
# exported .xlsx and reads it back with openpyxl to assert its rows, via
# `process.env.PYTHON` (falling back, when unset, to a path under the
# maintainer's own home directory that exists only on his Mac). ci.yml sets
# PYTHON for the e2e job to this package's interpreter - confirmed missing
# by running the suite here first (`spawnSync .../.venv/bin/python ENOENT`,
# the fallback path, since nothing set PYTHON) before adding the package;
# same gap would hit a GitHub-hosted runner, so this is not self-hosted-only.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client python-is-python3 python3-openpyxl \
    && rm -rf /var/lib/apt/lists/*
