from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="smartpaper-tagging",
    version="0.1.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="智能學術文獻標籤管理系統",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/SmartPaper-Tagging",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Scientific/Engineering",
    ],
    python_requires=">=3.9",
    install_requires=[
        "openpyxl>=3.1.0",
        "requests>=2.31.0",
        "beautifulsoup4>=4.12.0",
        "lxml>=5.0.0",
        "google-generativeai>=0.5.0",
        "chromadb>=0.4.0",
        "pydantic>=2.0.0",
        "python-dotenv>=1.0.0",
        "rich>=13.0.0",
        "tqdm>=4.65.0",
    ],
    entry_points={
        "console_scripts": [
            "smartpaper=main:main",
        ],
    },
)
