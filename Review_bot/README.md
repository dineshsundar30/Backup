# 🤖 AI Agent Code Reviewer for Robot Framework & GitLab MRs

An intelligent, scalable AI Code Reviewer tailored for **Robot Framework HMI (In-Vehicle Infotainment / Touchscreen UI) test automation** and **GitLab Merge Requests (MRs)**, powered by **Streamlit**.

---

## 🌟 Key Features

- 🦊 **GitLab MR Automated Review**: Automatically fetches Merge Request metadata, changed files, and unified diffs via GitLab API.
- 🤖 **Robot Framework HMI Rules Engine**: Specialized static analysis checks for:
  - 🛑 **Prohibition of Hardcoded Sleep**: Replaces static `Sleep 5s` with dynamic wait keywords (`Wait Until Element Is Visible`).
  - 📍 **Fragile Index-Based XPaths**: Detects brittle `//div[3]/button[2]` locators and enforces Page Object IDs.
  - 🔄 **Suite Lifecycle Verification**: Ensures `Suite Setup` and `Suite Teardown` exist for session init and screenshot capture on failure.
  - 🏷️ **Metadata Checks**: Enforces `[Documentation]` and `[Tags]` (e.g. `HMI`, `Sanity`).
- 🧠 **Multi-Provider LLM Integration**: Connects to **OpenAI** (`gpt-4o`, `gpt-4o-mini`), **Google Gemini** (`gemini-1.5-flash`), **Ollama** (offline local models like `qwen2.5-coder`), and **Groq**.
- 💬 **GitLab MR Comment Posting**: One-click action to post structured review reports and line-by-line findings back onto GitLab MR notes.
- 📝 **Local Snippet & Diff Mode**: Paste raw Robot Framework code or Python test libraries for instant pre-commit analysis.

---

## 🚀 Quick Start

### 1. Installation

Clone or navigate to the project directory:

```bash
cd /home/dinesh/DK/Backup/Review_bot
```

Install python dependencies:

```bash
pip install -r requirements.txt
```

### 2. Environment Configuration

Copy `.env.example` to `.env` and add your credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Options: openai, gemini, ollama, groq
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5-coder

# Remote or Local Ollama Machine Settings
OLLAMA_BASE_URL=http://192.168.1.100:11434  # Replace with remote server IP or hostname
OLLAMA_API_KEY=your_remote_ollama_api_key   # Optional bearer token if remote proxy requires auth

GITLAB_URL=https://gitlab.com
GITLAB_TOKEN=your_gitlab_personal_access_token
```

### 3. Launching Streamlit Web App

Start the interactive dashboard:

```bash
streamlit run app.py
```

Open your browser at `http://localhost:8501`.

---

## 📁 Project Architecture

```
Review_bot/
├── app.py                     # Streamlit Main Dashboard Entrypoint
├── requirements.txt           # Python dependencies
├── .env.example               # Environment variables template
├── README.md                  # System Documentation
├── config/
│   └── settings.py            # Centralized settings & environment loader
├── src/
│   ├── gitlab_client.py       # GitLab API client (MR diffs & comment posting)
│   ├── rf_analyzer.py         # Static analyzer for Robot Framework HMI rules
│   ├── ai_agent.py            # Multi-provider LLM review agent
│   ├── models.py              # Data structures (MRDetails, ReviewResult, ReviewIssue)
│   └── ui/
│       ├── components.py      # Streamlit reusable UI components
│       └── tabs/              # Tab interfaces (GitLab, Local Code, Rules, Settings)
└── tests/
    └── sample_rf/             # Sample test files for testing review engine
```

---

## 🤝 Usage Guide

### Reviewing a GitLab Merge Request
1. Open the **🦊 GitLab MR Reviewer** tab.
2. Enter your GitLab MR URL (e.g., `https://gitlab.com/org/repo/-/merge_requests/42`).
3. Click **Fetch & Review Merge Request**.
4. View overall quality score, executive summary, and findings.
5. Click **Post Comment to GitLab MR** to publish the report directly to GitLab.

### Reviewing Local Code Snippets
1. Open the **📝 Local Code / Diff Review** tab.
2. Click **Load Sample Code** or paste your `.robot` code.
3. Click **Review Local Code** for instant analysis.

---

*Built with Python, Streamlit, Robot Framework, and OpenAI/Gemini/Ollama.*
