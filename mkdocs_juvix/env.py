"""
This file defines a configurator for the different plugins included in
mkdocs-juvix. It manages the different paths, mkdocs configurations, and
Juvix settings.
"""

import os
import shutil
import subprocess
from functools import lru_cache
from os import getenv
from pathlib import Path
from typing import List, Optional, Tuple

from colorama import Fore, Style  # type: ignore
from mkdocs.config.defaults import MkDocsConfig
from mkdocs.plugins import get_plugin_logger
from semver import Version

from mkdocs_juvix.juvix_version import MIN_JUVIX_VERSION
from mkdocs_juvix.utils import compute_hash_filepath, hash_file

log = get_plugin_logger(f"{Fore.BLUE}[juvix_mkdocs-env]{Style.RESET_ALL}")

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
    USE_DOT: bool
    DOT_BIN: str
    DOT_FLAGS: str
    IMAGES_ENABLED: bool

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

    FIRST_RUN: bool = bool(
        getenv("FIRST_RUN", True)
    )  # Whether this is the first time the plugin is run

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

    DOCS_INDEXES_DIRNAME: str = getenv("DOCS_INDEXES_DIRNAME", "indexes")
    CACHE_MARKDOWN_JUVIX_OUTPUT_DIRNAME: str = getenv(
        "CACHE_MARKDOWN_JUVIX_OUTPUT_DIRNAME",
        ".markdown_output_from_juvix_markdown_files",
    )  # The name of the file where the Juvix Markdown files are stored
    CACHE_WIKILINKS_DIRNAME: str = getenv(
        "CACHE_WIKILINKS_DIRNAME", ".wikilinks"
    )  # The name of the file where the Juvix Markdown files are stored
    DOCS_IMAGES_DIRNAME: str = getenv("DOCS_IMAGES_DIRNAME", "images")
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
    CACHE_WIKILINKS_PATH: Path  # The path to the wikilinks cache directory
    CACHE_HTML_PATH: Path  # The path to the Juvix Markdown output directory
    CACHE_JUVIX_PROJECT_HASH_FILEPATH: (
        Path  # The path to the Juvix Markdown output directory
    )
    CACHE_HASHES_PATH: Path  # The path where hashes are stored (not the project hash)
    JUVIX_FOOTER_CSS_FILEPATH: Path  # The path to the Juvix footer CSS file
    CACHE_JUVIX_VERSION_FILEPATH: Path  # The path to the Juvix version file
    TOKEN_ISABELLE_THEORY: str = "<!-- ISABELLE_THEORY -->"
    SHOW_TODOS_IN_MD: bool
    INDEXES_PATH: Path
    IMAGES_PATH: Path

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
        self.CACHE_ABSPATH = self.ROOT_ABSPATH / self.CACHE_DIRNAME

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

        self.CACHE_ORIGINAL_JUVIX_MARKDOWN_FILES_ABSPATH: Path = (
            self.CACHE_ABSPATH / self.CACHE_JUVIX_MARKDOWN_DIRNAME
        )  # The path to the Juvix Markdown cache directory
        self.ROOT_ABSPATH: Path = (
            self.CACHE_ABSPATH.parent
        )  # The path to the root directory
        self.DOCS_ABSPATH: Path = (
            self.ROOT_ABSPATH / self.DOCS_DIRNAME
        )  # The path to the documentation directory
        self.IMAGES_PATH: Path = (
            self.DOCS_ABSPATH / self.DOCS_IMAGES_DIRNAME
        )  # The path to the images directory

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
        self.CACHE_WIKILINKS_PATH: Path = (
            self.CACHE_ABSPATH / self.CACHE_WIKILINKS_DIRNAME
        )  # The path to the wikilinks cache directory

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
            self.CACHE_WIKILINKS_PATH,
        ]

        for directory in directories:
            if (
                directory.exists()
                and self.REMOVE_CACHE
                and config
                and not config.get("env_init", False)
            ):
                try:
                    log.info(
                        f"Removing directory {Fore.RED}{directory}{Style.RESET_ALL}"
                    )
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

        self.USE_DOT = bool(getenv("USE_DOT", True))
        self.DOT_BIN = getenv("DOT_BIN", "dot")
        self.DOT_FLAGS = getenv("DOT_FLAGS", "-Tsvg")
        self.IMAGES_ENABLED = bool(getenv("IMAGES_ENABLED", True))
        if config:
            config["env_init"] = True

    @lru_cache(maxsize=128)
    def read_markdown_file_from_cache(self, filepath: Path) -> Optional[str]:
        if cache_ABSpath := self.get_filepath_for_juvix_markdown_in_cache(filepath):
            return cache_ABSpath.read_text()
        return None

    @lru_cache(maxsize=128)
    def read_wikilinks_file_from_cache(self, filepath: Path) -> Optional[str]:
        if cache_ABSpath := self.get_filepath_for_wikilinks_in_cache(filepath):
            return cache_ABSpath.read_text()
        return None

    def write_wikilinks_file_to_cache(self, filepath: Path, content: str) -> None:
        if cache_ABSpath := self.get_filepath_for_wikilinks_in_cache(filepath):
            cache_ABSpath.write_text(content)

    def get_filepath_for_wikilinks_in_cache(self, filepath: Path) -> Optional[Path]:
        filepath = filepath.absolute()
        rel_to_docs = filepath.relative_to(self.DOCS_ABSPATH)
        return self.CACHE_WIKILINKS_PATH / rel_to_docs.parent / filepath.name

    def new_or_changed_or_not_exists(self, filepath: Path) -> bool:
        content_hash = hash_file(filepath)
        path_hash = compute_hash_filepath(filepath, hash_dir=self.CACHE_HASHES_PATH)
        if not path_hash.exists():
            log.debug(f"File: {filepath} does not have a hash file.")
            return True
        fresh_content_hash = path_hash.read_text()
        return content_hash != fresh_content_hash

    @lru_cache(maxsize=128)
    def get_filepath_for_juvix_markdown_in_cache(
        self, _filepath: Path
    ) -> Optional[Path]:
        filepath = _filepath.absolute()
        md_filename = filepath.name.replace(".juvix.md", ".md")
        rel_to_docs = filepath.relative_to(self.DOCS_ABSPATH)
        return self.CACHE_MARKDOWN_JUVIX_OUTPUT_PATH / rel_to_docs.parent / md_filename

    def unqualified_module_name(self, filepath: Path) -> Optional[str]:
        fposix: str = filepath.as_posix()
        if not fposix.endswith(".juvix.md"):
            return None
        return os.path.basename(fposix).replace(".juvix.md", "")

    def qualified_module_name(self, filepath: Path) -> Optional[str]:
        absolute_path = filepath.absolute()
        cmd = [self.JUVIX_BIN, "dev", "root", absolute_path.as_posix()]
        pp = subprocess.run(cmd, cwd=self.DOCS_ABSPATH, capture_output=True)
        root = None
        try:
            root = pp.stdout.decode("utf-8").strip()
        except Exception as e:
            log.error(f"Error running Juvix dev root: {e}")
            return None

        if not root:
            return None

        relative_to_root = filepath.relative_to(Path(root))

        qualified_name = (
            relative_to_root.as_posix()
            .replace(".juvix.md", "")
            .replace("./", "")
            .replace("/", ".")
        )

        return qualified_name if qualified_name else None

    def get_filename_module_by_extension(
        self, filepath: Path, extension: str = ".md"
    ) -> Optional[str]:
        """
        The markdown filename is the same as the juvix file name but without the .juvix.md extension.
        """
        module_name = self.unqualified_module_name(filepath)
        return module_name + extension if module_name else None

    def update_hash_file(self, filepath: Path) -> Optional[Tuple[Path, str]]:  # noqa: F821
        filepath_hash = compute_hash_filepath(filepath, hash_dir=self.CACHE_HASHES_PATH)
        try:
            with open(filepath_hash, "w") as f:
                content_hash = hash_file(filepath)
                f.write(content_hash)
                return (filepath_hash, content_hash)
        except Exception as e:
            log.error(f"Error updating hash file: {e}")
            return None

    def get_expected_filepath_for_juvix_markdown_output_in_cache(
        self, filepath: Path
    ) -> Optional[Path]:
        cache_markdown_filename: Optional[str] = self.get_filename_module_by_extension(
            filepath, extension=".md"
        )
        if cache_markdown_filename is None:
            return None
        rel_to_docs = filepath.relative_to(self.DOCS_ABSPATH)
        cache_markdown_filepath: Path = (
            self.CACHE_MARKDOWN_JUVIX_OUTPUT_PATH
            / rel_to_docs.parent
            / cache_markdown_filename
        )
        return cache_markdown_filepath

    def get_expected_filepath_for_juvix_isabelle_output_in_cache(
        self, filepath: Path
    ) -> Optional[Path]:
        cache_isabelle_filename: Optional[str] = self.get_filename_module_by_extension(
            filepath, extension=".thy"
        )
        if cache_isabelle_filename is None:
            return None
        rel_to_docs = filepath.relative_to(self.DOCS_ABSPATH)
        cache_isabelle_filepath: Path = (
            self.CACHE_ISABELLE_OUTPUT_PATH
            / rel_to_docs.parent
            / cache_isabelle_filename
        )
        return cache_isabelle_filepath
