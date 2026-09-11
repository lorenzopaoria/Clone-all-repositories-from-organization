import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import requests

import clone_all_repos


class FakeResponse:
    def __init__(self, payload=None, status_code=200, json_error=None):
        self.payload = payload
        self.status_code = status_code
        self.json_error = json_error

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


class FetchRepositoriesTests(unittest.TestCase):
    @mock.patch("clone_all_repos.requests.get")
    def test_fetches_every_page(self, request_get):
        first_page = [
            {
                "name": "one",
                "ssh_url": "git@github.com:example-org/one.git",
                "clone_url": "https://github.com/example-org/one.git",
            },
            {
                "name": "two",
                "ssh_url": "git@github.com:example-org/two.git",
                "clone_url": "https://github.com/example-org/two.git",
            },
        ]
        request_get.side_effect = [FakeResponse(first_page), FakeResponse([])]

        repositories = clone_all_repos.fetch_repositories("example-org", "secret-token")

        self.assertEqual(repositories, first_page)
        self.assertEqual(request_get.call_count, 2)
        first_call = request_get.call_args_list[0]
        second_call = request_get.call_args_list[1]
        self.assertNotIn("secret-token", first_call.args[0])
        self.assertEqual(first_call.kwargs["params"]["page"], 1)
        self.assertEqual(second_call.kwargs["params"]["page"], 2)
        self.assertEqual(first_call.kwargs["timeout"], clone_all_repos.REQUEST_TIMEOUT)
        prepared_request = requests.Request("GET", first_call.args[0]).prepare()
        first_call.kwargs["auth"](prepared_request)
        self.assertEqual(
            prepared_request.headers["Authorization"], "Bearer secret-token"
        )

    @mock.patch("clone_all_repos.requests.get", side_effect=requests.Timeout)
    def test_reports_timeout(self, request_get):
        with self.assertRaisesRegex(clone_all_repos.RepositoryFetchError, "Timed out"):
            clone_all_repos.fetch_repositories("example-org", "secret-token")

    @mock.patch("clone_all_repos.requests.get", side_effect=requests.ConnectionError)
    def test_reports_connection_error(self, request_get):
        with self.assertRaisesRegex(
            clone_all_repos.RepositoryFetchError, "Could not connect"
        ):
            clone_all_repos.fetch_repositories("example-org", "secret-token")

    @mock.patch("clone_all_repos.requests.get")
    def test_reports_http_error_without_response_body(self, request_get):
        request_get.return_value = FakeResponse(
            {"message": "Forbidden"}, status_code=403
        )

        with self.assertRaisesRegex(clone_all_repos.RepositoryFetchError, "HTTP 403"):
            clone_all_repos.fetch_repositories("example-org", "secret-token")

    @mock.patch("clone_all_repos.requests.get")
    def test_rejects_invalid_json(self, request_get):
        request_get.return_value = FakeResponse(json_error=ValueError("invalid JSON"))

        with self.assertRaisesRegex(
            clone_all_repos.RepositoryFetchError, "invalid JSON"
        ):
            clone_all_repos.fetch_repositories("example-org", "secret-token")

    @mock.patch("clone_all_repos.requests.get")
    def test_rejects_non_list_response(self, request_get):
        request_get.return_value = FakeResponse({"message": "unexpected"})

        with self.assertRaisesRegex(
            clone_all_repos.RepositoryFetchError, "unexpected response"
        ):
            clone_all_repos.fetch_repositories("example-org", "secret-token")

    @mock.patch("clone_all_repos.requests.get")
    def test_rejects_incomplete_repository_data_before_returning(self, request_get):
        request_get.return_value = FakeResponse([{"name": "incomplete"}])

        with self.assertRaisesRegex(
            clone_all_repos.RepositoryFetchError, "invalid repository data"
        ):
            clone_all_repos.fetch_repositories("example-org", "secret-token")


class CloneRepositoriesTests(unittest.TestCase):
    def setUp(self):
        self.repository = {
            "name": "example",
            "ssh_url": "git@github.com:example-org/example.git",
            "clone_url": "https://github.com/example-org/example.git",
        }

    @mock.patch("clone_all_repos.subprocess.run")
    def test_uses_ssh_url_and_removes_token_from_environment(self, run):
        with (
            tempfile.TemporaryDirectory() as destination,
            mock.patch.dict(
                os.environ,
                {"GITHUB_TOKEN": "secret-token", "PATH": "/usr/bin"},
                clear=True,
            ),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                failures = clone_all_repos.clone_repositories(
                    [self.repository], destination, "ssh"
                )

        self.assertEqual(failures, [])
        command = run.call_args.args[0]
        child_environment = run.call_args.kwargs["env"]
        self.assertIn(self.repository["ssh_url"], command)
        self.assertNotIn("secret-token", " ".join(command))
        self.assertNotIn("GITHUB_TOKEN", child_environment)
        self.assertNotIn("secret-token", output.getvalue())
        self.assertTrue(run.call_args.kwargs["check"])

    @mock.patch("clone_all_repos.subprocess.run")
    def test_uses_unmodified_https_url(self, run):
        with (
            mock.patch.dict(
                os.environ,
                {"GITHUB_TOKEN": "secret-token", "PATH": "/usr/bin"},
                clear=True,
            ),
            tempfile.TemporaryDirectory() as destination,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            failures = clone_all_repos.clone_repositories(
                [self.repository], destination, "https"
            )

        self.assertEqual(failures, [])
        self.assertIn(self.repository["clone_url"], run.call_args.args[0])
        self.assertNotIn("GITHUB_TOKEN", run.call_args.kwargs["env"])

    @mock.patch("clone_all_repos.subprocess.run")
    def test_continues_after_a_clone_failure(self, run):
        second_repository = {
            "name": "second",
            "ssh_url": "git@github.com:example-org/second.git",
            "clone_url": "https://github.com/example-org/second.git",
        }
        run.side_effect = [subprocess.CalledProcessError(128, "git"), None]

        with (
            tempfile.TemporaryDirectory() as destination,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            failures = clone_all_repos.clone_repositories(
                [self.repository, second_repository], destination, "ssh"
            )

        self.assertEqual(failures, ["example"])
        self.assertEqual(run.call_count, 2)

    @mock.patch("clone_all_repos.subprocess.run")
    def test_skips_existing_destination(self, run):
        with tempfile.TemporaryDirectory() as destination:
            os.mkdir(os.path.join(destination, self.repository["name"]))
            with contextlib.redirect_stdout(io.StringIO()):
                failures = clone_all_repos.clone_repositories(
                    [self.repository], destination, "ssh"
                )

        self.assertEqual(failures, [])
        run.assert_not_called()

    @mock.patch("clone_all_repos.subprocess.run", side_effect=FileNotFoundError)
    def test_reports_missing_git(self, run):
        with (
            tempfile.TemporaryDirectory() as destination,
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(clone_all_repos.GitNotFoundError),
        ):
            clone_all_repos.clone_repositories([self.repository], destination, "ssh")


class MainTests(unittest.TestCase):
    def setUp(self):
        dotenv_patcher = mock.patch("clone_all_repos.load_dotenv")
        self.load_dotenv = dotenv_patcher.start()
        self.addCleanup(dotenv_patcher.stop)

    def test_protocol_accepts_https(self):
        self.assertEqual(
            clone_all_repos.parse_args(["--protocol", "https"]).protocol, "https"
        )

    def test_missing_token_stops_before_api_request(self):
        with (
            mock.patch.dict(os.environ, {"GITHUB_ORG": "example-org"}, clear=True),
            mock.patch("clone_all_repos.fetch_repositories") as fetch,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            exit_code = clone_all_repos.main([])

        self.assertEqual(exit_code, 1)
        fetch.assert_not_called()
        self.load_dotenv.assert_called_once_with(override=False)

    def test_missing_organization_stops_before_api_request(self):
        with (
            mock.patch.dict(os.environ, {"GITHUB_TOKEN": "secret-token"}, clear=True),
            mock.patch("clone_all_repos.fetch_repositories") as fetch,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            exit_code = clone_all_repos.main([])

        self.assertEqual(exit_code, 1)
        fetch.assert_not_called()

    def test_invalid_environment_protocol_stops_before_api_request(self):
        with (
            mock.patch.dict(
                os.environ,
                {
                    "GITHUB_TOKEN": "secret-token",
                    "GITHUB_ORG": "example-org",
                    "GITHUB_PROTOCOL": "invalid",
                },
                clear=True,
            ),
            mock.patch("clone_all_repos.fetch_repositories") as fetch,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            exit_code = clone_all_repos.main([])

        self.assertEqual(exit_code, 1)
        fetch.assert_not_called()

    def test_api_failure_stops_before_cloning(self):
        with (
            mock.patch.dict(
                os.environ,
                {"GITHUB_TOKEN": "secret-token", "GITHUB_ORG": "example-org"},
                clear=True,
            ),
            mock.patch(
                "clone_all_repos.fetch_repositories",
                side_effect=clone_all_repos.RepositoryFetchError("request failed"),
            ),
            mock.patch("clone_all_repos.clone_repositories") as clone,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            exit_code = clone_all_repos.main([])

        self.assertEqual(exit_code, 1)
        clone.assert_not_called()

    def test_clone_failure_produces_nonzero_exit_code(self):
        with (
            tempfile.TemporaryDirectory() as destination,
            mock.patch.dict(
                os.environ,
                {"GITHUB_TOKEN": "secret-token", "GITHUB_ORG": destination},
                clear=True,
            ),
            mock.patch(
                "clone_all_repos.fetch_repositories",
                return_value=[{"name": "failed"}],
            ),
            mock.patch(
                "clone_all_repos.clone_repositories",
                return_value=["failed"],
            ),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            exit_code = clone_all_repos.main([])

        self.assertEqual(exit_code, 1)

    def test_main_forwards_selected_protocol(self):
        with (
            tempfile.TemporaryDirectory() as destination,
            mock.patch.dict(
                os.environ,
                {"GITHUB_TOKEN": "secret-token", "GITHUB_ORG": destination},
                clear=True,
            ),
            mock.patch(
                "clone_all_repos.fetch_repositories",
                return_value=[{"name": "example"}],
            ),
            mock.patch("clone_all_repos.clone_repositories", return_value=[]) as clone,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            exit_code = clone_all_repos.main(["--protocol", "https"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(clone.call_args.args[2], "https")

    def test_main_uses_environment_protocol(self):
        with (
            tempfile.TemporaryDirectory() as destination,
            mock.patch.dict(
                os.environ,
                {
                    "GITHUB_TOKEN": "secret-token",
                    "GITHUB_ORG": destination,
                    "GITHUB_PROTOCOL": "https",
                },
                clear=True,
            ),
            mock.patch(
                "clone_all_repos.fetch_repositories",
                return_value=[{"name": "example"}],
            ),
            mock.patch("clone_all_repos.clone_repositories", return_value=[]) as clone,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            exit_code = clone_all_repos.main([])

        self.assertEqual(exit_code, 0)
        self.assertEqual(clone.call_args.args[2], "https")

    def test_main_defaults_to_ssh(self):
        with (
            tempfile.TemporaryDirectory() as destination,
            mock.patch.dict(
                os.environ,
                {"GITHUB_TOKEN": "secret-token", "GITHUB_ORG": destination},
                clear=True,
            ),
            mock.patch(
                "clone_all_repos.fetch_repositories",
                return_value=[{"name": "example"}],
            ),
            mock.patch("clone_all_repos.clone_repositories", return_value=[]) as clone,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            exit_code = clone_all_repos.main([])

        self.assertEqual(exit_code, 0)
        self.assertEqual(clone.call_args.args[2], "ssh")


if __name__ == "__main__":
    unittest.main()
