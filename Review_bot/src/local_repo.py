"""
Local Git Repository Scanner for Review Bot.

Instead of downloading project files via GitLab API every time,
this module uses the local clone at ~/projects/ivi_features to:
  1. Check if the target branch is available
  2. Switch to it and pull the latest
  3. Read .robot / .resource / .tsv files directly from disk
  4. Restore the original branch afterward

Falls back gracefully if the repo or branch isn't available.
"""

import os
import subprocess
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# File extensions considered Robot Framework files
RF_EXTENSIONS = (".robot", ".resource", ".tsv")


class LocalRepoScanner:
    """Scans a local Git repository for Robot Framework project files."""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).expanduser().resolve()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Check if the local repo path exists and is a valid git repo."""
        git_dir = self.repo_path / ".git"
        return self.repo_path.is_dir() and git_dir.is_dir()

    def get_current_branch(self) -> Optional[str]:
        """Return the currently checked-out branch name, or None."""
        ok, stdout = self._git("rev-parse", "--abbrev-ref", "HEAD")
        return stdout.strip() if ok else None

    def has_branch(self, branch: str) -> bool:
        """Check whether the given branch exists locally or as a remote tracking branch."""
        # Check local branches
        ok, stdout = self._git("branch", "--list", branch)
        if ok and stdout.strip():
            return True
        # Check remote tracking branches
        ok, stdout = self._git("branch", "-r", "--list", f"*/{branch}")
        if ok and stdout.strip():
            return True
        return False

    def fetch_and_checkout(self, branch: str) -> bool:
        """
        Fetch latest from remote, then checkout the given branch.
        Returns True on success.
        """
        # Fetch all remote refs first
        self._git("fetch", "--all", "--prune")

        # Try checking out the branch
        ok, _ = self._git("checkout", branch)
        if not ok:
            # Branch might only exist on remote; try creating a tracking branch
            ok, _ = self._git("checkout", "-b", branch, f"origin/{branch}")
            if not ok:
                return False

        # Pull latest changes
        ok, _ = self._git("pull", "--ff-only")
        if not ok:
            # ff-only failed; try a regular pull
            self._git("pull")

        return True

    def scan_project_files(
        self,
        extensions: Tuple[str, ...] = RF_EXTENSIONS,
        max_files: int = 500,
    ) -> Dict[str, str]:
        """
        Walk the repo directory and return {relative_path: file_content}
        for all files matching the given extensions.
        """
        project_files: Dict[str, str] = {}
        count = 0

        for root, _dirs, files in os.walk(self.repo_path):
            # Skip .git directory
            rel_root = Path(root).relative_to(self.repo_path)
            if ".git" in rel_root.parts:
                continue

            for fname in sorted(files):
                if count >= max_files:
                    break
                if any(fname.endswith(ext) for ext in extensions):
                    full_path = Path(root) / fname
                    rel_path = str(full_path.relative_to(self.repo_path))
                    try:
                        content = full_path.read_text(encoding="utf-8", errors="replace")
                        project_files[rel_path] = content
                        count += 1
                    except OSError as exc:
                        logger.warning("Could not read %s: %s", rel_path, exc)

            if count >= max_files:
                break

        return project_files

    def scan_for_branch(
        self,
        target_branch: str,
        on_status: Optional[callable] = None,
    ) -> Tuple[bool, Dict[str, str]]:
        """
        High-level method: attempt to switch to target_branch, scan files,
        then restore the original branch.

        Args:
            target_branch: The branch to scan
            on_status: Optional callback(message: str) for progress updates

        Returns:
            (success: bool, project_files: Dict[str, str])
        """
        if not self.is_available():
            if on_status:
                on_status("❌ Local repo not found, will use API fallback")
            return False, {}

        if on_status:
            on_status(f"📂 Found local repo at `{self.repo_path}`")

        # Remember current branch to restore later
        original_branch = self.get_current_branch()

        if not self.has_branch(target_branch):
            if on_status:
                on_status(f"❌ Branch `{target_branch}` not found locally, will use API fallback")
            return False, {}

        if on_status:
            on_status(f"🔀 Switching to branch `{target_branch}` and pulling latest...")

        try:
            if not self.fetch_and_checkout(target_branch):
                if on_status:
                    on_status(f"❌ Failed to checkout `{target_branch}`, will use API fallback")
                return False, {}

            if on_status:
                on_status("📖 Reading project files from disk...")

            project_files = self.scan_project_files()

            if on_status:
                on_status(f"✅ Read **{len(project_files)}** Robot Framework files from local repo")

            return True, project_files

        finally:
            # Always restore the original branch
            if original_branch and original_branch != target_branch:
                self._git("checkout", original_branch)

    # ------------------------------------------------------------------
    # Git helper
    # ------------------------------------------------------------------

    def _git(self, *args: str) -> Tuple[bool, str]:
        """Run a git command in the repo directory. Returns (success, stdout)."""
        cmd = ["git", "-C", str(self.repo_path)] + list(args)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                logger.debug("git %s failed: %s", " ".join(args), result.stderr.strip())
            return result.returncode == 0, result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("git command failed: %s", exc)
            return False, ""
