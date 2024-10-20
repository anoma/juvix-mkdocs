"""
This file defines a configurator for the different plugins included in
mkdocs-juvix. It manages the different paths, mkdocs configurations, and
Juvix settings.
"""

import shutil
import subprocess
from os import getenv
from pathlib import Path
from typing import List, Optional

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.plugins import get_plugin_logger
from semver import Version

from mkdocs_juvix.juvix_version import MIN_JUVIX_VERSION

log = get_plugin_logger("ENV")

BASE_PATH = Path(__file__).parent
FIXTURES_PATH = BASE_PATH / "fixtures"


class ENV:
    ROOT_PATH: Path
    DOCS_DIRNAME: str = getenv("DOCS_DIRNAME", "docs")
    DOCS_PATH: Path
    CACHE_DIRNAME: str = getenv("CACHE_DIRNAME", ".hooks")
    CACHE_PATH: Path
    DIFF_ENABLED: bool
    DIFF_BIN: str
    DIFF_AVAILABLE: bool
    DIFF_DIR: Path
    DIFF_OPTIONS: List[str]
    SITE_URL: str
    SITE_DIR: Optional[str]
    JUVIX_VERSION: str = ""

    REMOVE_CACHE: bool = bool(
        getenv("REMOVE_CACHE", False)
    )  # Whether the cache should be removed

    JUVIX_ENABLED: bool = bool(
        getenv("JUVIX_ENABLED", True)
    )  # Whether the user wants to use Juvix
    JUVIX_FULL_VERSION: str
    JUVIX_BIN_NAME: str = getenv("JUVIX_BIN", "juvix")  # The name of the Juvix binary
    JUVIX_BIN_PATH: str = getenv("JUVIX_PATH", "")  # The path to the Juvix binary
    JUVIX_BIN: str = (
        JUVIX_BIN_PATH + "/" + JUVIX_BIN_NAME
        if JUVIX_BIN_PATH != ""
        else JUVIX_BIN_NAME
    )  # The full path to the Juvix binary
    JUVIX_AVAILABLE: bool = shutil.which(JUVIX_BIN) is not None
    JUVIX_FOOTER_CSS_FILENAME: str = getenv(
        "JUVIX_FOOTER_CSS_FILENAME", "juvix_codeblock_footer.css"
    )
    CACHE_JUVIX_MARKDOWN_DIRNAME: str = getenv(
        "CACHE_JUVIX_MARKDOWN_DIRNAME", ".original_juvix_markdown_files"
    )  # The name of the directory where the Juvix Markdown files are cached
    CACHE_JUVIX_PROJECT_HASH_FILENAME: str = getenv(
        "CACHE_JUVIX_PROJECT_HASH_FILENAME", ".hash_compound_of_juvix_markdown_files"
    )  # The name of the file where the Juvix Markdown files are cached

    CACHE_ISABELLE_THEORIES_DIRNAME: str = getenv(
        "CACHE_ISABELLE_THEORIES_DIRNAME", ".isabelle_theories"
    )  # The name of the directory where the Isabelle Markdown files are cached
    CACHE_ISABELLE_OUTPUT_PATH: Path
    CACHE_HASHES_DIRNAME: str = getenv(
        "CACHE_HASHES_DIRNAME", ".hashes_for_juvix_markdown_files"
    )  # The name of the directory where the hashes are stored
    CACHE_HTML_DIRNAME: str = getenv(
        "CACHE_HTML_DIRNAME", ".html"
    )  # The name of the directory where the HTML files are cached
    FIRST_RUN: bool = bool(
        getenv("FIRST_RUN", True)
    )  # Whether this is the first time the plugin is run
    CACHE_MARKDOWN_JUVIX_OUTPUT_DIRNAME: str = getenv(
        "CACHE_MARKDOWN_JUVIX_OUTPUT_DIRNAME",
        ".markdown_output_from_juvix_markdown_files",
    )  # The name of the file where the Juvix Markdown files are stored
    CACHE_JUVIX_VERSION_FILENAME: str = getenv(
        "CACHE_JUVIX_VERSION_FILENAME", ".juvix_version"
    )  # The name of the file where the Juvix version is stored

    CACHE_ABSPATH: Path  # The path to the cache directory
    CACHE_ORIGINAL_JUVIX_MARKDOWN_FILES_ABSPATH: (
        Path  # The path to the Juvix Markdown cache directory
    )
    ROOT_ABSPATH: Path  # The path to the root directory
    DOCS_ABSPATH: Path  # The path to the documentation directory
    CACHE_MARKDOWN_JUVIX_OUTPUT_PATH: (
        Path  # The path to the Juvix Markdown output directory
    )
    CACHE_HTML_PATH: Path  # The path to the Juvix Markdown output directory
    CACHE_JUVIX_PROJECT_HASH_FILEPATH: (
        Path  # The path to the Juvix Markdown output directory
    )
    CACHE_HASHES_PATH: Path  # The path where hashes are stored (not the project hash)
    JUVIX_FOOTER_CSS_FILEPATH: Path  # The path to the Juvix footer CSS file
    CACHE_JUVIX_VERSION_FILEPATH: Path  # The path to the Juvix version file
    TOKEN_ISABELLE_THEORY: str = "<!-- ISABELLE_THEORY -->"
    SHOW_TODOS_IN_MD: bool

    def __init__(self, config: Optional[MkDocsConfig] = None):
        if config:
            config_file = config.config_file_path

            if config.get("use_directory_urls", False):
                log.error(
                    "use_directory_urls has been set to True to work with Juvix Markdown files."
                )
                exit(1)

            self.ROOT_PATH = Path(config_file).parent
            self.SITE_URL = config.get("site_url", "")
        else:
            self.ROOT_PATH = Path(".").resolve()
            self.SITE_URL = ""

        self.ROOT_ABSPATH = self.ROOT_PATH.absolute()

        self.DOCS_PATH = self.ROOT_PATH / self.DOCS_DIRNAME
        self.CACHE_PATH = self.ROOT_PATH / self.CACHE_DIRNAME
        self.CACHE_PATH.mkdir(parents=True, exist_ok=True)

        self.SHOW_TODOS_IN_MD = bool(getenv("SHOW_TODOS_IN_MD", False))
        self.REPORT_TODOS = bool(getenv("REPORT_TODOS", False))

        self.DIFF_ENABLED: bool = bool(getenv("DIFF_ENABLED", False))

        self.DIFF_BIN: str = getenv("DIFF_BIN", "diff")
        self.DIFF_AVAILABLE = shutil.which(self.DIFF_BIN) is not None

        self.DIFF_DIR: Path = self.CACHE_PATH / ".diff"
        self.DIFF_DIR.mkdir(parents=True, exist_ok=True)

        if self.DIFF_ENABLED:
            self.DIFF_OPTIONS = ["--unified", "--new-file", "--text"]

            try:
                subprocess.run([self.DIFF_BIN, "--version"], capture_output=True)
            except FileNotFoundError:
                log.warning(
                    "The diff binary is not available. Please install diff and make sure it's available in the PATH."
                )

        self.CACHE_ABSPATH = self.ROOT_ABSPATH / self.CACHE_DIRNAME
        self.CACHE_ORIGINAL_JUVIX_MARKDOWN_FILES_ABSPATH: Path = (
            self.CACHE_ABSPATH / self.CACHE_JUVIX_MARKDOWN_DIRNAME
        )  # The path to the Juvix Markdown cache directory
        self.ROOT_ABSPATH: Path = (
            self.CACHE_ABSPATH.parent
        )  # The path to the root directory
        self.DOCS_ABSPATH: Path = (
            self.ROOT_ABSPATH / self.DOCS_DIRNAME
        )  # The path to the documentation directory
        self.CACHE_MARKDOWN_JUVIX_OUTPUT_PATH: Path = (
            self.CACHE_ABSPATH / self.CACHE_MARKDOWN_JUVIX_OUTPUT_DIRNAME
        )  # The path to the Juvix Markdown output directory
        self.CACHE_HTML_PATH: Path = (
            self.CACHE_ABSPATH / self.CACHE_HTML_DIRNAME
        )  # The path to the Juvix Markdown output directory

        self.CACHE_ISABELLE_OUTPUT_PATH: Path = (
            self.CACHE_ABSPATH / self.CACHE_ISABELLE_THEORIES_DIRNAME
        )  # The path to the Isabelle output directory

        self.CACHE_JUVIX_PROJECT_HASH_FILEPATH: Path = (
            self.CACHE_ABSPATH / self.CACHE_JUVIX_PROJECT_HASH_FILENAME
        )  # The path to the Juvix Markdown output directory
        self.CACHE_HASHES_PATH: Path = (
            self.CACHE_ABSPATH / self.CACHE_HASHES_DIRNAME
        )  # The path where hashes are stored (not the project hash)

        self.JUVIX_FOOTER_CSS_FILEPATH: Path = (
            self.DOCS_ABSPATH / "assets" / "css" / self.JUVIX_FOOTER_CSS_FILENAME
        )
        self.CACHE_JUVIX_VERSION_FILEPATH: Path = (
            self.CACHE_ABSPATH / self.CACHE_JUVIX_VERSION_FILENAME
        )  # The path to the Juvix version file

        if not self.DOCS_ABSPATH.exists():
            log.error(
                "Expected documentation directory %s not found.", self.DOCS_ABSPATH
            )
            exit(1)

        directories: List[Path] = [
            self.CACHE_MARKDOWN_JUVIX_OUTPUT_PATH,
            self.CACHE_ISABELLE_OUTPUT_PATH,
            self.CACHE_ORIGINAL_JUVIX_MARKDOWN_FILES_ABSPATH,
            self.CACHE_ABSPATH,
            self.CACHE_HASHES_PATH,
            self.JUVIX_FOOTER_CSS_FILEPATH.parent,
        ]

        for directory in directories:
            if directory.exists() and self.REMOVE_CACHE:
                try:
                    shutil.rmtree(directory, ignore_errors=True)
                except Exception as e:
                    log.error(
                        f"Something went wrong while removing the directory {directory}. Error: {e}"
                    )
            directory.mkdir(parents=True, exist_ok=True)

        self.JUVIX_VERSION = ""
        self.JUVIX_FULL_VERSION = ""

        if self.JUVIX_AVAILABLE:
            full_version_cmd = [self.JUVIX_BIN, "--version"]
            try:
                result = subprocess.run(full_version_cmd, capture_output=True)
                if result.returncode == 0:
                    self.JUVIX_FULL_VERSION = result.stdout.decode("utf-8")
                    if "Branch: HEAD" not in self.JUVIX_FULL_VERSION:
                        log.debug(
                            "You are using a version of Juvix that may not be supported by this plugin. Use at your own risk!"
                        )
            except Exception as e:
                log.debug(
                    f"[!] Something went wrong while getting the full version of Juvix. Error: {e}"
                )

            numeric_version_cmd = [self.JUVIX_BIN, "--numeric-version"]
            try:
                result = subprocess.run(numeric_version_cmd, capture_output=True)
                if result.returncode == 0:
                    self.JUVIX_VERSION = result.stdout.decode("utf-8")
            except Exception as e:
                log.debug(
                    f"[!] Something went wrong while getting the numeric version of Juvix. Error: {e}"
                )

        if self.JUVIX_VERSION == "":
            log.debug(
                "Juvix version not found. Make sure Juvix is installed, for now support for Juvix Markdown is disabled."
            )
            self.JUVIX_ENABLED = False
            self.JUVIX_AVAILABLE = False

            return

        if Version.parse(self.JUVIX_VERSION) < MIN_JUVIX_VERSION:
            log.debug(
                f"""Juvix version {MIN_JUVIX_VERSION} or higher is required. Please upgrade Juvix and try again."""
            )
            self.JUVIX_ENABLED = False
            self.JUVIX_AVAILABLE = False
            return
