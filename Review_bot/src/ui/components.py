import streamlit as st
from src.models import ReviewResult, ReviewIssue, Severity, Category

def render_header():
    """Render application header and subtitle."""
    st.markdown("""
        <div style="background: linear-gradient(135deg, #1e1e2f 0%, #2d2b55 100%); padding: 24px; border-radius: 12px; margin-bottom: 24px; box-shadow: 0 4px 20px rgba(0,0,0,0.3);">
            <h1 style="color: #ffffff; margin: 0; font-size: 2.2rem; font-weight: 700;">🤖 AI Agent Code Reviewer</h1>
            <p style="color: #a0a0c0; margin: 8px 0 0 0; font-size: 1.05rem;">
                Automated Quality & HMI Validation Reviewer for <b>Robot Framework</b> Test Suites & <b>GitLab Merge Requests</b>
            </p>
        </div>
    """, unsafe_allow_html=True)

def render_score_card(result: ReviewResult):
    """Render overall verdict and score metric cards."""
    col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1])

    # Verdict styling
    verdict_colors = {
        "PASSED": "#2ecc71",
        "NEEDS_WORK": "#f39c12",
        "REJECTED": "#e74c3c"
    }
    v_color = verdict_colors.get(result.verdict, "#3498db")

    with col1:
        st.markdown(f"""
            <div style="border-left: 6px solid {v_color}; background-color: rgba(255,255,255,0.05); padding: 16px; border-radius: 8px;">
                <span style="font-size: 0.85rem; text-transform: uppercase; color: #888; font-weight: 600;">Overall Verdict</span>
                <h2 style="color: {v_color}; margin: 4px 0 0 0; font-size: 2rem;">{result.verdict}</h2>
                <span style="font-size: 0.9rem; color: #aaa;">Score: <b>{result.overall_score}/100</b></span>
            </div>
        """, unsafe_allow_html=True)

    with col2:
        st.metric("Critical", result.critical_count, delta=None)
    with col3:
        st.metric("Major", result.major_count, delta=None)
    with col4:
        st.metric("Minor", result.minor_count, delta=None)
    with col5:
        st.metric("Info", result.info_count, delta=None)

def render_issues_list(result: ReviewResult):
    """Render list of identified code review issues grouped by severity."""
    if not result.issues:
        st.success("🎉 No issues identified! The code meets Robot Framework HMI validation standards.")
        return

    st.markdown("### 🔍 Identified Code Review Findings")

    # Filter controls
    severities = [s.value for s in Severity]
    selected_severities = st.multiselect("Filter by Severity:", severities, default=severities)

    filtered_issues = [i for i in result.issues if i.severity.value in selected_severities]

    for idx, issue in enumerate(filtered_issues, start=1):
        sev_badges = {
            Severity.CRITICAL: "🔴 **CRITICAL**",
            Severity.MAJOR: "🟠 **MAJOR**",
            Severity.MINOR: "🟡 **MINOR**",
            Severity.INFO: "🔵 **INFO**",
        }
        badge = sev_badges.get(issue.severity, "⚪ **INFO**")
        line_info = f" (Line {issue.line_number})" if issue.line_number else ""

        with st.expander(f"{badge} | **{issue.file_path}**{line_info} — {issue.title}"):
            st.markdown(f"**Category:** `{issue.category.value if hasattr(issue.category, 'value') else issue.category}`")
            st.markdown(f"**Description:** {issue.description}")
            st.markdown(f"**Recommendation:** {issue.recommendation}")

            if issue.code_snippet:
                st.markdown("**Original Snippet:**")
                st.code(issue.code_snippet, language="robotframework" if issue.file_path.endswith(".robot") else "python")

            if issue.suggested_fix:
                st.markdown("**Suggested Fix:**")
                st.code(issue.suggested_fix, language="robotframework" if issue.file_path.endswith(".robot") else "python")

def generate_gitlab_markdown_report(result: ReviewResult, mr_title: str) -> str:
    """Generate a clean markdown report formatted for GitLab MR notes."""
    report = f"## 🤖 AI Agent Code Review Report\n\n"
    report += f"**Overall Verdict:** `{result.verdict}` | **Score:** `{result.overall_score}/100` | **Files Reviewed:** `{result.files_reviewed_count}`\n\n"
    report += f"### 📊 Issue Summary\n"
    report += f"- 🔴 **Critical:** {result.critical_count}\n"
    report += f"- 🟠 **Major:** {result.major_count}\n"
    report += f"- 🟡 **Minor:** {result.minor_count}\n"
    report += f"- 🔵 **Info:** {result.info_count}\n\n"

    report += f"### 📝 Executive Summary\n{result.summary}\n\n"

    if result.issues:
        report += f"### 🔍 Detailed Findings\n"
        for issue in result.issues:
            line_str = f" Line `{issue.line_number}`" if issue.line_number else ""
            report += f"#### [{issue.severity.value}] `{issue.file_path}`{line_str}: {issue.title}\n"
            report += f"- **Category:** {issue.category.value if hasattr(issue.category, 'value') else issue.category}\n"
            report += f"- **Explanation:** {issue.description}\n"
            report += f"- **Recommendation:** {issue.recommendation}\n"
            if issue.suggested_fix:
                report += f"```robotframework\n{issue.suggested_fix}\n```\n"
            report += "\n---\n"

    report += "\n*Generated by AI Agent Code Reviewer for Robot Framework & GitLab MRs.*"
    return report
