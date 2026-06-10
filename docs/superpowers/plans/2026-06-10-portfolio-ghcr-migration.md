# Portfolio GHCR Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the portfolio the same way as `life-dashboard`: build the portfolio Docker image in its own GitHub repository, publish it to GHCR, and make `My_server` pull that image.

**Architecture:** The `portfolio` repository owns application source, Dockerfile, and image publishing. The `My_server` repository owns only orchestration and references `ghcr.io/gi99lin/portfolio:latest` from the root compose file. The `portfolio` submodule is removed from `My_server` so updates no longer require submodule pointer changes.

**Tech Stack:** Docker, Docker Compose, Git submodules, GitHub Actions, GitHub Container Registry, nginx.

---

## File Map

- `/Users/ivanakimkin/Projects/portfolio/.github/workflows/docker-publish.yml`
  - New workflow that builds, smoke-tests, and pushes `ghcr.io/gi99lin/portfolio:latest`.
- `/Users/ivanakimkin/Projects/My_server/docker-compose.yml`
  - Change `landing` from local `build: ./portfolio` to the published GHCR image.
- `/Users/ivanakimkin/Projects/My_server/.gitmodules`
  - Remove the `portfolio` submodule section.
- `/Users/ivanakimkin/Projects/My_server/portfolio`
  - Remove from the git index as a submodule entry. The sibling repository at `/Users/ivanakimkin/Projects/portfolio` stays intact.
- `/Users/ivanakimkin/Projects/My_server/README.md`
  - Update wording so the landing page is described as an external GHCR image, not a submodule.

---

### Task 1: Add Portfolio GHCR Workflow

**Files:**
- Create: `/Users/ivanakimkin/Projects/portfolio/.github/workflows/docker-publish.yml`

- [ ] **Step 1: Verify current missing workflow state**

Run:

```sh
test -f /Users/ivanakimkin/Projects/portfolio/.github/workflows/docker-publish.yml
```

Expected: FAIL with exit code `1`, because the workflow does not exist yet.

- [ ] **Step 2: Create the workflow directory**

Run:

```sh
mkdir -p /Users/ivanakimkin/Projects/portfolio/.github/workflows
```

- [ ] **Step 3: Add the workflow file**

Create `/Users/ivanakimkin/Projects/portfolio/.github/workflows/docker-publish.yml` with:

```yaml
name: Publish Docker image

on:
  push:
    branches: [ "main", "master" ]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ghcr.io/${{ github.repository_owner }}/portfolio

jobs:
  build-and-push-image:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Log in to the Container registry
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Lowercase image name
        run: |
          echo "IMAGE_NAME=${IMAGE_NAME,,}" >> ${GITHUB_ENV}

      - name: Build image
        run: |
          docker build -t "${IMAGE_NAME}:latest" .

      - name: Smoke test image
        run: |
          docker run --rm --entrypoint nginx "${IMAGE_NAME}:latest" -t

      - name: Push image
        run: |
          for attempt in 1 2 3; do
            echo "Pushing ${IMAGE_NAME}:latest (attempt ${attempt}/3)"
            if docker push "${IMAGE_NAME}:latest"; then
              exit 0
            fi
            echo "Push failed; retrying after registry backoff..."
            sleep "$((attempt * 20))"
          done

          echo "Push failed after 3 attempts"
          exit 1
```

- [ ] **Step 4: Verify workflow file exists**

Run:

```sh
test -f /Users/ivanakimkin/Projects/portfolio/.github/workflows/docker-publish.yml
```

Expected: PASS with exit code `0`.

- [ ] **Step 5: Build the portfolio image locally**

Run:

```sh
cd /Users/ivanakimkin/Projects/portfolio && docker build -t ghcr.io/gi99lin/portfolio:latest .
```

Expected: PASS with exit code `0`.

- [ ] **Step 6: Smoke test the local image**

Run:

```sh
docker run --rm --entrypoint nginx ghcr.io/gi99lin/portfolio:latest -t
```

Expected: PASS with nginx reporting configuration syntax is ok and test is successful.

- [ ] **Step 7: Commit the workflow in `portfolio`**

Run:

```sh
cd /Users/ivanakimkin/Projects/portfolio
git add .github/workflows/docker-publish.yml
git commit -m "ci: publish portfolio docker image"
```

Expected: commit succeeds and includes only the workflow file.

---

### Task 2: Switch `landing` To GHCR Image

**Files:**
- Modify: `/Users/ivanakimkin/Projects/My_server/docker-compose.yml`

- [ ] **Step 1: Verify compose still uses local build**

Run:

```sh
cd /Users/ivanakimkin/Projects/My_server
python3 - <<'PY'
from pathlib import Path
text = Path("docker-compose.yml").read_text()
raise SystemExit(0 if "context: ./portfolio" in text and "image: vps-server-landing" in text else 1)
PY
```

Expected: PASS with exit code `0`, documenting the current state before the change.

- [ ] **Step 2: Change the `landing` service image**

Update the service from:

```yaml
  landing:
    build:
      context: ./portfolio
      dockerfile: Dockerfile
    image: vps-server-landing
    container_name: landing
    restart: unless-stopped
    networks:
      - proxy_network
```

to:

```yaml
  landing:
    image: ghcr.io/gi99lin/portfolio:latest
    container_name: landing
    restart: unless-stopped
    networks:
      - proxy_network
```

- [ ] **Step 3: Verify compose references the GHCR image**

Run:

```sh
cd /Users/ivanakimkin/Projects/My_server
python3 - <<'PY'
from pathlib import Path
text = Path("docker-compose.yml").read_text()
ok = (
    "image: ghcr.io/gi99lin/portfolio:latest" in text
    and "context: ./portfolio" not in text
    and "image: vps-server-landing" not in text
)
raise SystemExit(0 if ok else 1)
PY
```

Expected: PASS with exit code `0`.

- [ ] **Step 4: Validate compose syntax**

Run:

```sh
cd /Users/ivanakimkin/Projects/My_server && docker compose config
```

Expected: PASS with exit code `0`; rendered `landing` service uses `ghcr.io/gi99lin/portfolio:latest`.

---

### Task 3: Remove Portfolio Submodule From `My_server`

**Files:**
- Modify: `/Users/ivanakimkin/Projects/My_server/.gitmodules`
- Remove from git index: `/Users/ivanakimkin/Projects/My_server/portfolio`

- [ ] **Step 1: Verify current submodule state**

Run:

```sh
cd /Users/ivanakimkin/Projects/My_server
git config -f .gitmodules --get-regexp '^submodule\.portfolio\.'
git ls-files --stage portfolio
```

Expected: PASS with output showing `.gitmodules` entries and a `160000` gitlink entry for `portfolio`.

- [ ] **Step 2: Remove the submodule from the index and `.gitmodules`**

Run:

```sh
cd /Users/ivanakimkin/Projects/My_server
git rm --cached portfolio
git config -f .gitmodules --remove-section submodule.portfolio
```

Expected: `portfolio` is staged for deletion as a gitlink, and `.gitmodules` no longer has a `portfolio` section.

- [ ] **Step 3: Remove empty `.gitmodules` if applicable**

Run:

```sh
cd /Users/ivanakimkin/Projects/My_server
if [ ! -s .gitmodules ]; then
  rm .gitmodules
fi
```

Expected: `.gitmodules` is deleted if it became empty; otherwise it remains with any non-portfolio submodules.

- [ ] **Step 4: Verify submodule is no longer tracked**

Run:

```sh
cd /Users/ivanakimkin/Projects/My_server
python3 - <<'PY'
from pathlib import Path
gitmodules = Path(".gitmodules")
text = gitmodules.read_text() if gitmodules.exists() else ""
raise SystemExit(0 if "submodule \"portfolio\"" not in text and "path = portfolio" not in text else 1)
PY
git ls-files --stage portfolio | grep -q . && exit 1 || exit 0
```

Expected: PASS with exit code `0`.

- [ ] **Step 5: Verify sibling portfolio repository is intact**

Run:

```sh
cd /Users/ivanakimkin/Projects/portfolio && git status --short --branch
```

Expected: PASS with output showing the `portfolio` repository branch status. The workflow from Task 1 may be clean if committed.

---

### Task 4: Update Server Documentation

**Files:**
- Modify: `/Users/ivanakimkin/Projects/My_server/README.md`

- [ ] **Step 1: Verify README still describes the old submodule model**

Run:

```sh
cd /Users/ivanakimkin/Projects/My_server
python3 - <<'PY'
from pathlib import Path
text = Path("README.md").read_text()
raise SystemExit(0 if "integrated as a Git submodule" in text else 1)
PY
```

Expected: PASS with exit code `0`.

- [ ] **Step 2: Update landing page wording**

Change:

```md
- **Landing Page**: Custom nginx-based personal portfolio website running alongside NPM (integrated as a Git submodule at `portfolio/`).
```

to:

```md
- **Landing Page**: Custom nginx-based personal portfolio website running alongside NPM from the prebuilt `ghcr.io/gi99lin/portfolio:latest` image.
```

Change:

```md
- `portfolio/` - Personal portfolio landing page (integrated as a Git submodule).
```

to:

```md
- Portfolio landing page - deployed from `ghcr.io/gi99lin/portfolio:latest`; source lives in the separate `portfolio` repository.
```

- [ ] **Step 3: Verify README describes the new model**

Run:

```sh
cd /Users/ivanakimkin/Projects/My_server
python3 - <<'PY'
from pathlib import Path
text = Path("README.md").read_text()
ok = (
    "ghcr.io/gi99lin/portfolio:latest" in text
    and "integrated as a Git submodule" not in text
)
raise SystemExit(0 if ok else 1)
PY
```

Expected: PASS with exit code `0`.

---

### Task 5: Final Verification And Commit

**Files:**
- Commit in `/Users/ivanakimkin/Projects/My_server`:
  - `/Users/ivanakimkin/Projects/My_server/docker-compose.yml`
  - `/Users/ivanakimkin/Projects/My_server/.gitmodules` deletion or modification
  - `/Users/ivanakimkin/Projects/My_server/portfolio` gitlink deletion
  - `/Users/ivanakimkin/Projects/My_server/README.md`
  - `/Users/ivanakimkin/Projects/My_server/docs/superpowers/plans/2026-06-10-portfolio-ghcr-migration.md`

- [ ] **Step 1: Check `portfolio` repository status**

Run:

```sh
cd /Users/ivanakimkin/Projects/portfolio && git status --short --branch
```

Expected: PASS. If the Task 1 workflow commit succeeded, there are no uncommitted workflow changes.

- [ ] **Step 2: Check `My_server` status without touching unrelated files**

Run:

```sh
cd /Users/ivanakimkin/Projects/My_server && git status --short
```

Expected: output includes only intended changed files plus pre-existing unrelated `hermes/hermes-qa/*` changes. Do not stage unrelated `hermes/hermes-qa/*` files.

- [ ] **Step 3: Validate compose one more time**

Run:

```sh
cd /Users/ivanakimkin/Projects/My_server && docker compose config
```

Expected: PASS with exit code `0`.

- [ ] **Step 4: Stage only intended `My_server` files**

Run:

```sh
cd /Users/ivanakimkin/Projects/My_server
git add docker-compose.yml README.md docs/superpowers/plans/2026-06-10-portfolio-ghcr-migration.md
if [ -e .gitmodules ]; then git add .gitmodules; else git rm --cached --ignore-unmatch .gitmodules; fi
git add -u portfolio
```

Expected: only intended migration files are staged.

- [ ] **Step 5: Review staged diff**

Run:

```sh
cd /Users/ivanakimkin/Projects/My_server && git diff --cached --stat && git diff --cached --name-status
```

Expected: staged paths are `docker-compose.yml`, `README.md`, `.gitmodules` deletion/modification, `portfolio` deletion, and the plan file.

- [ ] **Step 6: Commit `My_server` migration**

Run:

```sh
cd /Users/ivanakimkin/Projects/My_server
git commit -m "chore: deploy portfolio from ghcr image"
```

Expected: commit succeeds without including unrelated `hermes/hermes-qa/*` changes.

