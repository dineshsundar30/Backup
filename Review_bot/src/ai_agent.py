import json
import requests
from typing import List, Dict, Any, Optional
from src.models import ReviewResult, ReviewIssue, FileDiff, Category, Severity
from src.rf_analyzer import RobotFrameworkAnalyzer

class AICodeReviewerAgent:
    """Multi-provider AI Code Reviewer Agent for Robot Framework & GitLab MRs."""

    SYSTEM_PROMPT = """
You are an expert Principal QA Automation Engineer and Code Reviewer specializing in Robot Framework, HMI (In-Vehicle Infotainment / Touchscreen UI) test automation, Appium, Selenium, and Python.

Your task is to conduct a thorough code review of code changes (diffs or full files) provided in a Merge Request.

Review Guidelines for Robot Framework & HMI Automation:
1. HMI Timing & Flakiness: Identify hardcoded `Sleep` statements. Recommend dynamic waits (`Wait Until Element Is Visible`, `Wait Until Page Contains Element`, etc.).
2. Locators: Check for fragile index-based XPaths (e.g. `//div[3]/button[2]`). Recommend accessibility IDs, resource IDs, or Page Object pattern variables.
3. Test Lifecycle & Reliability: Ensure `Suite Setup`, `Suite Teardown`, `Test Setup`, and `Test Teardown` handle app initialization, device recovery, and screenshot on failure.
4. Test Metadata: Verify presence of `[Documentation]` and `[Tags]` (e.g. HMI, Sanity, Smoke).
5. Code Correctness & Edge Cases: Identify syntax errors, invalid keyword arguments, unhandled exceptions, and missing teardown assertions.
6. Maintainability: Check keyword modularity, code reuse, and parameterization.

Output Format Requirement:
You MUST respond strictly with a valid JSON object adhering to this structure:
{
  "overall_score": 85, // integer 0 to 100
  "verdict": "NEEDS_WORK", // "PASSED", "NEEDS_WORK", or "REJECTED"
  "summary": "High-level review summary markdown paragraph...",
  "issues": [
    {
      "category": "HMI Wait / Timing", // Choose from: "HMI Wait / Timing", "Locator Quality", "Suite Setup / Teardown", "Tags & Documentation", "RF Formatting & Style", "Logic & Error Handling", "Security & Secrets", "Maintainability & Reusability"
      "severity": "MAJOR", // "CRITICAL", "MAJOR", "MINOR", "INFO"
      "file_path": "path/to/file.robot",
      "line_number": 42, // integer or null if general
      "title": "Short descriptive issue title",
      "description": "Detailed explanation of why this is a problem in HMI automation.",
      "recommendation": "Concrete action step for developer to resolve it.",
      "suggested_fix": "# Code snippet fix",
      "code_snippet": "Original code line or block"
    }
  ]
}
"""

    def __init__(
        self,
        provider: str = "openai",
        model: str = "gpt-4o-mini",
        openai_api_key: str = "",
        gemini_api_key: str = "",
        ollama_base_url: str = "http://localhost:11434",
        ollama_api_key: str = "",
        groq_api_key: str = ""
    ):
        self.provider = provider.lower()
        self.model = model
        self.openai_api_key = openai_api_key
        self.gemini_api_key = gemini_api_key
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.ollama_api_key = ollama_api_key
        self.groq_api_key = groq_api_key
        self.rf_analyzer = RobotFrameworkAnalyzer()

    def review_diffs(self, file_diffs: List[FileDiff], mr_title: str = "", mr_desc: str = "") -> ReviewResult:
        """Combine static analysis and LLM analysis to produce a complete ReviewResult."""
        static_issues: List[ReviewIssue] = []

        # 1. Perform static analysis on Robot Framework files
        for fdiff in file_diffs:
            file_path = fdiff.new_path or fdiff.old_path
            if fdiff.is_robot_framework and fdiff.diff:
                # Run static analyzer on changed diff content
                s_issues = self.rf_analyzer.analyze_content(file_path, fdiff.diff)
                static_issues.extend(s_issues)

        # 2. Check if LLM integration is disabled / Static-Laya mode selected
        if self.provider in ("none", "static", "laya", "disabled"):
            all_issues = static_issues
            criticals = sum(1 for i in all_issues if i.severity == Severity.CRITICAL)
            majors = sum(1 for i in all_issues if i.severity == Severity.MAJOR)

            score = max(0, 100 - (criticals * 30 + majors * 15 + len(all_issues) * 5))
            verdict = "PASSED" if score >= 85 else ("NEEDS_WORK" if score >= 60 else "REJECTED")

            summary_msg = (
                f"**Review Engine:** Static Rules & Laya Engine (LLM Integration Disabled)\n\n"
                f"Analyzed {len(file_diffs)} modified files. "
                f"Found {len(static_issues)} rule findings across HMI wait timing, locators, tags, and lifecycle setups."
            )

            return ReviewResult(
                overall_score=score,
                verdict=verdict,
                summary=summary_msg,
                issues=static_issues,
                files_reviewed_count=len(file_diffs)
            )

        # 3. Prepare payload for LLM analysis
        prompt_content = f"Merge Request Title: {mr_title}\nMerge Request Description: {mr_desc}\n\nChanged Files & Diffs:\n"
        for idx, fdiff in enumerate(file_diffs, start=1):
            path = fdiff.new_path or fdiff.old_path
            prompt_content += f"\n--- File {idx}/{len(file_diffs)}: {path} ---\n{fdiff.diff}\n"

        # 4. Request LLM Analysis
        try:
            llm_response = self._call_llm_provider(prompt_content)
            parsed_data = self._parse_json_response(llm_response)
        except Exception as e:
            # Fallback if LLM fails or is unconfigured: return static analysis results with warning summary
            all_issues = static_issues
            criticals = sum(1 for i in all_issues if i.severity == Severity.CRITICAL)
            majors = sum(1 for i in all_issues if i.severity == Severity.MAJOR)

            score = max(0, 100 - (criticals * 30 + majors * 15 + len(all_issues) * 5))
            verdict = "PASSED" if score >= 85 else ("NEEDS_WORK" if score >= 60 else "REJECTED")

            return ReviewResult(
                overall_score=score,
                verdict=verdict,
                summary=f"**Note:** AI LLM evaluation encountered an error ({str(e)}). Displaying static analysis checks.\n\n"
                        f"Found {len(static_issues)} static code analysis rule findings.",
                issues=static_issues,
                files_reviewed_count=len(file_diffs)
            )

        # Combine static issues and LLM issues (deduplicate if necessary)
        llm_issues: List[ReviewIssue] = []
        for raw_issue in parsed_data.get("issues", []):
            try:
                cat_str = raw_issue.get("category", Category.MAINTAINABILITY)
                # Map category string to Category enum or fallback
                cat = Category.MAINTAINABILITY
                for c in Category:
                    if c.value.lower() == str(cat_str).lower():
                        cat = c
                        break

                sev_str = raw_issue.get("severity", Severity.MINOR).upper()
                sev = Severity.MINOR
                if sev_str in Severity.__members__:
                    sev = Severity[sev_str]

                llm_issues.append(ReviewIssue(
                    category=cat,
                    severity=sev,
                    file_path=raw_issue.get("file_path", "General"),
                    line_number=raw_issue.get("line_number"),
                    title=raw_issue.get("title", "Issue"),
                    description=raw_issue.get("description", ""),
                    recommendation=raw_issue.get("recommendation", ""),
                    suggested_fix=raw_issue.get("suggested_fix"),
                    code_snippet=raw_issue.get("code_snippet")
                ))
            except Exception:
                continue

        all_issues = static_issues + llm_issues

        return ReviewResult(
            overall_score=parsed_data.get("overall_score", 80),
            verdict=parsed_data.get("verdict", "NEEDS_WORK"),
            summary=parsed_data.get("summary", "Code review completed successfully."),
            issues=all_issues,
            files_reviewed_count=len(file_diffs)
        )

    def _call_llm_provider(self, user_prompt: str) -> str:
        """Route prompt to configured LLM provider (OpenAI, Gemini, Ollama, Groq)."""
        if self.provider == "openai":
            return self._call_openai(user_prompt)
        elif self.provider == "gemini":
            return self._call_gemini(user_prompt)
        elif self.provider == "ollama":
            return self._call_ollama(user_prompt)
        elif self.provider == "groq":
            return self._call_groq(user_prompt)
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def _call_openai(self, user_prompt: str) -> str:
        if not self.openai_api_key:
            raise ValueError("OpenAI API key is missing. Configure it in settings or .env.")
        
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model or "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _call_gemini(self, user_prompt: str) -> str:
        if not self.gemini_api_key:
            raise ValueError("Gemini API key is missing. Configure it in settings or .env.")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model or 'gemini-1.5-flash'}:generateContent?key={self.gemini_api_key}"
        headers = {"Content-Type": "application/json"}
        full_prompt = f"{self.SYSTEM_PROMPT}\n\nUser Code Review Request:\n{user_prompt}\n\nIMPORTANT: Output valid JSON only."
        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}]
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return text

    def _call_ollama(self, user_prompt: str) -> str:
        url = f"{self.ollama_base_url}/api/chat"
        headers = {"Content-Type": "application/json"}
        if self.ollama_api_key:
            headers["Authorization"] = f"Bearer {self.ollama_api_key}"
            headers["x-api-key"] = self.ollama_api_key

        payload = {
            "model": self.model or "qwen2.5-coder",
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "format": "json"
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=90)
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    def _call_groq(self, user_prompt: str) -> str:
        if not self.groq_api_key:
            raise ValueError("Groq API key is missing.")
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model or "llama-3.1-70b-versatile",
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """Extract and parse JSON object from LLM response text."""
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return json.loads(cleaned.strip())
