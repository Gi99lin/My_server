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
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*
