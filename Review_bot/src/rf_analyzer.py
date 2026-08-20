import re
from typing import List, Dict, Tuple, Optional
from src.models import ReviewIssue, Category, Severity

# XPath extraction: match //... values from within double-quoted strings, single-quoted strings, or bare tokens.
# Strategy: capture everything after // up to a double-quote, whitespace, or end of line.
# This correctly handles //button[@id='ok'] even with embedded single quotes.
_XPATH_EXTRACT = re.compile(
    r"""(?:xpath\s*=\s*)?["']?(\/\/[^\s">\)]+?)(?=\s|"|>|\)|$)""",
    re.IGNORECASE
)
# Robot Framework variable declaration pattern in *** Variables *** section
# e.g.  ${MY_VAR}    value  OR  @{MY_LIST}    item  OR  &{MY_DICT}    key=val
_VAR_DECL_PATTERN = re.compile(
    r"^([\$@&])\{([^}]+)\}\s+", re.IGNORECASE
)
# Naming convention: must be UPPER_SNAKE_CASE (letters, digits, underscores, all uppercase)
_UPPER_SNAKE_CASE = re.compile(r"^[A-Z][A-Z0-9_]*$")

class RobotFrameworkAnalyzer:
    """Specialized static code analyzer for Robot Framework test suites with HMI validation rules."""

    def __init__(self):
        self.sleep_pattern = re.compile(r"^\s*Sleep\s+([0-9\.]+s?|[0-9]+)", re.IGNORECASE)
        self.fragile_xpath_pattern = re.compile(
            r"xpath=\/\/[a-zA-Z0-9_\-\*]*(\/div|\/span|\/button|\/input)\[\d+\]", re.IGNORECASE
        )
        self.test_header_pattern = re.compile(r"^\*{3}\s*Test Cases?\s*\*{3}", re.IGNORECASE)
        self.settings_header_pattern = re.compile(r"^\*{3}\s*Settings?\s*\*{3}", re.IGNORECASE)
        self.variables_header_pattern = re.compile(r"^\*{3}\s*Variables?\s*\*{3}", re.IGNORECASE)
        self.suite_setup_pattern = re.compile(r"^\s*Suite Setup\s+", re.IGNORECASE)
        self.suite_teardown_pattern = re.compile(r"^\s*Suite Teardown\s+", re.IGNORECASE)
        self.doc_pattern = re.compile(r"^\s*\[Documentation\]", re.IGNORECASE)
        self.tags_pattern = re.compile(r"^\s*\[Tags\]", re.IGNORECASE)

    # ------------------------------------------------------------------
    # Project-wide registry building
    # ------------------------------------------------------------------

    def build_project_registry(
        self, project_files: Dict[str, str]
    ) -> Tuple[Dict[str, List[Tuple[str, int]]], Dict[str, List[Tuple[str, int]]]]:
        """
        Parse all project files and return two registries:
          - xpath_registry:    {xpath_string: [(file_path, line_number), ...]}
          - variable_registry: {var_name:     [(file_path, line_number), ...]}
        """
        xpath_registry: Dict[str, List[Tuple[str, int]]] = {}
        variable_registry: Dict[str, List[Tuple[str, int]]] = {}

        for file_path, content in project_files.items():
            in_variables = False
            for line_idx, raw_line in enumerate(content.splitlines(), start=1):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue

                # Track section headers
                if self.variables_header_pattern.search(line):
                    in_variables = True
                    continue
                elif line.startswith("***"):
                    in_variables = False
                    continue

                # Collect xpaths from any line
                for m in _XPATH_EXTRACT.finditer(raw_line):
                    xpath_val = m.group(1).strip()
                    xpath_registry.setdefault(xpath_val, []).append((file_path, line_idx))

                # Collect variable declarations only from Variables section
                if in_variables:
                    vm = _VAR_DECL_PATTERN.match(raw_line.lstrip())
                    if vm:
                        var_name = vm.group(2).strip()
                        variable_registry.setdefault(var_name, []).append((file_path, line_idx))

        return xpath_registry, variable_registry

    # ------------------------------------------------------------------
    # Core single-file analysis (no cross-project context)
    # ------------------------------------------------------------------

    def analyze_content(self, file_path: str, content: str) -> List[ReviewIssue]:
        """Analyse a single file/diff without cross-project context."""
        return self._analyze(file_path, content, xpath_registry={}, variable_registry={})

    # ------------------------------------------------------------------
    # Context-aware analysis (with cross-project registry)
    # ------------------------------------------------------------------

    def analyze_content_with_context(
        self,
        file_path: str,
        content: str,
        xpath_registry: Dict[str, List[Tuple[str, int]]],
        variable_registry: Dict[str, List[Tuple[str, int]]],
    ) -> List[ReviewIssue]:
        """Analyse a file/diff and cross-check against full-project registries."""
        return self._analyze(file_path, content, xpath_registry, variable_registry)

    # ------------------------------------------------------------------
    # Internal analysis engine
    # ------------------------------------------------------------------

    def _analyze(
        self,
        file_path: str,
        content: str,
        xpath_registry: Dict[str, List[Tuple[str, int]]],
        variable_registry: Dict[str, List[Tuple[str, int]]],
    ) -> List[ReviewIssue]:
        issues: List[ReviewIssue] = []
        lines = content.splitlines()

        is_hlk = "hlk" in file_path.lower()

        has_settings = False
        has_suite_setup = False
        has_suite_teardown = False
        in_test_cases = False
        in_variables = False
        current_test_name: Optional[str] = None
        test_has_tags = False
        test_has_doc = False
        test_start_line = 0

        # For variable order check in the Variables section
        prev_var_name: Optional[str] = None
        prev_var_line = 0

        for line_idx, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()

            if not line or line.startswith("#"):
                continue

            # ── Section headers ──────────────────────────────────────
            if self.settings_header_pattern.search(line):
                has_settings = True
                in_test_cases = False
                in_variables = False
                prev_var_name = None
                continue
            elif self.test_header_pattern.search(line):
                in_test_cases = True
                in_variables = False
                prev_var_name = None
                continue
            elif self.variables_header_pattern.search(line):
                in_variables = True
                in_test_cases = False
                prev_var_name = None
                continue
            elif line.startswith("***"):
                in_test_cases = False
                in_variables = False
                prev_var_name = None
                continue

            # ── Settings section ─────────────────────────────────────
            if has_settings and not in_test_cases and not in_variables:
                if self.suite_setup_pattern.search(raw_line):
                    has_suite_setup = True
                if self.suite_teardown_pattern.search(raw_line):
                    has_suite_teardown = True

            # ── Variables section checks ─────────────────────────────
            if in_variables:
                vm = _VAR_DECL_PATTERN.match(raw_line.lstrip())
                if vm:
                    sigil = vm.group(1)          # $, @, &
                    var_name = vm.group(2).strip()

                    # Rule: Naming convention – UPPER_SNAKE_CASE
                    if not _UPPER_SNAKE_CASE.match(var_name):
                        sigil_full = {"$": "${}", "@": "@{}", "&": "&{}"}.get(sigil, "${}")
                        issues.append(ReviewIssue(
                            category=Category.VARIABLE_NAMING,
                            severity=Severity.MINOR,
                            file_path=file_path,
                            line_number=line_idx,
                            title=f"Variable '{sigil}{{{var_name}}}' violates naming convention",
                            description=(
                                f"Variable `{sigil}{{{var_name}}}` does not follow Robot Framework naming convention. "
                                f"Scalar `${{VAR}}`, list `@{{LIST}}`, and dict `&{{DICT}}` names must be "
                                f"`UPPER_SNAKE_CASE` (uppercase letters, digits, underscores only)."
                            ),
                            recommendation=f"Rename to `{sigil}{{{var_name.upper().replace(' ', '_')}}}` and update all usages.",
                            code_snippet=raw_line
                        ))

                    # Rule: Alphabetical order
                    if prev_var_name is not None:
                        if var_name.lower() < prev_var_name.lower():
                            issues.append(ReviewIssue(
                                category=Category.VARIABLE_ORDER,
                                severity=Severity.MINOR,
                                file_path=file_path,
                                line_number=line_idx,
                                title=f"Variable '{sigil}{{{var_name}}}' is out of alphabetical order",
                                description=(
                                    f"`{sigil}{{{var_name}}}` (line {line_idx}) appears after "
                                    f"`{prev_var_name}` (line {prev_var_line}) but comes before it alphabetically. "
                                    f"Variables in the `*** Variables ***` section should be declared in A-Z order."
                                ),
                                recommendation="Sort the Variables section entries alphabetically for maintainability.",
                                code_snippet=raw_line
                            ))
                    prev_var_name = var_name
                    prev_var_line = line_idx

                    # Project-wide duplicate variable check
                    if variable_registry.get(var_name):
                        for existing_file, existing_line in variable_registry[var_name]:
                            if existing_file != file_path:
                                issues.append(ReviewIssue(
                                    category=Category.VARIABLE_NAMING,
                                    severity=Severity.MINOR,
                                    file_path=file_path,
                                    line_number=line_idx,
                                    title=f"Variable '{sigil}{{{var_name}}}' already declared in project",
                                    description=(
                                        f"`{sigil}{{{var_name}}}` is declared here but is also declared in "
                                        f"`{existing_file}` (line {existing_line}). "
                                        f"Duplicate variable names across files can cause shadowing and confusion."
                                    ),
                                    recommendation=(
                                        "Move shared variables to a common resource file and import it, "
                                        "or rename to be file-specific."
                                    ),
                                    code_snippet=raw_line
                                ))
                                break  # Report once per variable

            # ── Test Cases section ───────────────────────────────────
            if in_test_cases:
                if raw_line and not raw_line[0].isspace() and not line.startswith("["):
                    # Wrap up previous test
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
                        # [Documentation] required only for HLK files
                        if not test_has_doc and is_hlk:
                            issues.append(ReviewIssue(
                                category=Category.TAGS_DOCS,
                                severity=Severity.INFO,
                                file_path=file_path,
                                line_number=test_start_line,
                                title=f"Missing [Documentation] in HLK Test Case '{current_test_name}'",
                                description=(
                                    f"HLK test case '{current_test_name}' does not have a documentation string. "
                                    f"HLK certification requires documentation for each test step."
                                ),
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

            # ── Rule 1: Hardcoded Sleep ──────────────────────────────
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
                    recommendation="Replace with dynamic sync keywords like `Wait Until Element Is Visible` or `Wait Until Page Contains Element`.",
                    suggested_fix=f"# Replace:\n# {line}\n# With:\nWait Until Element Is Visible    ${{TARGET_ELEMENT}}    timeout=10s",
                    code_snippet=raw_line
                ))

            # ── Rule 2: Fragile Index-Based XPath ────────────────────
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

            # ── Rule 3: Tab Character Formatting ─────────────────────
            if "\t" in raw_line:
                issues.append(ReviewIssue(
                    category=Category.CODE_STYLE,
                    severity=Severity.INFO,
                    file_path=file_path,
                    line_number=line_idx,
                    title="Tab Character Used for Indentation",
                    description="Robot Framework standard style recommends 4 spaces instead of tabs.",
                    recommendation="Replace tab characters with 4 spaces.",
                    code_snippet=raw_line
                ))

            # ── Rule 4: Cross-Project XPath Duplication ──────────────
            if xpath_registry:
                for xm in _XPATH_EXTRACT.finditer(raw_line):
                    xpath_val = xm.group(1).strip()
                    existing_refs = xpath_registry.get(xpath_val, [])
                    for existing_file, existing_line in existing_refs:
                        if existing_file != file_path:
                            issues.append(ReviewIssue(
                                category=Category.XPATH_DUPLICATION,
                                severity=Severity.MAJOR,
                                file_path=file_path,
                                line_number=line_idx,
                                title="Repetitive XPath Already Declared in Project",
                                description=(
                                    f"XPath `{xpath_val}` is used here but is already declared in "
                                    f"`{existing_file}` (line {existing_line}). "
                                    f"Duplicating XPaths across files creates maintenance risks."
                                ),
                                recommendation=(
                                    "Move the XPath to a shared resource/page-object file as a variable, "
                                    "then import and reuse it: e.g. `${BTN_SUBMIT}    xpath=//button[@id='submit']`."
                                ),
                                code_snippet=raw_line
                            ))
                            break  # Report once per xpath occurrence

        # ── Final test case wrap-up ──────────────────────────────────
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
            if not test_has_doc and is_hlk:
                issues.append(ReviewIssue(
                    category=Category.TAGS_DOCS,
                    severity=Severity.INFO,
                    file_path=file_path,
                    line_number=test_start_line,
                    title=f"Missing [Documentation] in HLK Test Case '{current_test_name}'",
                    description=(
                        f"HLK test case '{current_test_name}' does not have a documentation string. "
                        f"HLK certification requires documentation for each test step."
                    ),
                    recommendation="Add `[Documentation]  Validates HMI touchscreen response...`."
                ))

        # ── Rule 5: Suite Setup & Teardown ───────────────────────────
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
