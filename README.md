# Clone All GitHub Repositories from an Organization

This script discovers every GitHub repository accessible to a token in one
organization and clones each repository into a local organization directory.
GitHub API pagination is handled automatically.

The API token is kept separate from Git authentication. It is loaded from a
local `.env` file or the process environment, used only in the API authorization
header, and removed from the environment passed to Git. It is never added to
clone URLs or stored in repository configuration.

## Requirements

- Python 3.11 or later
- Git
- An API token that can list the required organization repositories
- An SSH key or HTTPS credential helper that can clone those repositories

Install the Python dependency in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On Windows PowerShell, activate the environment with:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Configuration

### 1. Create a GitHub token

Use a fine-grained personal access token whenever your organization supports
one:

1. Select the target organization as the resource owner.
2. Limit repository access to only the repositories that must be discovered.
3. Grant read-only `Metadata` repository permission. Metadata access is enough
   for the API endpoint used by this script.
4. Set a short expiration date.
5. Complete organization approval or SSO authorization if required.

An organization policy or your membership type may require a classic token
instead. In that case, private repository discovery requires the broader
`repo` scope. Prefer a fine-grained token whenever possible.

The token only controls API discovery. Your SSH key or HTTPS credential helper
must independently have access to each private repository being cloned.

### 2. Create the local `.env`

Create `.env` from the tracked `.env.example` and restrict its permissions on
Linux or macOS:

```bash
cp .env.example .env
chmod 600 .env
```

Configure the three values:

```dotenv
GITHUB_TOKEN=github_pat_replace_with_your_token
GITHUB_ORG=your-organization-slug
GITHUB_PROTOCOL=ssh
```

`GITHUB_ORG` must be the slug shown in the organization's GitHub URL, not its
display name. `GITHUB_PROTOCOL` accepts `ssh` or `https` and defaults to `ssh`
when omitted.

The repository ignores `.env` and tracks only `.env.example`. Never force-add
`.env` to Git. Environment variables set outside the file take precedence,
which is useful for CI or temporary overrides.

Do not write the token in `clone_all_repos.py`, a clone URL, command arguments,
or a shell profile. Keep `.env` local and readable only by your user.

## Git Authentication

### SSH (default)

Add an SSH key for any GitHub identity that can access the repositories, and
verify the connection before running the script. The SSH identity does not need
to match the account that created the API token:

```bash
ssh -T git@github.com
```

See GitHub's [SSH setup documentation](https://docs.github.com/en/authentication/connecting-to-github-with-ssh)
if a key is not configured yet.

Set `GITHUB_PROTOCOL=ssh` in `.env` and run:

```bash
python clone_all_repos.py
```

The script uses each repository's `ssh_url`.

### HTTPS

Configure Git Credential Manager before selecting HTTPS so Git can use an OS
credential store while keeping its credentials separate from the API token.

GitHub CLI is also supported: run `gh auth login`, select HTTPS, and allow the
CLI to authenticate Git. Pay attention to any warning that credentials could
not be stored in a credential store; GitHub CLI can otherwise fall back to a
plain-text file. Never configure Git's plain-text `credential.helper store`.
See GitHub's [credential storage documentation](https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git)
for setup instructions.

Set `GITHUB_PROTOCOL=https` in `.env`, or override it for one run:

```bash
python clone_all_repos.py --protocol https
```

The HTTPS URL is passed to Git unchanged. Public repositories need no Git
credentials. Private repositories use any secure Git-compatible credential
helper already configured by the user. `GITHUB_TOKEN` is not forwarded to the
Git process.

## Behavior and Errors

- The API requests up to 100 repositories per page until every page is read.
- No cloning starts unless repository discovery completes successfully.
- API requests time out after 30 seconds and connection, HTTP, and malformed
  response errors produce a non-zero exit status.
- Existing destination paths are skipped and never overwritten.
- A failed clone is reported, but the script continues with the remaining
  repositories and exits with a non-zero status at the end.
- The token is never printed or included in Git arguments.

If the API succeeds but reports zero repositories for an organization that has
private repositories, verify that the fine-grained token uses that organization
as its resource owner, includes the required repositories, and has been approved
by the organization.

## Testing

The test suite mocks GitHub and Git, so it does not require a real token and
does not clone real repositories:

```bash
python -m unittest discover -s tests -v
```

## If a Token Was Exposed

If a token was ever placed in this script, a clone URL, logs, or shell history:

1. Revoke the token immediately in GitHub settings.
2. Create a replacement with the minimum permissions and a short expiration.
3. Remove authenticated URLs from every previously cloned repository.
4. Remove the token from local files, logs, and shell history where possible.

Inspect and replace a repository's `origin` URL with SSH:

```bash
git -C path/to/repository remote get-url origin
git -C path/to/repository remote set-url origin git@github.com:ORG/REPOSITORY.git
```

Or replace it with a clean HTTPS URL:

```bash
git -C path/to/repository remote set-url origin https://github.com/ORG/REPOSITORY.git
```

Revocation is required even after removing the URL because the credential may
already have been copied elsewhere.
