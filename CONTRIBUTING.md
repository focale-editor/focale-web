# Contributing to Focale Web

This repository maintains browser distribution and GitHub Pages deployment.
For editor bugs, feature requests and questions, use
[Focale Community](https://github.com/focale-editor/community).

## Scope

Changes here cover public documentation, archive verification, release handling
and Pages configuration. The application release pipeline supplies the compiled
application. Do not commit bundles, credentials, application source files or source
maps. Published release bytes are immutable; corrections require another version.

Versioning and changelogs belong to `dart run release` in the application repository.
Pull requests here must not independently assign application versions or tags.

## Local validation

Use Python 3.12 or newer. The tooling requires only its standard library.

```bash
python3 -m unittest discover -s scripts -p '*_test.py'
git diff --check
actionlint .github/workflows/pages.yml
```

If actionlint's runner registry does not yet recognize `ubuntu-26.04`, verify the
label against [GitHub's supported images](https://github.com/actions/runner-images)
and use a temporary runner-label configuration for that check.

To inspect downloaded release assets without publishing:

```bash
python3 scripts/release.py verify --input build/download --tag v1.0.0
python3 scripts/release.py stage --input build/download --tag v1.0.0 --output site
python3 -m http.server 8000 --directory site
```

Replace the sample tag with the downloaded release's tag. The output directory
must not exist. To retain its predecessor, add `--previous build/previous
--previous-tag v0.9.0` to `stage`. Open `http://localhost:8000/` and check that the
application starts and reloads at `/`, with resources loaded from the current
`/releases/<tag>/` directory and content-hashed database files from `/workers/`.
Missing assets must return 404, not the app HTML.

Unit tests cover integrity, unsafe archives, release retention, retry immutability
and stale deployments. Browser startup tests run with the compiled application in
the build pipeline. Local checks do not establish production DNS, HTTPS or actual
Safari compatibility.

## Pull requests

Target `main`. Explain the problem, resulting behavior and checks performed. Use
a Conventional Commits title such as `fix: reject incomplete web archives` or
`docs: clarify browser storage`. Link relevant community issues with
`Fixes focale-editor/community#123` when applicable.
