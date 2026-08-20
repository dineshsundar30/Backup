import streamlit as st
from config.settings import settings

def render_settings_tab():
    st.subheader("⚙️ API Credentials & LLM Configuration")
    st.markdown("Configure LLM Providers (OpenAI, Gemini, Ollama, Groq) and GitLab Integration settings.")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 🤖 LLM Provider Settings")
        options_list = ["openai", "gemini", "ollama", "groq", "none"]
        curr_provider = st.session_state.get("llm_provider", settings.LLM_PROVIDER).lower()
        if curr_provider not in options_list:
            curr_provider = "none"

        provider = st.selectbox(
            "Select Review Engine / LLM Provider:",
            options=options_list,
            index=options_list.index(curr_provider),
            format_func=lambda x: "🚫 none (Static Rules & Laya Engine - No LLM)" if x in ("none", "static", "laya") else f"🤖 {x.upper()}"
        )
        st.session_state["llm_provider"] = provider

        if provider in ("none", "static", "laya"):
            st.info("⚡ **Offline / No-LLM Mode Active**: MR diff validation will run 100% locally using static rule analysis & Laya without external LLM API calls.")

        if provider == "openai":
            model = st.text_input("OpenAI Model:", value=st.session_state.get("llm_model", "gpt-4o-mini"))
            api_key = st.text_input("OpenAI API Key:", value=st.session_state.get("openai_api_key", settings.OPENAI_API_KEY), type="password")
            st.session_state["llm_model"] = model
            st.session_state["openai_api_key"] = api_key

        elif provider == "gemini":
            model = st.text_input("Gemini Model:", value=st.session_state.get("llm_model", "gemini-1.5-flash"))
            api_key = st.text_input("Gemini API Key:", value=st.session_state.get("gemini_api_key", settings.GEMINI_API_KEY), type="password")
            st.session_state["llm_model"] = model
            st.session_state["gemini_api_key"] = api_key

        elif provider == "ollama":
            model = st.text_input("Ollama Model:", value=st.session_state.get("llm_model", "qwen2.5-coder"))
            url = st.text_input("Ollama Endpoint URL (Local or Remote Server IP/Host):", value=st.session_state.get("ollama_base_url", settings.OLLAMA_BASE_URL), help="e.g. http://192.168.1.100:11434 or http://localhost:11434")
            api_key = st.text_input("Ollama API Key / Auth Token (Optional for Remote Proxy):", value=st.session_state.get("ollama_api_key", settings.OLLAMA_API_KEY), type="password", help="Leave blank if local Ollama without auth key.")
            st.session_state["llm_model"] = model
            st.session_state["ollama_base_url"] = url
            st.session_state["ollama_api_key"] = api_key

        elif provider == "groq":
            model = st.text_input("Groq Model:", value=st.session_state.get("llm_model", "llama-3.1-70b-versatile"))
            api_key = st.text_input("Groq API Key:", value=st.session_state.get("groq_api_key", settings.GROQ_API_KEY), type="password")
            st.session_state["llm_model"] = model
            st.session_state["groq_api_key"] = api_key

    with col2:
        st.markdown("### 🦊 GitLab Credentials")
        gl_url = st.text_input("GitLab Server URL:", value=settings.GITLAB_URL)
        gl_token = st.text_input("GitLab Access Token:", value=settings.GITLAB_TOKEN, type="password")

        st.markdown("### 🎛️ Review Preferences")
        strictness = st.select_slider(
            "Review Strictness Level:",
            options=["low", "medium", "high"],
            value=settings.REVIEW_STRICTNESS
        )

    st.markdown("---")
    if st.button("💾 Save Settings", type="primary"):
        st.success("Settings updated successfully for this session!")
