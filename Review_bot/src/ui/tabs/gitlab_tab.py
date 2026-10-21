import streamlit as st
import time
from config.settings import settings
from src.gitlab_client import GitLabClient
from src.ai_agent import AICodeReviewerAgent
from src.rf_analyzer import RobotFrameworkAnalyzer
from src.local_repo import LocalRepoScanner
from src.ui.components import render_score_card, render_issues_list, generate_gitlab_markdown_report

def render_gitlab_tab():
    st.subheader("🦊 GitLab Merge Request AI Reviewer")
    st.markdown("Analyze GitLab MR diffs automatically for **Robot Framework HMI Validation** standards and general code quality.")

    # Form input for MR URL or Project Details
    col1, col2 = st.columns([3, 1])
    with col1:
        mr_url_input = st.text_input(
            "GitLab MR URL:",
            placeholder="e.g. https://gitlab.com/my-org/hmi-tests/-/merge_requests/42",
            help="Full URL to your GitLab merge request."
        )
    with col2:
        gitlab_token = st.text_input(
            "GitLab Access Token:",
            value=settings.GITLAB_TOKEN,
            type="password",
            help="Personal Access Token with api scope."
        )

    st.markdown("---")

    if st.button("🚀 Fetch & Review Merge Request", type="primary"):
        if not mr_url_input:
            st.error("Please enter a valid GitLab Merge Request URL.")
            return

        parsed = GitLabClient.parse_mr_url(mr_url_input)
        if not parsed:
            st.error("Invalid GitLab MR URL format. Expected format: `https://gitlab-host/owner/repo/-/merge_requests/ID`")
            return

        gitlab_base_url, project_identifier, mr_iid = parsed

        with st.spinner(f"Fetching Merge Request #{mr_iid} from {gitlab_base_url}..."):
            try:
                client = GitLabClient(gitlab_url=gitlab_base_url, private_token=gitlab_token)
                mr_details = client.fetch_mr_details(project_identifier, mr_iid)
            except Exception as e:
                st.error(f"Failed to fetch MR from GitLab: {str(e)}")
                return

        # Display MR Summary Header
        st.success(f"Loaded MR #{mr_details.mr_iid}: **{mr_details.title}**")
        st.markdown(
            f"**Author:** `{mr_details.author}` | "
            f"**Branches:** `{mr_details.source_branch}` ➔ `{mr_details.target_branch}` | "
            f"**Changed Files:** `{len(mr_details.diffs)}`"
        )

        if not mr_details.diffs:
            st.warning("No changed files found in this Merge Request.")
            return

        # Filter Robot Framework & Python files
        rf_files = [f for f in mr_details.diffs if f.is_robot_framework]
        st.info(
            f"Identified {len(rf_files)} Robot Framework / Automation test files "
            f"out of {len(mr_details.diffs)} total modified files."
        )

        # ── Build project-wide registry from target branch ────────────────────
        xpath_registry = {}
        variable_registry = {}
        try:
            status_container = st.status("🔍 Analyzing project for cross-file checks...", expanded=True)
            with status_container:
                project_files_content = {}
                used_local = False

                # --- Step 1: Try local repository first ---
                st.write("⏳ Checking local repository...")
                time.sleep(0.2)
                scanner = LocalRepoScanner(settings.LOCAL_REPO_PATH)

                if scanner.is_available():
                    st.write(f"✅ Local repo found at `{settings.LOCAL_REPO_PATH}`")
                    st.write(f"⏳ Checking for branch `{mr_details.target_branch}`...")
                    time.sleep(0.2)

                    if scanner.has_branch(mr_details.target_branch):
                        st.write(f"✅ Branch `{mr_details.target_branch}` is available")
                        st.write("⏳ Pulling latest changes...")
                        time.sleep(0.2)

                        success, project_files_content = scanner.scan_for_branch(
                            mr_details.target_branch
                        )
                        if success:
                            used_local = True
                            st.write(f"✅ Loaded **{len(project_files_content)}** files from local repo")
                        else:
                            st.write("⚠️ Could not read from local repo, switching to API...")
                    else:
                        st.write(f"⚠️ Branch `{mr_details.target_branch}` not found locally, using API fallback...")
                else:
                    st.write("⚠️ Local repo not available, using API fallback...")

                # --- Step 2: Fallback to API if local didn't work ---
                if not used_local:
                    st.write("⏳ Fetching file list via GitLab API...")
                    time.sleep(0.2)
                    project_files_paths = client.fetch_project_file_list(
                        project_identifier,
                        branch=mr_details.target_branch
                    )
                    if project_files_paths:
                        st.write(f"✅ Found **{len(project_files_paths)}** Robot Framework files")
                        st.write("⏳ Downloading file contents...")
                        for fp in project_files_paths:
                            content = client.fetch_file_content(
                                project_identifier, fp, branch=mr_details.target_branch
                            )
                            if content:
                                project_files_content[fp] = content

                # --- Step 3: Build registries ---
                if project_files_content:
                    analyzer = RobotFrameworkAnalyzer()

                    st.write("⏳ Building XPath duplication registry...")
                    time.sleep(0.2)
                    xpath_registry, variable_registry = analyzer.build_project_registry(
                        project_files_content
                    )
                    st.write(f"✅ XPath registry: **{len(xpath_registry)}** unique XPaths")

                    st.write(f"✅ Variable registry: **{len(variable_registry)}** unique variables")

                    st.write("⏳ Cross-referencing for duplicates...")
                    time.sleep(0.2)
                    st.write("✅ Cross-file analysis complete")

                source_label = "local repo" if used_local else "GitLab API"
            status_container.update(
                label=f"✅ Project analysis complete — {len(project_files_content)} files via {source_label}",
                state="complete",
                expanded=False,
            )
        except Exception as e:
            st.warning(
                f"⚠️ Could not build full-project registry (cross-file checks will be skipped): {str(e)}"
            )

        # ── Execute Code Review ───────────────────────────────────────────────
        active_provider = st.session_state.get("llm_provider", settings.LLM_PROVIDER).lower()
        spinner_msg = (
            "Running Static & Laya Rule Engine Review (No LLM)..."
            if active_provider in ("none", "static", "laya")
            else f"Running AI Code Review using {active_provider.upper()} ({settings.LLM_MODEL})..."
        )
        with st.spinner(spinner_msg):
            agent = AICodeReviewerAgent(
                provider=st.session_state.get("llm_provider", settings.LLM_PROVIDER),
                model=st.session_state.get("llm_model", settings.LLM_MODEL),
                openai_api_key=st.session_state.get("openai_api_key", settings.OPENAI_API_KEY),
                gemini_api_key=st.session_state.get("gemini_api_key", settings.GEMINI_API_KEY),
                ollama_base_url=st.session_state.get("ollama_base_url", settings.OLLAMA_BASE_URL),
                ollama_api_key=st.session_state.get("ollama_api_key", settings.OLLAMA_API_KEY),
                groq_api_key=st.session_state.get("groq_api_key", settings.GROQ_API_KEY)
            )

            review_result = agent.review_diffs(
                mr_details.diffs,
                mr_title=mr_details.title,
                mr_desc=mr_details.description,
                xpath_registry=xpath_registry,
                variable_registry=variable_registry,
            )
            st.session_state["last_review_result"] = review_result
            st.session_state["current_mr"] = mr_details

        # Render Results
        render_score_card(review_result)

        st.markdown("### 📝 Executive Review Summary")
        st.markdown(review_result.summary)

        # Render Identified Findings
        render_issues_list(review_result)

        st.markdown("---")
        st.markdown("### 💬 Post Review to GitLab")

        report_md = generate_gitlab_markdown_report(review_result, mr_details.title)

        with st.expander("Preview GitLab Comment Markdown"):
            st.code(report_md, language="markdown")

        if st.button("📤 Post Comment to GitLab MR"):
            if not gitlab_token:
                st.error("GitLab Access Token is required to post comments.")
            else:
                with st.spinner("Posting review note to GitLab MR..."):
                    try:
                        client.post_mr_comment(project_identifier, mr_iid, report_md)
                        st.balloons()
                        st.success("Successfully posted AI review report to GitLab Merge Request!")
                    except Exception as e:
                        st.error(f"Failed to post comment to GitLab: {str(e)}")
