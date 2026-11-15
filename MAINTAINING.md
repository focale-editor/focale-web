# Maintaining Focale Web

## Initial setup

1. Create the public repository **`focale-editor/focale-web`** and push this checkout's
   initial commit to `main`. The local `origin` is already configured. Protect
   `main` and review changes to publication tools and workflows.
2. In **Settings → Pages**, select **GitHub Actions** as the build source.
   Set the custom domain to **`web.focale-editor.app`**. The generated `CNAME`
   file documents that domain but does not configure repository settings.
3. At the DNS provider, add a **CNAME** record named **`web`**, targeting
   **`focale-editor.github.io`** (without a repository path). Remove conflicting
   records for this subdomain. Wait for Pages DNS checks and certificate issuance,
   then enable **Enforce HTTPS**. See [GitHub's domain guide](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site).
4. Restrict the **`github-pages`** environment to `main`.
5. In the private Focale repository's **`distribution`** environment, add
   **`FOCALE_WEB_TOKEN`**, a fine-grained token owned by `focale-editor` and limited
   to `focale-web`, with **Contents: read/write** and **Actions: read/write**.
6. Push the Focale and GetFocale pipeline changes. Create a new application release
   tag containing the browser integration; older source tags lack its build tool.
   GetFocale's existing source-read credentials are reused. Web compilation is
   part of the build workflow and requires this public repository to exist first.
7. Set **`FOCALE_WEB_PUBLISH=true`** in the private Focale repository variables
   when Pages, DNS and the token are ready. Without it, builds produce the web
   artifact but the private workflow skips web publication.

This checkout does not create the remote repository, configure DNS, or install
credentials. Commit/push and hosted setup are separate operations.

## Release flow

GetFocale compiles the same source commit as the desktop packages. Its web job
prepares translations, generated sources, license notices and workers, then builds
Wasm plus JavaScript with a release-specific base path. It packages the result,
stages it, and probes Chromium/Wasm, Chromium/JavaScript and Firefox/Wasm without
cross-origin isolation. Only the verified ZIP and JSON are uploaded as the `web`
Actions artifact, retained for 30 days.

After the complete build succeeds, private Focale validates build provenance and
publishes the desktop release, including corresponding third-party sources. Its
web publication job then checks the version and source commit, uploads the browser
assets here, and dispatches `pages.yml`. Public prereleases do not replace this
stable web channel; the application's beta status is independent of that channel.

The Pages workflow downloads the latest stable release by numeric application
version and its immediate predecessor, verifies every file, and publishes the
complete snapshot. The site budget is 950 MiB uncompressed, below GitHub Pages'
[1 GB site limit](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits).
Compiled assets are never added to Git history. Missing assets receive real 404s;
there is no SPA fallback or service worker added by this repository.

## Retry and recovery

For a failed upload, rerun the private publication using the same build run ID.
Identical complete assets are reused; partial drafts can resume. Changed published
bytes or changed complete drafts are rejected. Publication never rebuilds the app.

For a failed Pages deployment after assets were published, rerun **Deploy Focale
Web** here with the current stable tag. It needs no source repository access:

```bash
gh workflow run pages.yml --repo focale-editor/focale-web --ref main -f tag=v1.0.0
```

Older versions cannot replace the latest stable release through this workflow.
Fix a defective version with a new application release. Keep release attachments:
Actions artifact expiry does not remove the durable GitHub Release copies.

## Browser and hosting checks

GitHub Pages controls HTTP caching and does not expose custom response-header
configuration. Do not add `_headers` files expecting them to change Pages behavior.
The complete versioned paths protect open tabs from mixed application, worker and
codec versions. The root redirect may remain cached briefly after deployment;
the retained previous release remains usable. Rendering runs without COOP/COEP
isolation; this is covered by the build probes, not a promise of desktop performance.

Before announcing the beta, check the actual HTTPS domain in Chromium, Firefox
and Safari: open/edit/undo/save/reopen/export, reload persistence, fonts, and
unsaved-navigation protection. Check the root redirect, missing-asset 404s and
`application/wasm` responses. Installed shortcuts must open `/` on this origin.
The web release does not add cloud storage or a backend.
