import streamlit as st

def render_rules_tab():
    st.subheader("🤖 Robot Framework HMI Quality Rules & Guidelines")
    st.markdown("Overview of static and LLM analysis rules enforced by the AI Code Reviewer.")

    rules = [
        {
            "id": "RF-HMI-001",
            "name": "Hardcoded Sleep Prohibition",
            "severity": "MAJOR",
            "category": "HMI Wait / Timing",
            "desc": "Detects `Sleep  5s`. In HMI automation, fixed sleeps cause slow, flaky executions.",
            "remedy": "Use dynamic wait keywords: `Wait Until Element Is Visible`, `Wait Until Page Contains Element`, or `Wait Until Keyword Succeeds`."
        },
        {
            "id": "RF-HMI-002",
            "name": "Fragile Index-Based XPath Locators",
            "severity": "MAJOR",
            "category": "Locator Quality",
            "desc": "Flags locators relying on array indices like `//div[3]/button[2]`. These break whenever HMI layouts are modified.",
            "remedy": "Use unique accessibility IDs, resource IDs (`id=com.hmi:id/btn`), or text attributes in Page Object files."
        },
        {
            "id": "RF-HMI-003",
            "name": "Suite Setup & Teardown Verification",
            "severity": "MINOR",
            "category": "Suite Setup / Teardown",
            "desc": "Verifies that `.robot` test suites define `Suite Setup` and `Suite Teardown` in `*** Settings ***`.",
            "remedy": "Include setup/teardown for launching HMI session, driver instantiation, and screenshot capture on failure."
        },
        {
            "id": "RF-HMI-004",
            "name": "Test Tags & Documentation Enforcement",
            "severity": "INFO",
            "category": "Tags & Documentation",
            "desc": "Ensures every test case includes `[Documentation]` and domain tags like `[Tags]  HMI  Sanity`.",
            "remedy": "Add descriptive metadata to enable test suite filtering during CI/CD execution."
        },
        {
            "id": "RF-HMI-005",
            "name": "Robot Framework Style & Spacing",
            "severity": "INFO",
            "category": "RF Formatting & Style",
            "desc": "Flags tab characters and recommends standard 4-space separation between keywords and arguments.",
            "remedy": "Format `.robot` code with 4-space indentation or run `robotidy`."
        }
    ]

    for rule in rules:
        with st.expander(f"📌 **[{rule['id']}] {rule['name']}** — {rule['severity']}"):
            st.markdown(f"**Category:** `{rule['category']}`")
            st.markdown(f"**Description:** {rule['desc']}")
            st.markdown(f"**Remedy:** {rule['remedy']}")
