# Releasing

How to ship a new version of HR-Kit to PyPI, npm, and GitHub Releases.

> Maintainers only. End users don't need this — see [INSTALL.md](INSTALL.md).

## Channels

| Channel | What ships | Trigger |
|---|---|---|
| **PyPI** | `hrkit-X.Y.Z-py3-none-any.whl` + `hrkit-X.Y.Z.tar.gz` | Pushing a `vX.Y.Z` tag (auto via `.github/workflows/publish-pypi.yml`) |
| **npm** | `@thinqmesh/hrkit@X.Y.Z` (the Node wrapper) | Manual `npm publish` from `cli/` (2FA blocks tokens for publish) |
| **GitHub Pages** | The marketing site at <https://anitchaudhry.github.io/HRKit/> | Push to `main` that touches `website/**` (auto via `.github/workflows/deploy-pages.yml`) |
| **GitHub Releases** | Wheel + sdist attached to the tag | Manual `gh release create` |

## Five-step release

### 1. Bump version

Two files must move in lockstep:

```diff
# pyproject.toml
- version = "0.2.1"
+ version = "0.2.2"

# cli/package.json
- "version": "0.2.1",
+ "version": "0.2.2",
```

(Optional but recommended: also bump `__version__` in `hrkit/__init__.py`
so `hrkit --version` prints the right number.)

### 2. Commit + tag + push

```bash
git add pyproject.toml cli/package.json hrkit/__init__.py
git commit -m "Release v0.2.2 — <one-line changelog>"
git tag -a v0.2.2 -m "v0.2.2"
git push --tags
```

Pushing the tag triggers the `Publish to PyPI` workflow. It:

1. Checks out the tag,
2. Installs `build` and `twine`,
3. Runs `python -m build` → `dist/hrkit-X.Y.Z-py3-none-any.whl` and `dist/hrkit-X.Y.Z.tar.gz`,
4. `twine check dist/*` to validate metadata,
5. Uploads with `pypa/gh-action-pypi-publish` using the `PYPI_API_TOKEN` secret.

Watch progress:

```bash
gh run list --repo AnitChaudhry/HRKit --limit 3
gh run watch <id> --repo AnitChaudhry/HRKit
```

When it goes green, verify:

```bash
pip index versions hrkit
# Should show the new X.Y.Z available.
```

### 3. Publish to npm

This step is **manual** because npm 2FA blocks granular tokens from
publishing without an OTP, and the OTP only lives 30 seconds — too short
for any chat-driven workflow.

From a real terminal on a machine where you ran `npm login` recently:

```bash
cd cli
# Open your authenticator, then:
npm publish --access public --otp=<6-digit-code>
```

If you get `EOTP`, the code expired in transit — generate a fresh one
and rerun. Verify:

```bash
npm view @thinqmesh/hrkit version
# Should print the new X.Y.Z.
```

#### Alternative: granular access token (no OTP per publish)

1. <https://www.npmjs.com/settings/thinqmesh-tech/tokens> → Generate New Token → Granular.
2. Scope: `@thinqmesh/hrkit` read+write, expiry 7 days.
3. Copy the `npm_...` value.
4. From `cli/`:
   ```bash
   printf '//registry.npmjs.org/:_authToken=npm_xxxx\n' > /tmp/.npmrc-publish
   npm publish --access public --userconfig=/tmp/.npmrc-publish
   rm /tmp/.npmrc-publish
   ```
5. Revoke the token on npm afterwards (or let the 7-day expiry lapse).

### 4. Attach wheel + sdist to the GitHub Release

```bash
rm -rf dist/
python -m build
gh release create vX.Y.Z dist/hrkit-X.Y.Z-py3-none-any.whl dist/hrkit-X.Y.Z.tar.gz \
  --repo AnitChaudhry/HRKit \
  --title "vX.Y.Z — <one-line summary>" \
  --notes "$(cat <<'EOF'
<release notes — see v0.2.1 for the format>
EOF
)"
```

Verify the assets are downloadable (shouldn't 404 once the workflow
finishes setting permissions):

```bash
curl -sIL "https://github.com/AnitChaudhry/HRKit/releases/download/vX.Y.Z/hrkit-X.Y.Z-py3-none-any.whl" | head -3
```

### 5. Update CHANGELOG.md

Move "Unreleased" entries into a new `## vX.Y.Z — YYYY-MM-DD` section.
Commit. (No push needed — it'll go out with the next merge to `main`.)

## Required GitHub secrets

| Secret | Used by | How to set |
|---|---|---|
| `PYPI_API_TOKEN` | `publish-pypi.yml` | `gh secret set PYPI_API_TOKEN --repo AnitChaudhry/HRKit` (paste when prompted). Project-scoped is preferred over account-wide. |

That's the only one. npm publish doesn't run from CI yet (the OTP issue);
GitHub Pages uses the implicit `GITHUB_TOKEN`.

## Branch protection

`main` is protected:

- 1 PR approval required before merge
- Stale approvals dismissed when new commits push
- Conversation resolution required
- Force pushes blocked
- Deletions blocked
- Owner (you) can self-merge after approving (admins not enforced)

Direct pushes to `main` are blocked for non-owners; PR-only for
contributors.

## What about an automated release-please / semantic-release flow?

Not configured. Each release is a deliberate decision (bumped version,
written changelog, pinned tag) so we can keep the npm 2FA dance manual
without disrupting CI. Revisit if release frequency goes weekly.

## When something goes wrong

| Symptom | Fix |
|---|---|
| PyPI workflow fails with `403 Forbidden` | Token expired or revoked. Generate a fresh project-scoped token at <https://pypi.org/manage/account/token/> and re-set with `gh secret set PYPI_API_TOKEN`. |
| PyPI workflow says "File already exists" | You re-tagged the same version. Bump and re-tag. The `skip-existing: true` flag in the workflow makes this non-fatal but a no-op. |
| `npm publish` says `EPUBLISHCONFLICT` | Same version already on npm. Bump `cli/package.json` and retry. |
| Pages deploy succeeds but site shows old content | CDN cache. Hard-refresh (Ctrl+Shift+R) or wait ~5 min. |
| Tests pass locally but fail in CI | Usually a Python 3.10 / 3.11 / 3.12 syntax difference (e.g., f-string backslashes are 3.12-only). Reproduce locally with `pyenv` or `actuate the matching Python` then fix. |
