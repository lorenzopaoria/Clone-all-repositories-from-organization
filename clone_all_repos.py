import argparse
import os
import subprocess
import sys

import requests
from dotenv import load_dotenv

API_URL = "https://api.github.com/orgs/{org_name}/repos"
REQUEST_TIMEOUT = 30


class RepositoryFetchError(Exception):
    pass


class GitNotFoundError(Exception):
    pass


class BearerAuth(requests.auth.AuthBase):
    def __init__(self, token):
        self.token = token

    def __call__(self, request):
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Clone every accessible repository from a GitHub organization."
    )
    parser.add_argument(
        "--protocol",
        choices=("ssh", "https"),
        help="Override GITHUB_PROTOCOL from .env (default: ssh).",
    )
    return parser.parse_args(argv)


def fetch_repositories(org_name, token):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
    }
    repositories = []
    page = 1

    while True:
        try:
            response = requests.get(
                API_URL.format(org_name=org_name),
                auth=BearerAuth(token),
                headers=headers,
                params={"type": "all", "per_page": 100, "page": page},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except requests.Timeout as error:
            raise RepositoryFetchError(
                f"Timed out while fetching repository page {page}."
            ) from error
        except requests.ConnectionError as error:
            raise RepositoryFetchError(
                f"Could not connect to GitHub while fetching repository page {page}."
            ) from error
        except requests.HTTPError as error:
            status_code = (
                error.response.status_code if error.response is not None else "unknown"
            )
            raise RepositoryFetchError(
                f"GitHub returned HTTP {status_code} for repository page {page}."
            ) from error
        except requests.RequestException as error:
            raise RepositoryFetchError(
                f"The request for repository page {page} failed."
            ) from error

        try:
            repositories_page = response.json()
        except ValueError as error:
            raise RepositoryFetchError(
                f"GitHub returned invalid JSON for repository page {page}."
            ) from error

        if not isinstance(repositories_page, list):
            raise RepositoryFetchError(
                f"GitHub returned an unexpected response for repository page {page}."
            )
        if not repositories_page:
            return repositories

        for repository in repositories_page:
            if not isinstance(repository, dict):
                raise RepositoryFetchError(
                    f"GitHub returned invalid repository data on page {page}."
                )

            repository_name = repository.get("name")
            ssh_url = repository.get("ssh_url")
            clone_url = repository.get("clone_url")
            if (
                not isinstance(repository_name, str)
                or not repository_name
                or os.path.basename(repository_name) != repository_name
                or repository_name in {".", ".."}
                or not isinstance(ssh_url, str)
                or not ssh_url.startswith("git@github.com:")
                or not isinstance(clone_url, str)
                or not clone_url.startswith("https://github.com/")
            ):
                raise RepositoryFetchError(
                    f"GitHub returned invalid repository data on page {page}."
                )

        repositories.extend(repositories_page)
        page += 1


def clone_repositories(repositories, destination, protocol):
    url_key = "ssh_url" if protocol == "ssh" else "clone_url"
    failed_repositories = []
    git_environment = os.environ.copy()
    git_environment.pop("GITHUB_TOKEN", None)

    for repository in repositories:
        try:
            repository_name = repository["name"]
            clone_url = repository[url_key]
        except (KeyError, TypeError):
            print("Error: GitHub returned incomplete repository data.", file=sys.stderr)
            failed_repositories.append("<unknown>")
            continue

        repository_path = os.path.join(destination, repository_name)
        if os.path.exists(repository_path):
            print(f"The repository {repository_name} already exists.")
            continue

        print(f"Cloning {repository_name}...")
        try:
            subprocess.run(
                ["git", "clone", "--", clone_url, repository_path],
                check=True,
                env=git_environment,
            )
        except FileNotFoundError:
            raise GitNotFoundError from None
        except subprocess.CalledProcessError:
            print(f"Error: failed to clone {repository_name}.", file=sys.stderr)
            failed_repositories.append(repository_name)

    return failed_repositories


def main(argv=None):
    load_dotenv(override=False)
    args = parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    org_name = os.environ.get("GITHUB_ORG", "").strip()
    protocol = args.protocol or os.environ.get("GITHUB_PROTOCOL", "ssh").strip().lower()

    if not token:
        print(
            "Error: GITHUB_TOKEN is not set in the environment or .env.",
            file=sys.stderr,
        )
        return 1
    if not org_name:
        print(
            "Error: GITHUB_ORG is not set in the environment or .env.", file=sys.stderr
        )
        return 1
    if protocol not in {"ssh", "https"}:
        print("Error: GITHUB_PROTOCOL must be either ssh or https.", file=sys.stderr)
        return 1

    try:
        repositories = fetch_repositories(org_name, token)
    except RepositoryFetchError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    try:
        os.makedirs(org_name, exist_ok=True)
    except OSError as error:
        print(
            f"Error: could not create the destination directory: {error}",
            file=sys.stderr,
        )
        return 1

    print(f"Number of repositories found: {len(repositories)}")
    if not repositories:
        print("No repositories found in the organization.")
        return 0

    try:
        failed_repositories = clone_repositories(repositories, org_name, protocol)
    except GitNotFoundError:
        print(
            "Error: Git is not installed or is not available in PATH.", file=sys.stderr
        )
        return 1
    if failed_repositories:
        print(
            f"Failed to clone {len(failed_repositories)} repository/repositories: "
            f"{', '.join(failed_repositories)}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
