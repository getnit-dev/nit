"""Transport-level HTTP tests for GitHubAPI.

These tests use the ``responses`` library to intercept ``requests`` calls at the
transport layer, verifying that the correct URLs, headers, and request bodies
are sent to the GitHub REST API.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import requests as _requests
import responses
from responses import matchers

from nit.utils.git import (
    GitHubAPI,
    GitHubAPIError,
    GitHubPRInfo,
    PullRequestParams,
)

_BASE = "https://api.github.com"

_EXPECTED_HEADERS = {
    "Authorization": "Bearer test-value",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _req_url(call: responses.Call) -> str:
    """Extract the request URL from a responses.Call, narrowing away None."""
    url = call.request.url
    assert url is not None
    return url


def _req_body(call: responses.Call) -> dict[str, Any]:
    """Parse the JSON request body from a responses.Call."""
    body = call.request.body
    assert body is not None
    parsed: dict[str, Any] = json.loads(body)
    return parsed


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> GitHubAPI:
    """Create a GitHubAPI instance backed by a test token."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-value")
    return GitHubAPI()


@pytest.fixture()
def pr_info() -> GitHubPRInfo:
    """Standard PR info using GitHub's canonical example owner/repo."""
    return GitHubPRInfo(owner="octocat", repo="hello-world", pr_number=42)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COMMENT_RESPONSE: dict[str, Any] = {
    "id": 1,
    "node_id": "MDEyOklzc3VlQ29tbWVudDE=",
    "html_url": ("https://github.com/octocat/hello-world/issues/42#issuecomment-1"),
    "body": "Test comment",
    "user": {"login": "bot", "id": 1},
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z",
}


# ---------------------------------------------------------------------------
# TestCreateComment
# ---------------------------------------------------------------------------


class TestCreateComment:
    """POST /repos/{owner}/{repo}/issues/{pr_number}/comments."""

    @responses.activate
    def test_url_headers_and_body(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"
        responses.add(
            responses.POST,
            url,
            json=_COMMENT_RESPONSE,
            status=201,
            match=[
                matchers.header_matcher(_EXPECTED_HEADERS),
                matchers.json_params_matcher({"body": "Test comment"}),
            ],
        )

        result = api.create_comment(pr_info, "Test comment")

        assert result == _COMMENT_RESPONSE
        assert len(responses.calls) == 1
        assert _req_url(responses.calls[0]) == url

    @responses.activate
    def test_markdown_and_unicode_body(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        body = "## Coverage\n| pkg | % |\n|---|---|\n| web | 85 |\n\n🎉 résumé"
        url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"
        responses.add(
            responses.POST,
            url,
            json={**_COMMENT_RESPONSE, "body": body},
            status=201,
            match=[matchers.json_params_matcher({"body": body})],
        )

        result = api.create_comment(pr_info, body)

        assert result["body"] == body

    @responses.activate
    def test_response_returned_unchanged(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"
        responses.add(responses.POST, url, json=_COMMENT_RESPONSE, status=201)

        result = api.create_comment(pr_info, "Test comment")

        assert result["id"] == 1
        assert result["node_id"] == "MDEyOklzc3VlQ29tbWVudDE="
        assert result["user"]["login"] == "bot"


# ---------------------------------------------------------------------------
# TestUpdateComment
# ---------------------------------------------------------------------------


class TestUpdateComment:
    """PATCH /repos/{owner}/{repo}/issues/comments/{comment_id}."""

    @responses.activate
    def test_url_and_method(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues/comments/999"
        responses.add(
            responses.PATCH,
            url,
            json={**_COMMENT_RESPONSE, "id": 999, "body": "Updated"},
            status=200,
            match=[
                matchers.header_matcher(_EXPECTED_HEADERS),
                matchers.json_params_matcher({"body": "Updated"}),
            ],
        )

        result = api.update_comment(pr_info, 999, "Updated")

        assert result["id"] == 999
        assert len(responses.calls) == 1
        assert _req_url(responses.calls[0]) == url
        assert responses.calls[0].request.method == "PATCH"


# ---------------------------------------------------------------------------
# TestFindCommentByMarker
# ---------------------------------------------------------------------------


class TestFindCommentByMarker:
    """GET /repos/{owner}/{repo}/issues/{pr_number}/comments."""

    @responses.activate
    def test_returns_matching_comment(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        marker = "<!-- nit:coverage:abc123 -->"
        comments: list[dict[str, Any]] = [
            {"id": 1, "body": "unrelated comment"},
            {"id": 2, "body": f"{marker}\n## Coverage report"},
            {"id": 3, "body": "another comment"},
        ]
        url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"
        responses.add(
            responses.GET,
            url,
            json=comments,
            status=200,
            match=[matchers.header_matcher(_EXPECTED_HEADERS)],
        )

        result = api.find_comment_by_marker(pr_info, marker)

        assert result is not None
        assert result["id"] == 2

    @responses.activate
    def test_returns_none_when_not_found(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        comments: list[dict[str, Any]] = [
            {"id": 1, "body": "unrelated"},
            {"id": 2, "body": "also unrelated"},
        ]
        url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"
        responses.add(responses.GET, url, json=comments, status=200)

        result = api.find_comment_by_marker(pr_info, "<!-- not-here -->")

        assert result is None

    @responses.activate
    def test_returns_none_for_empty_list(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"
        responses.add(responses.GET, url, json=[], status=200)

        result = api.find_comment_by_marker(pr_info, "<!-- nit -->")

        assert result is None

    @responses.activate
    def test_handles_comment_without_body_key(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        comments: list[dict[str, Any]] = [
            {"id": 1},  # no "body" key
            {"id": 2, "body": "<!-- nit --> content"},
        ]
        url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"
        responses.add(responses.GET, url, json=comments, status=200)

        result = api.find_comment_by_marker(pr_info, "<!-- nit -->")

        assert result is not None
        assert result["id"] == 2


# ---------------------------------------------------------------------------
# TestUpsertComment
# ---------------------------------------------------------------------------


class TestUpsertComment:
    """Composite: find_comment_by_marker → create_comment or update_comment."""

    @responses.activate
    def test_creates_when_no_existing_comment(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        marker = "<!-- nit:test -->"
        comments_url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"

        # GET returns empty list (no existing comment)
        responses.add(responses.GET, comments_url, json=[], status=200)
        # POST creates the comment
        responses.add(
            responses.POST,
            comments_url,
            json={**_COMMENT_RESPONSE, "body": f"{marker}\nNew content"},
            status=201,
        )

        result = api.upsert_comment(pr_info, f"{marker}\nNew content", marker)

        assert result["body"] == f"{marker}\nNew content"
        assert len(responses.calls) == 2
        assert responses.calls[0].request.method == "GET"
        assert responses.calls[1].request.method == "POST"

    @responses.activate
    def test_updates_when_existing_comment_found(
        self, api: GitHubAPI, pr_info: GitHubPRInfo
    ) -> None:
        marker = "<!-- nit:test -->"
        comments_url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"
        update_url = f"{_BASE}/repos/octocat/hello-world/issues/comments/555"

        # GET returns existing comment with marker
        responses.add(
            responses.GET,
            comments_url,
            json=[{"id": 555, "body": f"{marker}\nOld content"}],
            status=200,
        )
        # PATCH updates the existing comment
        responses.add(
            responses.PATCH,
            update_url,
            json={**_COMMENT_RESPONSE, "id": 555, "body": f"{marker}\nUpdated"},
            status=200,
        )

        result = api.upsert_comment(pr_info, f"{marker}\nUpdated", marker)

        assert result["id"] == 555
        assert len(responses.calls) == 2
        assert responses.calls[0].request.method == "GET"
        assert responses.calls[1].request.method == "PATCH"
        assert "/issues/comments/555" in _req_url(responses.calls[1])

    @responses.activate
    def test_prepends_marker_when_missing_from_body(
        self, api: GitHubAPI, pr_info: GitHubPRInfo
    ) -> None:
        marker = "<!-- nit:coverage -->"
        comments_url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"

        responses.add(responses.GET, comments_url, json=[], status=200)
        responses.add(responses.POST, comments_url, json=_COMMENT_RESPONSE, status=201)

        api.upsert_comment(pr_info, "plain text without marker", marker)

        # The POST body should have marker prepended
        posted_body = _req_body(responses.calls[1])["body"]
        assert posted_body.startswith(marker)
        assert "plain text without marker" in posted_body

    @responses.activate
    def test_preserves_marker_when_already_present(
        self, api: GitHubAPI, pr_info: GitHubPRInfo
    ) -> None:
        marker = "<!-- nit:coverage -->"
        body = f"{marker}\n## Report"
        comments_url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"

        responses.add(responses.GET, comments_url, json=[], status=200)
        responses.add(responses.POST, comments_url, json=_COMMENT_RESPONSE, status=201)

        api.upsert_comment(pr_info, body, marker)

        posted_body = _req_body(responses.calls[1])["body"]
        # Marker should appear exactly once
        assert posted_body.count(marker) == 1
        assert posted_body == body


# ---------------------------------------------------------------------------
# TestCreatePullRequest
# ---------------------------------------------------------------------------


class TestCreatePullRequest:
    """POST /repos/{owner}/{repo}/pulls."""

    @responses.activate
    def test_url_and_body(self, api: GitHubAPI) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/pulls"
        expected_body: dict[str, Any] = {
            "title": "Add tests",
            "body": "Generated by nit",
            "head": "nit/generated-tests",
            "base": "main",
            "draft": False,
        }
        pr_response: dict[str, Any] = {
            "number": 42,
            "html_url": "https://github.com/octocat/hello-world/pull/42",
            "state": "open",
            "title": "Add tests",
        }
        responses.add(
            responses.POST,
            url,
            json=pr_response,
            status=201,
            match=[
                matchers.header_matcher(_EXPECTED_HEADERS),
                matchers.json_params_matcher(expected_body),
            ],
        )

        params = PullRequestParams(
            owner="octocat",
            repo="hello-world",
            title="Add tests",
            body="Generated by nit",
            head="nit/generated-tests",
            base="main",
        )
        result = api.create_pull_request(params)

        assert result == pr_response
        assert len(responses.calls) == 1
        assert _req_url(responses.calls[0]) == url

    @responses.activate
    def test_draft_pr(self, api: GitHubAPI) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/pulls"
        responses.add(
            responses.POST,
            url,
            json={"number": 1},
            status=201,
            match=[
                matchers.json_params_matcher(
                    {
                        "title": "Draft PR",
                        "body": "",
                        "head": "feature",
                        "base": "main",
                        "draft": True,
                    }
                ),
            ],
        )

        params = PullRequestParams(
            owner="octocat",
            repo="hello-world",
            title="Draft PR",
            body="",
            head="feature",
            base="main",
            draft=True,
        )
        result = api.create_pull_request(params)

        assert result["number"] == 1


# ---------------------------------------------------------------------------
# TestCreateIssue
# ---------------------------------------------------------------------------


class TestCreateIssue:
    """POST /repos/{owner}/{repo}/issues."""

    @responses.activate
    def test_with_labels(self, api: GitHubAPI) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues"
        expected_body: dict[str, Any] = {
            "title": "Bug: null deref",
            "body": "Details here",
            "labels": ["bug", "severity:high", "nit:detected"],
        }
        responses.add(
            responses.POST,
            url,
            json={"number": 7, "html_url": "https://github.com/octocat/hello-world/issues/7"},
            status=201,
            match=[
                matchers.header_matcher(_EXPECTED_HEADERS),
                matchers.json_params_matcher(expected_body),
            ],
        )

        result = api.create_issue(
            "octocat",
            "hello-world",
            "Bug: null deref",
            "Details here",
            labels=["bug", "severity:high", "nit:detected"],
        )

        assert result["number"] == 7

    @responses.activate
    def test_without_labels(self, api: GitHubAPI) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues"
        # Body should NOT contain "labels" key
        expected_body: dict[str, Any] = {
            "title": "Bug",
            "body": "desc",
        }
        responses.add(
            responses.POST,
            url,
            json={"number": 8},
            status=201,
            match=[matchers.json_params_matcher(expected_body)],
        )

        result = api.create_issue("octocat", "hello-world", "Bug", "desc")

        assert result["number"] == 8

    @responses.activate
    def test_empty_labels_not_sent(self, api: GitHubAPI) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues"
        # Empty list is falsy, so "labels" should be absent
        expected_body: dict[str, Any] = {
            "title": "Bug",
            "body": "desc",
        }
        responses.add(
            responses.POST,
            url,
            json={"number": 9},
            status=201,
            match=[matchers.json_params_matcher(expected_body)],
        )

        result = api.create_issue("octocat", "hello-world", "Bug", "desc", labels=[])

        assert result["number"] == 9


# ---------------------------------------------------------------------------
# TestCreateIssueComment
# ---------------------------------------------------------------------------


class TestCreateIssueComment:
    """POST /repos/{owner}/{repo}/issues/{issue_number}/comments."""

    @responses.activate
    def test_url_uses_issue_number(self, api: GitHubAPI) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues/7/comments"
        responses.add(
            responses.POST,
            url,
            json={"id": 10, "body": "Linked to PR #42"},
            status=201,
            match=[
                matchers.header_matcher(_EXPECTED_HEADERS),
                matchers.json_params_matcher({"body": "Linked to PR #42"}),
            ],
        )

        result = api.create_issue_comment("octocat", "hello-world", 7, "Linked to PR #42")

        assert result["id"] == 10
        assert "/issues/7/comments" in _req_url(responses.calls[0])


# ---------------------------------------------------------------------------
# TestHTTPErrors
# ---------------------------------------------------------------------------


class TestHTTPErrors:
    """Error handling for 4xx, 5xx, and network failures."""

    @responses.activate
    def test_get_404(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"
        responses.add(
            responses.GET,
            url,
            json={"message": "Not Found"},
            status=404,
        )

        with pytest.raises(GitHubAPIError, match="GitHub API error 404"):
            api.find_comment_by_marker(pr_info, "<!-- nit -->")

    @responses.activate
    def test_post_422_validation(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"
        responses.add(
            responses.POST,
            url,
            json={
                "message": "Validation Failed",
                "errors": [{"resource": "IssueComment", "code": "missing_field", "field": "body"}],
            },
            status=422,
        )

        with pytest.raises(GitHubAPIError, match="GitHub API error 422"):
            api.create_comment(pr_info, "")

    @responses.activate
    def test_patch_403_forbidden(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues/comments/1"
        responses.add(
            responses.PATCH,
            url,
            json={"message": "Resource not accessible by integration"},
            status=403,
        )

        with pytest.raises(GitHubAPIError, match="GitHub API error 403"):
            api.update_comment(pr_info, 1, "Updated")

    @responses.activate
    def test_post_500_server_error(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"
        responses.add(
            responses.POST,
            url,
            json={"message": "Internal Server Error"},
            status=500,
        )

        with pytest.raises(GitHubAPIError, match="GitHub API error 500"):
            api.create_comment(pr_info, "test")

    @responses.activate
    def test_connection_error(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"
        responses.add(
            responses.GET,
            url,
            body=ConnectionError("DNS resolution failed"),
        )

        with pytest.raises(GitHubAPIError, match="GET request failed"):
            api.find_comment_by_marker(pr_info, "<!-- nit -->")

    @responses.activate
    def test_timeout_error(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"
        responses.add(
            responses.POST,
            url,
            body=_requests.exceptions.Timeout("Read timed out"),
        )

        with pytest.raises(GitHubAPIError, match="POST request failed"):
            api.create_comment(pr_info, "test")


# ---------------------------------------------------------------------------
# TestHeaders
# ---------------------------------------------------------------------------


class TestHeaders:
    """Verify all three required headers are sent for every HTTP method."""

    @responses.activate
    def test_get_sends_required_headers(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"
        responses.add(
            responses.GET,
            url,
            json=[],
            status=200,
            match=[matchers.header_matcher(_EXPECTED_HEADERS)],
        )

        api.find_comment_by_marker(pr_info, "<!-- nit -->")

        # If headers didn't match, responses would have raised ConnectionError
        assert len(responses.calls) == 1

    @responses.activate
    def test_post_sends_required_headers(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"
        responses.add(
            responses.POST,
            url,
            json=_COMMENT_RESPONSE,
            status=201,
            match=[matchers.header_matcher(_EXPECTED_HEADERS)],
        )

        api.create_comment(pr_info, "test")

        assert len(responses.calls) == 1

    @responses.activate
    def test_patch_sends_required_headers(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues/comments/1"
        responses.add(
            responses.PATCH,
            url,
            json=_COMMENT_RESPONSE,
            status=200,
            match=[matchers.header_matcher(_EXPECTED_HEADERS)],
        )

        api.update_comment(pr_info, 1, "test")

        assert len(responses.calls) == 1

    @responses.activate
    def test_post_sets_json_content_type(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"
        responses.add(responses.POST, url, json=_COMMENT_RESPONSE, status=201)

        api.create_comment(pr_info, "test")

        content_type = responses.calls[0].request.headers["Content-Type"]
        assert "application/json" in content_type

    @responses.activate
    def test_patch_sets_json_content_type(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues/comments/1"
        responses.add(responses.PATCH, url, json=_COMMENT_RESPONSE, status=200)

        api.update_comment(pr_info, 1, "test")

        content_type = responses.calls[0].request.headers["Content-Type"]
        assert "application/json" in content_type


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """URL construction edge cases and API-specific scenarios."""

    @responses.activate
    def test_owner_with_hyphens_and_dots(self, api: GitHubAPI) -> None:
        url = f"{_BASE}/repos/my-org/my.repo.name/issues"
        responses.add(responses.POST, url, json={"number": 1}, status=201)

        result = api.create_issue("my-org", "my.repo.name", "title", "body")

        assert result["number"] == 1
        assert "/repos/my-org/my.repo.name/" in _req_url(responses.calls[0])

    @responses.activate
    def test_large_pr_number(self, api: GitHubAPI) -> None:
        pr = GitHubPRInfo(owner="octocat", repo="hello-world", pr_number=999999)
        url = f"{_BASE}/repos/octocat/hello-world/issues/999999/comments"
        responses.add(responses.GET, url, json=[], status=200)

        api.find_comment_by_marker(pr, "<!-- nit -->")

        assert "/issues/999999/comments" in _req_url(responses.calls[0])

    @responses.activate
    def test_rate_limit_response(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"
        responses.add(
            responses.GET,
            url,
            json={"message": "API rate limit exceeded"},
            status=403,
            headers={
                "X-RateLimit-Remaining": "0",
                "Retry-After": "60",
            },
        )

        with pytest.raises(GitHubAPIError, match="GitHub API error 403"):
            api.find_comment_by_marker(pr_info, "<!-- nit -->")

    @responses.activate
    def test_empty_json_response(self, api: GitHubAPI, pr_info: GitHubPRInfo) -> None:
        url = f"{_BASE}/repos/octocat/hello-world/issues/42/comments"
        responses.add(responses.POST, url, json={}, status=201)

        result = api.create_comment(pr_info, "test")

        assert result == {}
