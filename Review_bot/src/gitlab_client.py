import re
import urllib.parse
from typing import Optional, List, Dict, Tuple
from src.models import MRDetails, FileDiff

try:
    import gitlab
    HAS_GITLAB_LIB = True
except ImportError:
    HAS_GITLAB_LIB = False

import requests

class GitLabClient:
    """Client for interacting with GitLab REST API to fetch Merge Requests and post review feedback."""

    def __init__(self, gitlab_url: str = "https://gitlab.com", private_token: Optional[str] = None):
        self.gitlab_url = gitlab_url.rstrip("/")
        self.private_token = private_token or ""
        self.gl = None

        if HAS_GITLAB_LIB and self.private_token:
            try:
                self.gl = gitlab.Gitlab(url=self.gitlab_url, private_token=self.private_token)
                self.gl.auth()
            except Exception:
                self.gl = None

    @staticmethod
    def parse_mr_url(url: str) -> Optional[Tuple[str, str, int]]:
        """
        Parse GitLab MR URL and return (base_url, project_path, mr_iid).
        Example: https://gitlabee.dt.renault.com/swlabs/matrix/-/merge_requests/42 -> ('https://gitlabee.dt.renault.com', 'swlabs/matrix', 42)
        """
        pattern = r"(https?://[^/]+)/(.+?)/-/merge_requests/(\d+)"
        match = re.match(pattern, url.strip())
        if match:
            base_url = match.group(1)
            project_path = match.group(2)
            mr_iid = int(match.group(3))
            return base_url, project_path, mr_iid
        return None

    def fetch_mr_details(self, project_identifier: str, mr_iid: int) -> MRDetails:
        """Fetch Merge Request details and file diffs from GitLab API."""
        encoded_project = urllib.parse.quote(project_identifier, safe="")

        headers = {}
        if self.private_token:
            headers["PRIVATE-TOKEN"] = self.private_token

        # 1. Fetch MR Metadata
        mr_url = f"{self.gitlab_url}/api/v4/projects/{encoded_project}/merge_requests/{mr_iid}"
        resp = requests.get(mr_url, headers=headers)
        resp.raise_for_status()
        mr_data = resp.json()

        # 2. Fetch MR Changes/Diffs
        changes_url = f"{mr_url}/changes"
        changes_resp = requests.get(changes_url, headers=headers)
        changes_resp.raise_for_status()
        changes_data = changes_resp.json()

        diffs: List[FileDiff] = []
        for change in changes_data.get("changes", []):
            diffs.append(FileDiff(
                old_path=change.get("old_path", ""),
                new_path=change.get("new_path", ""),
                diff=change.get("diff", ""),
                is_new_file=change.get("new_file", False),
                is_deleted_file=change.get("deleted_file", False),
                is_renamed_file=change.get("renamed_file", False)
            ))

        return MRDetails(
            project_id=str(mr_data.get("project_id", project_identifier)),
            mr_iid=mr_iid,
            title=mr_data.get("title", ""),
            description=mr_data.get("description", "") or "No description provided.",
            author=mr_data.get("author", {}).get("username", "Unknown"),
            web_url=mr_data.get("web_url", ""),
            source_branch=mr_data.get("source_branch", ""),
            target_branch=mr_data.get("target_branch", ""),
            diffs=diffs
        )

    def post_mr_comment(self, project_identifier: str, mr_iid: int, note_markdown: str) -> bool:
        """Post a summary comment note on the GitLab MR."""
        if not self.private_token:
            raise ValueError("GitLab Private Access Token is required to post comments.")

        encoded_project = urllib.parse.quote(project_identifier, safe="")
        notes_url = f"{self.gitlab_url}/api/v4/projects/{encoded_project}/merge_requests/{mr_iid}/notes"
        headers = {"PRIVATE-TOKEN": self.private_token}

        resp = requests.post(notes_url, headers=headers, json={"body": note_markdown})
        resp.raise_for_status()
        return resp.status_code in (200, 201)

    def fetch_project_file_list(
        self,
        project_identifier: str,
        branch: str = "main",
        extensions: tuple = (".robot", ".resource", ".tsv"),
        max_files: int = 500,
    ) -> List[str]:
        """
        Return a list of file paths in the project that match the given extensions.
        Uses the GitLab Repository Tree API (recursive).
        """
        encoded_project = urllib.parse.quote(project_identifier, safe="")
        headers = {}
        if self.private_token:
            headers["PRIVATE-TOKEN"] = self.private_token

        file_paths: List[str] = []
        page = 1
        per_page = 100

        while len(file_paths) < max_files:
            url = (
                f"{self.gitlab_url}/api/v4/projects/{encoded_project}/repository/tree"
                f"?recursive=true&ref={urllib.parse.quote(branch)}&per_page={per_page}&page={page}"
            )
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 404:
                # Branch might be named differently; fall back to listing without ref
                break
            resp.raise_for_status()
            items = resp.json()
            if not items:
                break

            for item in items:
                if item.get("type") == "blob":
                    path = item.get("path", "")
                    if any(path.endswith(ext) for ext in extensions):
                        file_paths.append(path)

            if len(items) < per_page:
                break
            page += 1

        return file_paths[:max_files]

    def fetch_file_content(
        self,
        project_identifier: str,
        file_path: str,
        branch: str = "main",
    ) -> str:
        """
        Fetch raw content of a single file from the repository at the given branch/ref.
        Returns the file content as a string, or empty string on error.
        """
        encoded_project = urllib.parse.quote(project_identifier, safe="")
        encoded_path = urllib.parse.quote(file_path, safe="")
        url = (
            f"{self.gitlab_url}/api/v4/projects/{encoded_project}"
            f"/repository/files/{encoded_path}/raw?ref={urllib.parse.quote(branch)}"
        )
        headers = {}
        if self.private_token:
            headers["PRIVATE-TOKEN"] = self.private_token

        try:
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            return resp.text
        except Exception:
            return ""

