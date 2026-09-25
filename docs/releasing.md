# Releasing to PyPI

`.github/workflows/release.yml` handles the whole release mechanically —
re-runs the full test suite, builds the package, and publishes it — but it
can't do the one thing only a human with a PyPI account can do: register
the project. That's a one-time setup, done once by whoever will own
`pypi.org/project/hashimori`. Everything after that is automatic.

No API token is created or stored anywhere in this process. PyPI's
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/) lets GitHub
Actions authenticate directly via a short-lived OIDC token scoped to this
exact repo and workflow — there's nothing to leak and nothing to rotate.

## One-time setup

1. Create a PyPI account at [pypi.org](https://pypi.org/account/register/)
   if you don't have one, and turn on 2FA (required before you can publish
   anything).
2. Go to [pypi.org/manage/account/publishing](https://pypi.org/manage/account/publishing/)
   and add a **new pending publisher**, filled in exactly:
   - **PyPI Project Name:** `hashimori`
   - **Owner:** `OSMoats`
   - **Repository name:** `hashimori`
   - **Workflow name:** `release.yml`
   - **Environment name:** `pypi`
3. Submit. This is the whole registration — nothing else to do on the PyPI
   side. The first time `release.yml` successfully runs from this exact
   repo, PyPI creates the `hashimori` project automatically and this
   registration becomes its permanent trusted publisher.
4. Recommended, not required: in the GitHub repo, go to **Settings →
   Environments → New environment**, name it exactly `pypi` (must match
   step 2), and optionally add yourself as a required reviewer. That adds
   one manual "approve this publish" click before anything actually reaches
   PyPI, without changing anything else about the automation.

## Cutting a release

1. Bump the version in `pyproject.toml` (e.g. `0.1.0` → `0.2.0`) and merge
   that as a normal PR. PyPI permanently refuses to re-accept a version
   number that's already been published, so this has to change every time.
2. Tag the merge commit and push the tag:
   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```
3. On GitHub: **Releases → Draft a new release**, pick the tag you just
   pushed, write release notes, **Publish release**.
4. Publishing the release triggers `release.yml` automatically:
   - Re-runs the full `ci.yml` test matrix (3.9 and 3.12) as the gate —
     nothing gets built or published if anything fails.
   - Verifies the release tag matches `pyproject.toml`'s version, and
     fails loudly (not silently) if they don't match, naming both values.
   - Builds the sdist and wheel, and runs `twine check` on them.
   - Publishes to PyPI via Trusted Publishing. If you added the required
     reviewer in step 4 above, this is the point you'll be asked to
     approve.
   - PyPI also auto-attaches a [Sigstore attestation](https://docs.pypi.org/attestations/)
     to the release, proving it was built from this exact commit by this
     exact workflow — on by default with Trusted Publishing, nothing to
     configure.

## What not to do

- Don't `twine upload` manually with a personal API token. Once Trusted
  Publishing is registered, that would be a secret to create, store, and
  rotate for no reason — the whole point is not needing one.
- Don't bump the version without tagging it to match, or tag without
  bumping `pyproject.toml` first. The workflow's version-check step exists
  specifically to catch this and refuse to publish, rather than publish
  the wrong thing under the right name.
