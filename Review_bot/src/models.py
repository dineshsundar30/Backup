from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum

class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    INFO = "INFO"

class Category(str, Enum):
    HMI_WAIT = "HMI Wait / Timing"
    LOCATOR_QUALITY = "Locator Quality"
    LIFECYCLE = "Suite Setup / Teardown"
    TAGS_DOCS = "Tags & Documentation"
    CODE_STYLE = "RF Formatting & Style"
    LOGIC_CORRECTNESS = "Logic & Error Handling"
    SECURITY = "Security & Secrets"
    MAINTAINABILITY = "Maintainability & Reusability"

@dataclass
class FileDiff:
    """Represents changes in a single file within a Merge Request or commit."""
    old_path: str
    new_path: str
    diff: str
    is_new_file: bool = False
    is_deleted_file: bool = False
    is_renamed_file: bool = False

    @property
    def is_robot_framework(self) -> bool:
        """Check if file is a Robot Framework test suite, resource, or Python library."""
        path = self.new_path or self.old_path
        return path.endswith((".robot", ".resource", ".tsv", ".txt")) or (
            path.endswith(".py") and ("library" in path.lower() or "keywords" in path.lower())
        )

@dataclass
class MRDetails:
    """Represents a GitLab Merge Request."""
    project_id: str
    mr_iid: int
    title: str
    description: str
    author: str
    web_url: str
    source_branch: str
    target_branch: str
    diffs: List[FileDiff] = field(default_factory=list)

@dataclass
class ReviewIssue:
    """Represents a single finding/issue raised during code review."""
    category: Category
    severity: Severity
    file_path: str
    line_number: Optional[int]
    title: str
    description: str
    recommendation: str
    suggested_fix: Optional[str] = None
    code_snippet: Optional[str] = None

@dataclass
class ReviewResult:
    """Represents the complete review analysis result for an MR or code snippet."""
    overall_score: int  # 0 to 100
    verdict: str        # "PASSED", "NEEDS_WORK", "REJECTED"
    summary: str
    issues: List[ReviewIssue] = field(default_factory=list)
    files_reviewed_count: int = 0
    total_additions: int = 0
    total_deletions: int = 0

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.CRITICAL)

    @property
    def major_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.MAJOR)

    @property
    def minor_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.MINOR)

    @property
    def info_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.INFO)
