from setuptools import setup, find_packages

setup(
    name="review-bot",
    version="1.0.0",
    description="Automated Robot Framework HMI Merge Request Review Bot",
    author="QA Automation Team",
    packages=find_packages(),
    py_modules=["app"],
    install_requires=[
        "streamlit>=1.35.0",
        "python-gitlab>=4.4.0",
        "python-dotenv>=1.0.1",
        "requests>=2.31.0",
        "pydantic>=2.7.0",
        "openai>=1.30.0",
        "google-generativeai>=0.5.0",
        "robotframework>=7.0",
        "pyyaml>=6.0.1",
        "rich>=13.7.0",
        "laya>=0.1.0",
    ],
    entry_points={
        "console_scripts": [
            "review-bot=app:main",
        ],
    },
    python_requires=">=3.10",
)
