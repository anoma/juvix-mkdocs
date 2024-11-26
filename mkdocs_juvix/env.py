"""
This file defines a configurator for the different plugins included in
mkdocs-juvix. It manages the different paths, mkdocs configurations, and
Juvix settings.
"""

import os
import shutil
import subprocess
from functools import lru_cache, wraps
from os import getenv
from pathlib import Path
from typing import List, Optional, Tuple

from colorama import Fore, Style  # type: ignore
from mkdocs.config.defaults import MkDocsConfig
from mkdocs.plugins import get_plugin_logger
from semver import Version

import mkdocs_juvix.utils as utils
from mkdocs_juvix.juvix_version import MIN_JUVIX_VERSION
from mkdocs_juvix.utils import is_juvix_markdown_file

log = get_plugin_logger(f"{Fore.BLUE}[juvix_mkdocs] (env) {Style.RESET_ALL}")

BASE_PATH = Path(__file__).parent
FIXTURES_PATH = BASE_PATH / "fixtures"


class ENV:
    ROOT_PATH: Path
    DOCS_DIRNAME: str = getenv("DOCS_DIRNAME", "docs")
    DOCS_PATH: Path
    CACHE_DIRNAME: str = getenv("CACHE_DIRNAME", ".cache-juvix-mkdocs")
    CACHE_PATH: Path
    DIFF_ENABLED: bool
    DIFF_BIN: str
    DIFF_AVAILABLE: bool
    DIFF_DIR: Path
    DIFF_OPTIONS: List[str]
    SITE_URL: str = getenv("SITE_URL", "/")
    SITE_DIR: Optional[str]
    JUVIX_VERSION: str = ""
    USE_DOT: bool
    DOT_BIN: str
    DOT_FLAGS: str
    IMAGES_ENABLED: bool
    CLEAN_DEPS: bool = bool(getenv("CLEAN_DEPS", False))
    UPDATE_DEPS: bool = bool(getenv("UPDATE_DEPS", False))
    TIMELIMIT: int = int(getenv("TIMELIMIT", 10))

    REMOVE_CACHE: bool = bool(getenv("REMOVE_CACHE", False))

    JUVIX_ENABLED: bool = bool(getenv("JUVIX_ENABLED", True))
    JUVIX_FULL_VERSION: str
    JUVIX_BIN_NAME: str = getenv("JUVIX_BIN", "juvix")
    JUVIX_BIN_PATH: str = getenv("JUVIX_PATH", "")
    JUVIX_BIN: str = (
        JUVIX_BIN_PATH + "/" + JUVIX_BIN_NAME
        if JUVIX_BIN_PATH != ""
        else JUVIX_BIN_NAME
    )
    JUVIX_AVAILABLE: bool = shutil.which(JUVIX_BIN) is not None

    FIRST_RUN: bool = bool(getenv("FIRST_RUN", True))

    JUVIX_FOOTER_CSS_FILENAME: str = getenv(
        "JUVIX_FOOTER_CSS_FILENAME", "juvix_codeblock_footer.css"
    )
    CACHE_ORIGINALS_DIRNAME: str = getenv("CACHE_ORIGINALS_DIRNAME", ".originals")
    CACHE_PROJECT_HASH_FILENAME: str = getenv(
        "CACHE_PROJECT_HASH_FILENAME", ".compound_hash_of_originals"
    )

    ISABELLE_THEORIES_DIRNAME: str = getenv(
        "CACHE_ISABELLE_THEORIES_DIRNAME", "isabelle_theories"
    )
    ISABELLE_OUTPUT_PATH: Path
    CACHE_HASHES_DIRNAME: str = getenv("CACHE_HASHES_DIRNAME", ".hashes")
    CACHE_HTML_DIRNAME: str = getenv("CACHE_HTML_DIRNAME", ".html")

    DOCS_INDEXES_DIRNAME: str = getenv("DOCS_INDEXES_DIRNAME", "indexes")
    CACHE_PROCESSED_MARKDOWN_DIRNAME: str = getenv(
        "CACHE_PROCESSED_MARKDOWN_DIRNAME",
        ".processed_markdown",
    )
    DOCS_IMAGES_DIRNAME: str = getenv("DOCS_IMAGES_DIRNAME", "images")
    CACHE_JUVIX_VERSION_FILENAME: str = getenv(
        "CACHE_JUVIX_VERSION_FILENAME", ".juvix_version"
    )

    ROOT_ABSPATH: Path
    CACHE_ABSPATH: Path
    DOCS_ABSPATH: Path
    CACHE_ORIGINALS_ABSPATH: Path
    CACHE_PROCESSED_MARKDOWN_PATH: Path
    CACHE_HTML_PATH: Path
    CACHE_PROJECT_HASH_FILEPATH: Path
    CACHE_HASHES_PATH: Path
    JUVIX_FOOTER_CSS_FILEPATH: Path
    CACHE_JUVIX_VERSION_FILEPATH: Path
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
        else:
            self.ROOT_PATH = Path(".").resolve()

        self.ROOT_ABSPATH = self.ROOT_PATH.absolute()
        self.CACHE_ABSPATH = self.ROOT_ABSPATH / self.CACHE_DIRNAME

        self.DOCS_PATH = self.ROOT_PATH / self.DOCS_DIRNAME
        self.CACHE_PATH = self.ROOT_PATH / self.CACHE_DIRNAME
        self.CACHE_PATH.mkdir(parents=True, exist_ok=True)

        self.SHOW_TODOS_IN_MD = bool(getenv("SHOW_TODOS_IN_MD", False))
        self.REPORT_TODOS = bool(getenv("REPORT_TODOS", False))

        self.DIFF_ENABLED: bool = bool(getenv("DIFF_ENABLED", False))

        if not self.SITE_URL.endswith("/"):
            self.SITE_URL = self.SITE_URL + "/"
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

        self.CACHE_ORIGINALS_ABSPATH: Path = (
            self.CACHE_ABSPATH / self.CACHE_ORIGINALS_DIRNAME
        )
        self.DOCS_ABSPATH: Path = self.ROOT_ABSPATH / self.DOCS_DIRNAME
        self.IMAGES_PATH: Path = self.DOCS_ABSPATH / self.DOCS_IMAGES_DIRNAME

        self.CACHE_PROCESSED_MARKDOWN_PATH: Path = (
            self.CACHE_ABSPATH / self.CACHE_PROCESSED_MARKDOWN_DIRNAME
        )
        self.CACHE_HTML_PATH: Path = self.CACHE_ABSPATH / self.CACHE_HTML_DIRNAME

        self.ISABELLE_OUTPUT_PATH: Path = (
            self.ROOT_ABSPATH / self.ISABELLE_THEORIES_DIRNAME
        )
        self.ISABELLE_OUTPUT_PATH.mkdir(parents=True, exist_ok=True)

        self.CACHE_PROJECT_HASH_FILEPATH: Path = (
            self.CACHE_ABSPATH / self.CACHE_PROJECT_HASH_FILENAME
        )
        self.CACHE_HASHES_PATH: Path = self.CACHE_ABSPATH / self.CACHE_HASHES_DIRNAME

        self.JUVIX_FOOTER_CSS_FILEPATH: Path = (
            self.DOCS_ABSPATH / "assets" / "css" / self.JUVIX_FOOTER_CSS_FILENAME
        )
        self.CACHE_JUVIX_VERSION_FILEPATH: Path = (
            self.CACHE_ABSPATH / self.CACHE_JUVIX_VERSION_FILENAME
        )

        if not self.DOCS_ABSPATH.exists():
            log.error(
                "Expected documentation directory %s not found.", self.DOCS_ABSPATH
            )
            exit(1)

        if (
            self.CACHE_ABSPATH.exists()
            and self.REMOVE_CACHE
            and config
            and not config.get("env_init", False)
        ):
            try:
                log.debug(
                    f"{Fore.YELLOW}Removing directory {self.CACHE_ABSPATH}{Style.RESET_ALL}"
                )
                shutil.rmtree(self.CACHE_ABSPATH, ignore_errors=True)
            except Exception as e:
                log.error(
                    f"Something went wrong while removing the directory {self.CACHE_ABSPATH}. Error: {e}"
                )
            self.CACHE_ABSPATH.mkdir(parents=True, exist_ok=True)

        # Create the cache directories
        self.CACHE_ORIGINALS_ABSPATH.mkdir(parents=True, exist_ok=True)
        self.CACHE_PROCESSED_MARKDOWN_PATH.mkdir(parents=True, exist_ok=True)
        self.ISABELLE_OUTPUT_PATH.mkdir(parents=True, exist_ok=True)
        self.CACHE_HTML_PATH.mkdir(parents=True, exist_ok=True)
        self.CACHE_HASHES_PATH.mkdir(parents=True, exist_ok=True)

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
                f"""Juvix version {Fore.RED}{MIN_JUVIX_VERSION}{Style.RESET_ALL}
                or higher is required. Please upgrade Juvix and try again."""
            )
            exit(1)

        self.USE_DOT = bool(getenv("USE_DOT", True))
        self.DOT_BIN = getenv("DOT_BIN", "dot")
        self.DOT_FLAGS = getenv("DOT_FLAGS", "-Tsvg")
        self.IMAGES_ENABLED = bool(getenv("IMAGES_ENABLED", True))
        if config:
            config["env_init"] = True

    @property
    def juvix_enabled(self) -> bool:
        return self.JUVIX_ENABLED and self.JUVIX_AVAILABLE

    @staticmethod
    def when_juvix_enabled(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if self.juvix_enabled:
                return func(self, *args, **kwargs)
            return None

        return wrapper

    def read_markdown_file_from_cache(self, filepath: Path) -> Optional[str]:
        if cache_ABSpath := self.compute_processed_filepath(filepath):
            return cache_ABSpath.read_text()
        return None

    def compute_filepath_for_cached_hash_for(self, filepath: Path) -> Path:
        file_abspath = filepath.absolute()
        return utils.get_filepath_for_cached_hash_for(
            file_abspath, hash_dir=self.CACHE_HASHES_PATH
        )

    def is_file_new_or_changed_for_cache(self, filepath: Path) -> bool:
        file_abspath = filepath.absolute()
        hash_file = self.compute_filepath_for_cached_hash_for(file_abspath)
        if not hash_file.exists():
            return True  # File is new
        # compute the hash of the file content to check if it has changed
        current_hash = utils.hash_content_of(file_abspath)
        cached_hash = hash_file.read_text().strip()
        return current_hash != cached_hash  # File has changed if hashes are different

    def update_cache_for_file(self, filepath: Path, file_content: str) -> None:
        file_abspath = filepath.absolute()
        cache_filepath = self.compute_filepath_for_cached_hash_for(file_abspath)
        cache_filepath.parent.mkdir(parents=True, exist_ok=True)
        cache_filepath.write_text(file_content)
        self.update_hash_file(file_abspath)

    def compute_filepath_for_original_file_in_cache(self, filepath: Path) -> Path:
        file_abspath = filepath.absolute()
        rel_to_docs = file_abspath.relative_to(self.DOCS_ABSPATH)
        return self.CACHE_ORIGINALS_ABSPATH / rel_to_docs.parent / filepath.name

    @lru_cache(maxsize=128)
    def compute_processed_filepath(
        self,
        filepath: Path,
        relative_to: Optional[Path] = None,
    ) -> Path:
        log.debug(f"Computing processed filepath for {filepath}")

        if filepath.name.endswith(".juvix.md"):
            md_filename = filepath.name.replace(".juvix.md", ".md")
            log.debug(f"Converted Juvix markdown filename to: {md_filename}")
        else:
            md_filename = filepath.name
            log.debug(f"Using markdown filename: {md_filename}")

        # check if the filepath is absolute
        if filepath.is_absolute():
            log.debug(f"Filepath is absolute: {filepath}")
            filepath = filepath.relative_to(self.DOCS_ABSPATH)
            processed_path = (
                self.CACHE_PROCESSED_MARKDOWN_PATH / filepath.parent / md_filename
            )
            log.debug(
                f"Computed processed filepath for absolute path: {processed_path}"
            )
            return processed_path
        else:
            log.debug(f"Filepath is relative: {filepath}")

        if len(filepath.parts) > 0 and filepath.parts[0] in ["docs", "./docs"]:
            filepath = Path(*filepath.parts[1:])
            processed_path = (
                self.CACHE_PROCESSED_MARKDOWN_PATH / filepath.parent / md_filename
            )
            log.debug(f"Computed processed filepath for docs path: {processed_path}")
            return processed_path

        if relative_to is None:
            log.error("No relative path specified for the processed filepath")
            return filepath

        if relative_to.is_file():
            processed_path = (
                self.CACHE_PROCESSED_MARKDOWN_PATH / relative_to.parent / md_filename
            )
            log.debug(f"Computed processed filepath relative to file: {processed_path}")
            return processed_path
        else:
            processed_path = (
                self.CACHE_PROCESSED_MARKDOWN_PATH / relative_to / md_filename
            )
            log.debug(
                f"Computed processed filepath relative to directory: {processed_path}"
            )
            return processed_path

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
        log.debug(
            f"Getting filename module by extension for {filepath} with extension {extension}"
        )
        module_name = self.unqualified_module_name(filepath)
        log.debug(f"Module name: {module_name}")
        return module_name + extension if module_name else None

    def update_hash_file(self, filepath: Path) -> Optional[Tuple[Path, str]]:
        filepath_hash = self.compute_filepath_for_cached_hash_for(filepath)
        try:
            with open(filepath_hash, "w") as f:
                content_hash = utils.hash_content_of(filepath)
                f.write(content_hash)
                return (filepath_hash, content_hash)
        except Exception as e:
            log.error(f"Error updating hash file: {e}")
            return None

    def remove_directory(self, directory: Path) -> None:
        try:
            shutil.rmtree(directory, ignore_errors=True)
        except Exception as e:
            log.error(f"Error removing folder: {e}")

    def copy_directory(self, src: Path, dst: Path) -> None:
        try:
            shutil.copytree(src, dst, dirs_exist_ok=True)
        except Exception as e:
            log.error(f"Error copying folder: {e}")

    def compute_filepath_for_juvix_isabelle_output_in_cache(
        self, filepath: Path
    ) -> Optional[Path]:
        if not is_juvix_markdown_file(filepath):
            log.debug(f"Filepath is not a Juvix Markdown filepath: {filepath}")
            return None

        log.debug(f"Computing filepath for Isabelle output in cache for {filepath}")
        cache_markdown_filename: Optional[str] = self.get_filename_module_by_extension(
            filepath, extension=".thy"
        )
        log.debug(f"Cache markdown filename: {cache_markdown_filename}")

        if cache_markdown_filename is None:
            log.debug(f"No Isabelle output filename found for {filepath}")
            return None

        if filepath.is_relative_to(self.DOCS_ABSPATH):
            rel_to_docs = filepath.relative_to(self.DOCS_ABSPATH)
        elif filepath.is_relative_to("./docs"):
            rel_to_docs = filepath.relative_to("./docs")
        elif filepath.is_relative_to("docs"):
            rel_to_docs = filepath.relative_to("docs")
        else:
            rel_to_docs = filepath

        cache_markdown_filepath: Path = (
            self.ISABELLE_OUTPUT_PATH / rel_to_docs.parent / cache_markdown_filename
        )
        cache_markdown_filepath.parent.mkdir(parents=True, exist_ok=True)
        log.debug(
            f"Computed filepath for Isabelle output in cache: {cache_markdown_filepath}"
        )
        return cache_markdown_filepath

    def find_file_in(
        self,
        _filepath: Path | str,
        _relative_to: Optional[Path | str],
        _base_path: Optional[Path | str],
        cache: bool = True,
    ) -> Optional[Path]:
        """
        The filepath can be:
        - Relative to the docs directory, e.g., "docs/..." or "./docs/..."
        - Absolute, e.g., "/some/path/to/docs/..."
        - Relative to the current working directory, in which case, relative_to
        should be specified.

        Otherwise, the search will be done relative to
        self.CACHE_PROCESSED_MARKDOWN_PATH first, or relative to the docs
        directory otherwise.

        If the filepath is relative to the docs directory, the path to the
        processed markdown file in the cache is obtained using
        self.CACHE_PROCESSED_MARKDOWN_PATH. If the filepath is absolute, it is
        checked for existence. If the filepath is relative to the current
        working directory, relative_to is used to find the file.
        """
        filepath: Path = Path(_filepath) if isinstance(_filepath, str) else _filepath
        relative_to = (
            Path(_relative_to) if isinstance(_relative_to, str) else _relative_to
        )
        base_path = Path(_base_path) if isinstance(_base_path, str) else _base_path

        filepath = Path(filepath.name.replace(".juvix.md", ".md"))

        log.debug(f"Attempting to find file: {filepath}")

        if filepath.is_relative_to("./docs") or filepath.is_relative_to("docs"):
            filepath = (
                filepath.relative_to("./docs")
                if filepath.is_relative_to("./docs")
                else filepath.relative_to("docs")
            )
            # Check if the filepath is relative to the docs directory
            docs_relative_path = self.DOCS_ABSPATH / filepath
            if docs_relative_path.exists():
                log.debug(
                    f"File found relative to docs directory: {docs_relative_path}"
                )
                if not base_path and cache:
                    new_path = self.CACHE_PROCESSED_MARKDOWN_PATH / filepath
                    if new_path.exists():
                        log.debug(
                            f"File found relative to cache processed markdown path: {new_path}"
                        )
                        return new_path
                new_path = base_path / filepath if base_path else docs_relative_path
                if new_path.exists():
                    log.debug(f"File found relative to base path: {new_path}")
                    return new_path

        # Check if the filepath is absolute
        if filepath.is_absolute():
            log.debug(f"Filepath is absolute: {filepath}")
            if filepath.exists():
                log.debug(f"File found at absolute path: {filepath}")
                return filepath
            else:
                log.debug(f"File not found at absolute path: {filepath}")
                return None

        # Check if the filepath is relative to the current working directory
        if relative_to:
            if isinstance(relative_to, str):
                relative_to = Path(relative_to)
            relative_to = relative_to.resolve().absolute()
            if relative_to.is_file():
                relative_path = relative_to.parent / filepath
            else:
                relative_path = relative_to / filepath

            log.debug(f"Checking relative to provided path: {relative_path}")
            if relative_path.exists():
                log.debug(f"File found relative to provided path: {relative_path}")
                return relative_path if base_path is None else base_path / relative_path

        # Fallback to checking relative to the cache processed markdown path
        cache_relative_path = self.CACHE_PROCESSED_MARKDOWN_PATH / filepath
        log.debug(
            f"Checking relative to cache processed markdown path: {cache_relative_path}"
        )
        if cache_relative_path.exists():
            log.debug(
                f"File found relative to cache processed markdown path: {cache_relative_path}"
            )
            return (
                cache_relative_path
                if base_path is None
                else base_path / cache_relative_path
            )

        log.debug(f"File not found: {filepath}")
        return None
