<p align="center">
  <a href="https://focale-editor.app">
    <img src=".github/assets/focale.png" alt="Focale app logo" width="112" height="112">
  </a>
</p>

<h1 align="center">Focale Web</h1>

The browser distribution repository for **Focale**, a photo and vector editor.

**[Open Focale in your browser](https://web.focale-editor.app)**.
The web edition is a beta; browser capabilities and available memory can affect
which documents and operations work comfortably.

[Website](https://focale-editor.app) ·
[Desktop downloads](https://focale-editor.app/#downloads) ·
[Releases](https://github.com/focale-editor/focale-web/releases) ·
[Community & support](https://github.com/focale-editor/community)

## Working with documents

Imported files, preferences and recovery data are stored in this browser's private
storage. Saving or exporting downloads a file; it does not replace the original
file on disk. Keep downloaded copies of documents you want to retain. Clearing
site data or using a private browsing session affects local retention.

Supported Chromium and Firefox browsers can use WebAssembly. Safari uses the
JavaScript fallback while its Wasm release checks remain pending. System printing
and Hunspell are unavailable; export a PDF to print. Font access depends on the
browser and its permissions. The desktop application remains available for native
file integration and workloads that exceed browser limits.

## Updates

Open [web.focale-editor.app](https://web.focale-editor.app) to enter the current
release. Existing tabs keep their version; save your work and return to that
address when you want to update. Installed shortcuts also open the current release.

The site retains the current and previous complete releases. An older tab may
need to be reopened after more releases have been published. Documents remain
under the same browser origin across versions; this is not cloud synchronization.

## About this repository

This repository contains the public publication tools and Pages configuration.
Application bundles are GitHub Release assets, not files committed to Git.

| File | Purpose |
| --- | --- |
| [`repository.json`](repository.json) | Public repository, domain and branch. |
| [`scripts/package.py`](scripts/package.py) | Package, verify and stage immutable browser bundles. |
| [`scripts/release.py`](scripts/release.py) | Resume publication and download verified releases for Pages. |
| [`.github/workflows/pages.yml`](.github/workflows/pages.yml) | Deploy the latest stable release and retain its predecessor. |
| [`MAINTAINING.md`](MAINTAINING.md) | Initial GitHub/DNS setup and publication operations. |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Local checks and contribution guidelines. |

Each release supplies `focale-<version>-web.zip` and `focale-<version>-web.json`.
The metadata binds the archive and every file to their SHA-256 checksums, full
application version and source commit. These checks detect changed or incomplete
assets; publication trust comes from the protected GitHub repositories and HTTPS.

Pages serves complete bundles at `/releases/<tag>/`. The root selects the current
version, avoiding dependencies on custom HTTP cache headers. Pages does not
provide configurable COOP/COEP headers: Wasm rendering uses the browser's
non-isolated fallback. Browser tests exercise this hosting condition.

## Feedback and help

Report application and browser issues in
[Focale Community](https://github.com/focale-editor/community). Include your
Focale version, browser/version, operating system, and the steps that failed.
See the application's About dialog and the [license catalogue](https://focale-editor.app/docs/licenses)
for third-party notices and source access.
