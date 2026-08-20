import streamlit as st
from config.settings import settings
from src.models import FileDiff
from src.ai_agent import AICodeReviewerAgent
from src.ui.components import render_score_card, render_issues_list

SAMPLE_ROBOT_CODE = """*** Settings ***
Documentation    HMI Media Player Functional Tests
Library          AppiumLibrary

*** Test Cases ***
Validate Play Pause Button Toggle
    [Tags]    HMI    Media
    Open HMI Application
    # Hardcoded sleep anti-pattern
    Sleep    5s
    # Fragile index-based XPath
    Click Element    xpath=//div[3]/button[2]
    Element Text Should Be    xpath=//div[3]/span[1]    Playing

*** Keywords ***
Open HMI Application
    # Missing Suite Teardown or error handling check
    Log    Launching HMI Media Player
"""

def render_local_tab():
    st.subheader("📝 Local Code Snippet & Diff AI Reviewer")
    st.markdown("Paste Robot Framework test code (`.robot`), resource files (`.resource`), or Python test libraries for instant AI code review.")

    col1, col2 = st.columns([3, 1])
    with col1:
        file_path = st.text_input("File Name / Path:", value="tests/hmi_media_player.robot")
    with col2:
        if st.button("Load Sample Code"):
            st.session_state["code_input"] = SAMPLE_ROBOT_CODE

    code_content = st.text_area(
        "Robot Framework / Python Code Content:",
        value=st.session_state.get("code_input", SAMPLE_ROBOT_CODE),
        height=320
    )

    if st.button("🔍 Review Local Code", type="primary"):
        if not code_content.strip():
            st.error("Please enter or paste code content to review.")
            return

        file_diff = FileDiff(
            old_path="",
            new_path=file_path,
            diff=code_content,
            is_new_file=True
        )

        with st.spinner("Analyzing code against Robot Framework HMI standards..."):
            agent = AICodeReviewerAgent(
                provider=st.session_state.get("llm_provider", settings.LLM_PROVIDER),
                model=st.session_state.get("llm_model", settings.LLM_MODEL),
                openai_api_key=st.session_state.get("openai_api_key", settings.OPENAI_API_KEY),
                gemini_api_key=st.session_state.get("gemini_api_key", settings.GEMINI_API_KEY),
                ollama_base_url=st.session_state.get("ollama_base_url", settings.OLLAMA_BASE_URL),
                ollama_api_key=st.session_state.get("ollama_api_key", settings.OLLAMA_API_KEY),
                groq_api_key=st.session_state.get("groq_api_key", settings.GROQ_API_KEY)
            )

            result = agent.review_diffs([file_diff], mr_title=f"Review for {file_path}", mr_desc="Local snippet analysis")

        # Render Results
        render_score_card(result)

        st.markdown("### 📝 AI Review Summary")
        st.markdown(result.summary)

        render_issues_list(result)
