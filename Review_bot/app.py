import streamlit as st

# Configure Streamlit page settings
st.set_page_config(
    page_title="AI Agent Code Reviewer | Robot Framework & GitLab",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

from config.settings import settings
from src.ui.components import render_header
from src.ui.tabs.gitlab_tab import render_gitlab_tab
from src.ui.tabs.local_tab import render_local_tab
from src.ui.tabs.rules_tab import render_rules_tab
from src.ui.tabs.settings_tab import render_settings_tab

def main():
    # Render Application Header
    render_header()

    # Sidebar Info & Quick Config
    st.sidebar.title("🎛️ Quick Control")
    active_p = st.session_state.get('llm_provider', settings.LLM_PROVIDER).lower()
    if active_p in ("none", "static", "laya"):
        st.sidebar.success("⚡ **Engine:** Static Rules & Laya Engine (No LLM Required)")
    else:
        st.sidebar.markdown(f"**Active LLM:** `{active_p.upper()}`")
        st.sidebar.markdown(f"**Model:** `{st.session_state.get('llm_model', settings.LLM_MODEL)}`")
    st.sidebar.markdown("---")
    st.sidebar.info("💡 **HMI Tip:** Hardcoded sleeps in Robot Framework tests slow down CI/CD. Use dynamic wait keywords!")

    # Tabs Layout
    tab1, tab2, tab3, tab4 = st.tabs([
        "🦊 GitLab MR Reviewer",
        "📝 Local Code / Diff Review",
        "🤖 RF HMI Validation Rules",
        "⚙️ Settings & Credentials"
    ])

    with tab1:
        render_gitlab_tab()

    with tab2:
        render_local_tab()

    with tab3:
        render_rules_tab()

    with tab4:
        render_settings_tab()

if __name__ == "__main__":
    main()
