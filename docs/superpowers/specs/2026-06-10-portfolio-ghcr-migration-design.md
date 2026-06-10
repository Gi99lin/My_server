# Portfolio GHCR Migration Design

## Goal

Move the portfolio deployment out of the server repository and make it follow the same update model as `life-dashboard`: the application repository builds and publishes a Docker image to GitHub Container Registry, while `My_server` only pulls and runs that image.

## Current State

- `My_server` includes `portfolio/` as a Git submodule pointing to `https://github.com/Gi99lin/portfolio.git`.
- The root `docker-compose.yml` builds the `landing` service locally from `./portfolio`.
- A separate local repository already exists at `/Users/ivanakimkin/Projects/portfolio`.
- `life-dashboard` already uses prebuilt GHCR images in its compose file and publishes them through GitHub Actions.

## Chosen Approach

Use the separate `portfolio` repository as the only source of portfolio code and publish its image as:

```text
ghcr.io/gi99lin/portfolio:latest
```

In `My_server`, remove the `portfolio` submodule and update the root `landing` service to use the GHCR image instead of a local build context.

This keeps the server repository focused on orchestration and makes portfolio updates consistent with `life-dashboard`.

## Repository Changes

### `portfolio` repository

- Add `.github/workflows/docker-publish.yml`.
- Build the existing `Dockerfile`.
- Smoke test the nginx image configuration before pushing.
- Push `ghcr.io/gi99lin/portfolio:latest` on pushes to `main` or `master`.

### `My_server` repository

- Remove `portfolio` from `.gitmodules`.
- Remove the `portfolio` submodule entry from the git index.
- Leave the sibling `/Users/ivanakimkin/Projects/portfolio` repository intact.
- Update the root `docker-compose.yml` `landing` service:
  - remove `build.context: ./portfolio`
  - remove `build.dockerfile: Dockerfile`
  - set `image: ghcr.io/gi99lin/portfolio:latest`

## Deployment Flow

1. Change portfolio code in `/Users/ivanakimkin/Projects/portfolio`.
2. Push changes to GitHub.
3. GitHub Actions builds and pushes `ghcr.io/gi99lin/portfolio:latest`.
4. On the server, update the running service with:

```sh
docker compose pull landing
docker compose up -d landing
```

## Verification

- Validate the root compose file with `docker compose config`.
- Validate the portfolio image builds locally with `docker build`.
- Smoke test the nginx image with `nginx -t`, matching the dashboard workflow style.
- Confirm `My_server` no longer tracks `portfolio` as a submodule.
- Confirm `/Users/ivanakimkin/Projects/portfolio` remains a normal git repository.

## Risks And Handling

- The first server pull depends on the GitHub Actions workflow having published the package. Mitigation: build/push workflow is added before deploying the compose change remotely.
- GHCR package visibility may need to be public or the server must authenticate with `docker login ghcr.io`. This mirrors the same operational concern as `life-dashboard`.
- The existing local `portfolio/` directory inside `My_server` may remain on disk after git removal. It should be treated as disposable working-tree residue and removed only after confirming the sibling portfolio repository is intact.
