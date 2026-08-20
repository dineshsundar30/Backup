import re
from typing import List
from src.models import ReviewIssue, Category, Severity

class RobotFrameworkAnalyzer:
    """Specialized static code analyzer for Robot Framework test suites with HMI validation rules."""

    def __init__(self):
        # Regex patterns for static analysis
        self.sleep_pattern = re.compile(r"^\s*Sleep\s+([0-9\.]+s?|[0-9]+)", re.IGNORECASE)
        self.fragile_xpath_pattern = re.compile(r"xpath=\/\/[a-zA-Z0-9_\-\*]*(\/div|\/span|\/button|\/input)\[\d+\]", re.IGNORECASE)
        self.hardcoded_text_locator = re.compile(r"['\"](?:\/\/[^'\"]+|xpath=[^'\"]+)['\"]")
        self.test_header_pattern = re.compile(r"^\*{3}\s*Test Cases?\s*\*{3}", re.IGNORECASE)
        self.settings_header_pattern = re.compile(r"^\*{3}\s*Settings?\s*\*{3}", re.IGNORECASE)
        self.suite_setup_pattern = re.compile(r"^\s*Suite Setup\s+", re.IGNORECASE)
        self.suite_teardown_pattern = re.compile(r"^\s*Suite Teardown\s+", re.IGNORECASE)
        self.doc_pattern = re.compile(r"^\s*\[Documentation\]", re.IGNORECASE)
        self.tags_pattern = re.compile(r"^\s*\[Tags\]", re.IGNORECASE)

    def analyze_content(self, file_path: str, content: str) -> List[ReviewIssue]:
        """Analyze full content of a .robot or .resource file and return identified issues."""
        issues: List[ReviewIssue] = []
        lines = content.splitlines()

        has_settings = False
        has_suite_setup = False
        has_suite_teardown = False
        in_test_cases = False
        current_test_name = None
        test_has_tags = False
        test_has_doc = False
        test_start_line = 0

        for line_idx, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue

            # Check headers
            if self.settings_header_pattern.search(line):
                has_settings = True
                in_test_cases = False
                continue
            elif self.test_header_pattern.search(line):
                in_test_cases = True
                continue
            elif line.startswith("***"):
                in_test_cases = False
                continue

            # Check Suite Setup & Teardown in Settings
            if has_settings and not in_test_cases:
                if self.suite_setup_pattern.search(raw_line):
                    has_suite_setup = True
                if self.suite_teardown_pattern.search(raw_line):
                    has_suite_teardown = True

            # Analyze Test Case section
            if in_test_cases:
                # Test Case Title line (no indentation at start of line)
                if raw_line and not raw_line[0].isspace() and not line.startswith("["):
                    # Wrap up previous test case check
                    if current_test_name:
                        if not test_has_tags:
                            issues.append(ReviewIssue(
                                category=Category.TAGS_DOCS,
                                severity=Severity.INFO,
                                file_path=file_path,
                                line_number=test_start_line,
                                title=f"Missing [Tags] in Test Case '{current_test_name}'",
                                description=f"Test case '{current_test_name}' lacks categorical tags (e.g. HMI, Sanity, Regression).",
                                recommendation="Add `[Tags]  HMI  Sanity` under test header for better test execution filtering."
                            ))
                        if not test_has_doc:
                            issues.append(ReviewIssue(
                                category=Category.TAGS_DOCS,
                                severity=Severity.INFO,
                                file_path=file_path,
                                line_number=test_start_line,
                                title=f"Missing [Documentation] in Test Case '{current_test_name}'",
                                description=f"Test case '{current_test_name}' does not have a documentation string explaining its goal.",
                                recommendation="Add `[Documentation]  Validates HMI touchscreen response...`."
                            ))
                    current_test_name = line
                    test_start_line = line_idx
                    test_has_tags = False
                    test_has_doc = False

                if self.tags_pattern.search(line):
                    test_has_tags = True
                if self.doc_pattern.search(line):
                    test_has_doc = True

            # Rule 1: Hardcoded Sleep Detection (HMI Timing Issue)
            sleep_match = self.sleep_pattern.search(line)
            if sleep_match:
                sleep_val = sleep_match.group(1)
                issues.append(ReviewIssue(
                    category=Category.HMI_WAIT,
                    severity=Severity.MAJOR,
                    file_path=file_path,
                    line_number=line_idx,
                    title="Hardcoded 'Sleep' Statement Detected",
                    description=f"Found explicit `Sleep {sleep_val}`. Hardcoded sleeps lead to flaky, slow HMI tests.",
                    recommendation="Replace with dynamic sync keywords like `Wait Until Element Is Visible`, `Wait Until Page Contains Element`, or `Wait Until HMI Screen Loaded`.",
                    suggested_fix=f"# Replace:\n# {line}\n# With:\nWait Until Element Is Visible    ${{TARGET_ELEMENT}}    timeout=10s",
                    code_snippet=raw_line
                ))

            # Rule 2: Fragile Index-Based XPath Locators
            if self.fragile_xpath_pattern.search(line):
                issues.append(ReviewIssue(
                    category=Category.LOCATOR_QUALITY,
                    severity=Severity.MAJOR,
                    file_path=file_path,
                    line_number=line_idx,
                    title="Fragile Index-Based XPath Locator",
                    description="Locator uses indexed position paths (e.g., //div[3]/button[1]), which break easily when HMI layout updates.",
                    recommendation="Use unique accessibility IDs, resource IDs, or text attributes instead of array index paths.",
                    suggested_fix="Define locator in Page Object: `${BTN_SUBMIT}    id=com.hmi.app:id/btn_submit`",
                    code_snippet=raw_line
                ))

            # Rule 3: Formatting / Tab Usage
            if "\t" in raw_line:
                issues.append(ReviewIssue(
                    category=Category.CODE_STYLE,
                    severity=Severity.INFO,
                    file_path=file_path,
                    line_number=line_idx,
                    title="Tab Character Used for Indentation",
                    description="Robot Framework standard style recommends 4 spaces instead of tabs for step spacing.",
                    recommendation="Replace tab characters with 4 spaces.",
                    code_snippet=raw_line
                ))

        # Check last test case tags/doc
        if current_test_name:
            if not test_has_tags:
                issues.append(ReviewIssue(
                    category=Category.TAGS_DOCS,
                    severity=Severity.INFO,
                    file_path=file_path,
                    line_number=test_start_line,
                    title=f"Missing [Tags] in Test Case '{current_test_name}'",
                    description=f"Test case '{current_test_name}' lacks categorical tags.",
                    recommendation="Add `[Tags]  HMI  Sanity`."
                ))

        # Rule 4: Suite Setup & Teardown Verification
        if file_path.endswith(".robot") and has_settings:
            if not has_suite_setup:
                issues.append(ReviewIssue(
                    category=Category.LIFECYCLE,
                    severity=Severity.MINOR,
                    file_path=file_path,
                    line_number=1,
                    title="Missing 'Suite Setup' in Settings",
                    description="Suite does not declare a `Suite Setup` to launch application or establish HMI connection.",
                    recommendation="Add `Suite Setup  Initialize HMI Automation Session` in `*** Settings ***`."
                ))
            if not has_suite_teardown:
                issues.append(ReviewIssue(
                    category=Category.LIFECYCLE,
                    severity=Severity.MINOR,
                    file_path=file_path,
                    line_number=1,
                    title="Missing 'Suite Teardown' in Settings",
                    description="Suite does not declare a `Suite Teardown` to close application or clean state on completion.",
                    recommendation="Add `Suite Teardown  Close HMI Automation Session` in `*** Settings ***`."
                ))

        return issues
