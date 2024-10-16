import json
import os
import shutil
import subprocess
from functools import lru_cache, wraps
from os import getenv
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import pathspec
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from mkdocs.config.defaults import MkDocsConfig
from mkdocs.plugins import BasePlugin, get_plugin_logger
from mkdocs.structure.files import Files
from mkdocs.structure.pages import Page
from semver import Version
from watchdog.events import FileSystemEvent

from mkdocs_juvix.utils import (
    compute_hash_filepath,
    compute_sha_over_folder,
    fix_site_url,
    hash_file,
)

load_dotenv()

log = get_plugin_logger("JuvixPlugin")

BASE_PATH = Path(__file__).parent
FIXTURES_PATH = BASE_PATH / "fixtures"


class JuvixPlugin(BasePlugin):
    mkconfig: MkDocsConfig
    juvix_md_files: List[Dict[str, Any]]

    # Config variables created from environment variables or from the config file
    SITE_DIR: Optional[str]
    SITE_URL: str
    JUVIX_VERSION: str = ""

    REMOVE_CACHE: bool = bool(
        getenv("REMOVE_CACHE", False)
    )  # Whether the cache should be removed

    JUVIX_ENABLED: bool = bool(
        getenv("JUVIX_ENABLED", True)
    )  # Whether the user wants to use Juvix
    MIN_JUVIX_VERSION: Optional[str] = getenv(
        "JUVIX_EXPECTED_VERSION", None
    )  # The version of Juvix that is being used
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
    CACHE_DIRNAME: str = getenv(
        "CACHE_DIRNAME", ".hooks"
    )  # The name of the directory where the hooks are stored
    DOCS_DIRNAME: str = getenv(
        "DOCS_DIRNAME", "docs"
    )  # The name of the directory where the documentation is stored

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

    _mkdocs_pipeline: str = """ For reference, the Mkdocs Pipeline is the following:
    ├── on_startup(command, dirty)
    └── on_config(config)
        ├── on_pre_build(config)
        ├── on_files(files, config)
        │   └── on_nav(nav, config, files)
        │       ├── Populate the page:
        │       │   ├── on_pre_page(page, config, files)
        │       │   ├── on_page_read_source(page, config)
        │       │   ├── on_page_markdown(markdown, page, config, files)
        │       │   ├── render()
        │       │   └── on_page_content(html, page, config, files)
        │       ├── on_env(env, config, files)
        │       └── Build the pages:
        │           ├── get_context()
        │           ├── on_page_context(context, page, config, nav)
        │           ├── get_template() & render()
        │           ├── on_post_page(output, page, config)
        │           └── write_file()
        ├── on_post_build(config)
        ├── on_serve(server, config)
        └── on_shutdown()
    """

    def _variables(self) -> Dict[str, Any]:
        return {
            "CACHE_DIRNAME": self.CACHE_DIRNAME,
            "CACHE_HASHES_DIRNAME": self.CACHE_HASHES_DIRNAME,
            "CACHE_HASHES_PATH": self.CACHE_HASHES_PATH,
            "CACHE_HTML_DIRNAME": self.CACHE_HTML_DIRNAME,
            "CACHE_ISABELLE_THEORIES_DIRNAME": self.CACHE_ISABELLE_THEORIES_DIRNAME,
            "CACHE_JUVIX_MARKDOWN_DIRNAME": self.CACHE_JUVIX_MARKDOWN_DIRNAME,
            "CACHE_JUVIX_PROJECT_HASH_FILENAME": self.CACHE_JUVIX_PROJECT_HASH_FILENAME,
            "CACHE_JUVIX_PROJECT_HASH_FILEPATH": self.CACHE_JUVIX_PROJECT_HASH_FILEPATH,
            "CACHE_JUVIX_VERSION_FILENAME": self.CACHE_JUVIX_VERSION_FILENAME,
            "CACHE_JUVIX_VERSION_FILEPATH": self.CACHE_JUVIX_VERSION_FILEPATH,
            "CACHE_MARKDOWN_JUVIX_OUTPUT_DIRNAME": self.CACHE_MARKDOWN_JUVIX_OUTPUT_DIRNAME,
            "DOCS_DIRNAME": self.DOCS_DIRNAME,
            "DOCS_ABSPATH": self.DOCS_ABSPATH,
            "FIRST_RUN": self.FIRST_RUN,
            "JUVIX_BIN": self.JUVIX_BIN,
            "JUVIX_BIN_NAME": self.JUVIX_BIN_NAME,
            "JUVIX_BIN_PATH": self.JUVIX_BIN_PATH,
            "JUVIX_ENABLED": self.JUVIX_ENABLED,
            "JUVIX_FOOTER_CSS_FILENAME": self.JUVIX_FOOTER_CSS_FILENAME,
            "JUVIX_FOOTER_CSS_FILEPATH": self.JUVIX_FOOTER_CSS_FILEPATH,
            "JUVIX_VERSION": self.JUVIX_VERSION,
            "MIN_JUVIX_VERSION": self.MIN_JUVIX_VERSION,
        }

    def on_config(self, config: MkDocsConfig) -> MkDocsConfig:
        """
        Here, we set up the paths, create the cache directories and check if the
        Juvix binary is available. If the Juvix binary is not available, we set the
        JUVIX_AVAILABLE variable to False. We also set the JUVIX_VERSION variable to
        the version of the Juvix binary.
        """
        config_file = config.config_file_path
        if config.get("use_directory_urls", False):
            log.error(
                "use_directory_urls has been set to True to work with Juvix Markdown files."
            )
            exit(1)

        self.ROOT_ABSPATH = Path(config_file).parent.absolute()
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

        self.force: bool = self.REMOVE_CACHE
        self.FIRST_RUN: bool = True

        directories: List[Path] = [
            self.CACHE_MARKDOWN_JUVIX_OUTPUT_PATH,
            self.CACHE_ORIGINAL_JUVIX_MARKDOWN_FILES_ABSPATH,
            self.CACHE_ABSPATH,
            self.CACHE_HASHES_PATH,
            self.JUVIX_FOOTER_CSS_FILEPATH.parent,
        ]

        for directory in directories:
            if directory.exists() and self.force:
                try:
                    shutil.rmtree(directory, ignore_errors=True)
                except Exception as e:
                    log.error(
                        f"Something went wrong while removing the directory {directory}. Error: {e}"
                    )
            directory.mkdir(parents=True, exist_ok=True)

        self.JUVIX_VERSION = ""
        if self.JUVIX_AVAILABLE:
            full_version_cmd = [self.JUVIX_BIN, "--version"]
            try:
                result = subprocess.run(full_version_cmd, capture_output=True)
                if result.returncode == 0:
                    self.JUVIX_FULL_VERSION = result.stdout.decode("utf-8")
            except Exception as e:
                log.warning(
                    f"Something went wrong while getting the full version of Juvix. Error: {e}"
                )

            numeric_version_cmd = [self.JUVIX_BIN, "--numeric-version"]
            try:
                result = subprocess.run(numeric_version_cmd, capture_output=True)
                if result.returncode == 0:
                    self.JUVIX_VERSION = result.stdout.decode("utf-8")
            except Exception as e:
                log.warning(
                    f"Something went wrong while getting the numeric version of Juvix. Error: {e}"
                )

        if self.JUVIX_VERSION == "":
            log.warning(
                "Juvix version not found. Make sure Juvix is installed, for now support for Juvix Markdown is disabled."
            )
            self.JUVIX_ENABLED = False
            self.JUVIX_AVAILABLE = False
            return config

        if self.MIN_JUVIX_VERSION is not None and Version.parse(
            self.JUVIX_VERSION
        ) < Version.parse(self.MIN_JUVIX_VERSION):
            log.warning(
                f"""Juvix version {self.MIN_JUVIX_VERSION} or higher is required. Please upgrade Juvix and try again."""
            )
            self.JUVIX_ENABLED = False
            self.JUVIX_AVAILABLE = False
            return config

        # Check if we need to create or update the codeblock footer CSS
        version_diff = not self.CACHE_JUVIX_VERSION_FILEPATH.exists() or Version.parse(
            self.CACHE_JUVIX_VERSION_FILEPATH.read_text().strip()
        ) != Version.parse(self.JUVIX_VERSION)

        if version_diff:
            log.info("Writing Juvix version to cache: %s", self.JUVIX_VERSION)
            self.CACHE_JUVIX_VERSION_FILEPATH.write_text(self.JUVIX_VERSION)

        if not self.JUVIX_FOOTER_CSS_FILEPATH.exists() or version_diff:
            log.info("Generating codeblock footer CSS file")
            self._generate_code_block_footer_css_file(
                self.JUVIX_FOOTER_CSS_FILEPATH, self.JUVIX_VERSION
            )
            log.info(
                "Codeblock footer CSS file generated and saved to %s",
                self.JUVIX_FOOTER_CSS_FILEPATH.as_posix(),
            )

        config = fix_site_url(config)
        self.mkconfig = config

        # Add CSS file to extra_css
        css_path = self.JUVIX_FOOTER_CSS_FILEPATH.relative_to(
            self.DOCS_ABSPATH
        ).as_posix()
        if css_path not in self.mkconfig["extra_css"]:
            self.mkconfig["extra_css"].append(css_path)
        log.info("Added CSS file to extra_css: %s", css_path)

        self.juvix_md_files: List[Dict[str, Any]] = []

        self.SITE_DIR = self.mkconfig.get("site_dir", getenv("SITE_DIR", None))
        self.SITE_URL = self.mkconfig.get("site_url", getenv("SITE_URL", ""))

        if not self.JUVIX_AVAILABLE and self.JUVIX_ENABLED:
            log.error(
                """You have requested Juvix but it is not available. Check your configuration.
Environment variables relevant:
- JUVIX_ENABLED
- JUVIX_BIN
- JUVIX_PATH
"""
            )
        return self.mkconfig

    @property
    def juvix_enabled(self) -> bool:
        return self.JUVIX_AVAILABLE and self.JUVIX_ENABLED

    @staticmethod
    def if_juvix_enabled(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if self.juvix_enabled:
                return func(self, *args, **kwargs)
            return None

        return wrapper

    @if_juvix_enabled
    def on_pre_build(self, config: MkDocsConfig) -> None:
        if self.FIRST_RUN:
            try:
                log.info("Updating Juvix dependencies...")
                subprocess.run(
                    [self.JUVIX_BIN, "dependencies", "update"], capture_output=True
                )
                self.FIRST_RUN = False
            except Exception as e:
                log.error(f"A problem occurred while updating Juvix dependencies: {e}")
                return

        for _file in self.DOCS_ABSPATH.rglob("*.juvix.md"):
            file: Path = _file.absolute()
            relative_to: Path = file.relative_to(self.DOCS_ABSPATH)
            url = urljoin(
                self.SITE_URL, relative_to.as_posix().replace(".juvix.md", ".html")
            )
            self.juvix_md_files.append(
                {
                    "module_name": self._unqualified_module_name(file),
                    "qualified_module_name": self._qualified_module_name(file),
                    "url": url,
                    "file": file.absolute().as_posix(),
                }
            )
            self._generate_markdown(file)

        self.juvix_md_files.sort(key=lambda x: x["qualified_module_name"])
        juvix_modules = self.CACHE_ABSPATH.joinpath("juvix_modules.json")

        if juvix_modules.exists():
            juvix_modules.unlink()

        with open(juvix_modules, "w") as f:
            json.dump(self.juvix_md_files, f, indent=4)

        sha_filecontent = (
            self.CACHE_JUVIX_PROJECT_HASH_FILEPATH.read_text()
            if self.CACHE_JUVIX_PROJECT_HASH_FILEPATH.exists()
            else None
        )

        current_sha: str = compute_sha_over_folder(
            self.CACHE_ORIGINAL_JUVIX_MARKDOWN_FILES_ABSPATH
        )
        equal_hashes = current_sha == sha_filecontent

        log.info("Computed Juvix content hash: %s", current_sha)

        if not equal_hashes:
            log.info("Cache Juvix content hash: %s", sha_filecontent)
        else:
            log.info("The Juvix Markdown content has not changed.")

        generate: bool = (
            self.JUVIX_ENABLED
            and self.JUVIX_AVAILABLE
            and (
                not equal_hashes
                or (
                    self.CACHE_HTML_PATH.exists()
                    and (len(list(self.CACHE_HTML_PATH.glob("*"))) == 0)
                )
            )
        )

        if not generate:
            log.info("Skipping Juvix HTML generation for Juvix files.")
        else:
            log.info(
                "Generating auxiliary HTML for Juvix files. This may take a while... It's only generated once per session."
            )

        with open(self.CACHE_JUVIX_PROJECT_HASH_FILEPATH, "w") as f:
            f.write(current_sha)

        self._generate_html(generate=generate, move_cache=True)
        return

    @if_juvix_enabled
    def on_files(self, files: Files, *, config: MkDocsConfig) -> Optional[Files]:
        _files = []
        for file in files:
            if not file.abs_src_path:
                continue
            if ".juvix-build" not in file.abs_src_path:
                _files.append(file)
        return Files(_files)

    @if_juvix_enabled
    def on_nav(self, nav, config: MkDocsConfig, files: Files):
        return nav

    @if_juvix_enabled
    def on_pre_page(self, page: Page, config: MkDocsConfig, files: Files):
        return page

    @if_juvix_enabled
    def on_page_read_source(self, page: Page, config: MkDocsConfig) -> Optional[str]:
        if not page.file.abs_src_path:
            return None

        filepath = Path(page.file.abs_src_path)

        if not filepath.as_posix().endswith(".juvix.md"):
            return None

        output = self._generate_markdown(filepath)
        if not output:
            log.error(f"Error generating markdown for file: {filepath}")
        return output

    @if_juvix_enabled
    def on_page_markdown(
        self, markdown: str, page: Page, config: MkDocsConfig, files: Files
    ) -> Optional[str]:
        path = page.file.abs_src_path
        if path and not path.endswith(".juvix.md"):
            return markdown
        page.file.name = page.file.name.replace(".juvix", "")
        page.file.url = page.file.url.replace(".juvix", "")
        page.file.dest_uri = page.file.dest_uri.replace(".juvix", "")
        page.file.abs_dest_path = page.file.abs_dest_path.replace(".juvix", "")

        metadata = page.meta
        if metadata.get("isabelle", False):
            # isabelle_html = self._generate_isabelle_html(page.file.abs_src_path)
            return markdown
        return markdown

    @if_juvix_enabled
    def on_page_content(
        self, html: str, page: Page, config: MkDocsConfig, files: Files
    ) -> Optional[str]:
        return html

    @if_juvix_enabled
    def on_post_page(self, output: str, page: Page, config: MkDocsConfig) -> str:
        soup = BeautifulSoup(output, "html.parser")
        for a in soup.find_all("a"):
            a["href"] = a["href"].replace(".juvix.html", ".html")
        return str(soup)

    @if_juvix_enabled
    def on_post_build(self, config: MkDocsConfig) -> None:
        self._generate_html(generate=False, move_cache=True)

    @if_juvix_enabled
    def on_serve(self, server: Any, config: MkDocsConfig, builder: Any) -> None:
        gitignore = None
        if (gitignore_file := self.ROOT_ABSPATH / ".gitignore").exists():
            with open(gitignore_file) as file:
                gitignore = pathspec.PathSpec.from_lines(
                    pathspec.patterns.GitWildMatchPattern,  # type: ignore
                    file,  # type: ignore
                )

        def callback_wrapper(
            callback: Callable[[FileSystemEvent], None],
        ) -> Callable[[FileSystemEvent], None]:
            def wrapper(event: FileSystemEvent) -> None:
                if gitignore and gitignore.match_file(
                    Path(event.src_path).relative_to(config.docs_dir).as_posix()  # type: ignore
                ):
                    return

                fpath: Path = Path(event.src_path).absolute()  # type: ignore
                fpathstr: str = fpath.as_posix()

                if ".juvix-build" in fpathstr:
                    return

                if fpathstr.endswith(".juvix.md"):
                    log.debug("Juvix file changed: %s", fpathstr)
                return callback(event)

            return wrapper

        handler = (
            next(
                handler
                for watch, handler in server.observer._handlers.items()
                if watch.path == config.docs_dir
            )
            .copy()
            .pop()
        )
        handler.on_any_event = callback_wrapper(handler.on_any_event)

    # The rest of the methods are for internal use and assume the plugin/juvix is enabled

    def _move_html_cache_to_site_dir(self, filepath: Path, site_dir: Path) -> None:
        rel_to_docs = filepath.relative_to(self.DOCS_ABSPATH)
        dest_folder = (
            site_dir / rel_to_docs
            if filepath.is_dir()
            else site_dir / rel_to_docs.parent
        )

        if not dest_folder.exists():
            log.info(f"Creating directory: {dest_folder}")
            dest_folder.mkdir(parents=True, exist_ok=True)

        # Patch: remove all the .html files in the destination folder of the
        # Juvix Markdown file to not lose the generated HTML files in the site
        # directory.

        for _file in self.CACHE_ORIGINAL_JUVIX_MARKDOWN_FILES_ABSPATH.rglob(
            "*.juvix.md"
        ):
            file = _file.absolute()

            html_file_path = (
                self.CACHE_HTML_PATH
                / file.relative_to(
                    self.CACHE_ORIGINAL_JUVIX_MARKDOWN_FILES_ABSPATH
                ).parent
                / file.name.replace(".juvix.md", ".html")
            )

            if html_file_path.exists():
                log.info(f"Removing file: {html_file_path}")
                html_file_path.unlink()

        index_file = self.CACHE_HTML_PATH / "index.html"
        if index_file.exists():
            index_file.unlink()

        # move the generated HTML files to the site directory
        shutil.copytree(self.CACHE_HTML_PATH, dest_folder, dirs_exist_ok=True)
        return

    def _new_or_changed_or_no_exist(self, filepath: Path) -> bool:
        content_hash = hash_file(filepath)
        path_hash = compute_hash_filepath(filepath, hash_dir=self.CACHE_HASHES_PATH)
        if not path_hash.exists():
            log.debug(f"File: {filepath} does not have a hash file.")
            return True
        fresh_content_hash = path_hash.read_text()
        return content_hash != fresh_content_hash

    def _generate_html(self, generate: bool = True, move_cache: bool = True) -> None:
        everythingJuvix = self.DOCS_ABSPATH.joinpath("everything.juvix.md")
        if not everythingJuvix.exists():
            log.warning(
                """Consider creating a file named 'everything.juvix.md' or \
                'index.juvix.md' in the docs directory to generate the HTML \
                for all Juvix Markdown file. Otherwise, the compiler will \
                generate the HTML for each Juvix Markdown file on each run."""
            )

        files_to_process = (
            self.juvix_md_files
            if not everythingJuvix.exists()
            else [
                {
                    "file": everythingJuvix,
                    "module_name": self._unqualified_module_name(everythingJuvix),
                    "qualified_module_name": self._qualified_module_name(
                        everythingJuvix
                    ),
                    "url": urljoin(self.SITE_URL, everythingJuvix.name).replace(
                        ".juvix.md", ".html"
                    ),
                }
            ]
        )

        for filepath_info in files_to_process:
            filepath = Path(filepath_info["file"])

            if generate:
                self._generate_html_per_file(filepath)
            if self.SITE_DIR and move_cache:
                self._move_html_cache_to_site_dir(filepath, Path(self.SITE_DIR))
        return

    def _generate_html_per_file(
        self, _filepath: Path, remove_cache: bool = False
    ) -> None:
        if remove_cache:
            try:
                shutil.rmtree(self.CACHE_HTML_PATH)
            except Exception as e:
                log.error(f"Error removing folder: {e}")

        self.CACHE_HTML_PATH.mkdir(parents=True, exist_ok=True)

        filepath: Path = _filepath.absolute()

        juvix_html_cmd: List[str] = (
            [self.JUVIX_BIN, "html"]
            + ["--strip-prefix=docs"]
            + ["--folder-structure"]
            + [f"--output-dir={self.CACHE_HTML_PATH.as_posix()}"]
            + [f"--prefix-url={self.SITE_URL}"]
            + [f"--prefix-assets={self.SITE_URL}"]
            + [filepath.as_posix()]
        )

        log.info(f"Juvix call:\n  {' '.join(juvix_html_cmd)}")

        cd = subprocess.run(juvix_html_cmd, cwd=self.DOCS_ABSPATH, capture_output=True)
        if cd.returncode != 0:
            log.error(cd.stderr.decode("utf-8") + "\n\n" + "Fix the error first.")
            return

        # The following is necessary as this project may
        # contain assets with changes that are not reflected
        # in the generated HTML by Juvix.

        good_assets: Path = self.DOCS_ABSPATH / "assets"
        good_assets.mkdir(parents=True, exist_ok=True)

        assets_in_html: Path = self.CACHE_HTML_PATH / "assets"

        if assets_in_html.exists():
            try:
                shutil.rmtree(assets_in_html, ignore_errors=True)
            except Exception as e:
                log.error(f"Error removing folder: {e}")

        try:
            shutil.copytree(good_assets, assets_in_html, dirs_exist_ok=True)
        except Exception as e:
            log.error(f"Error copying folder: {e}")

    @lru_cache(maxsize=128)
    def _get_filepath_for_juvix_markdown_in_cache(
        self, _filepath: Path
    ) -> Optional[Path]:
        filepath = _filepath.absolute()
        md_filename = filepath.name.replace(".juvix.md", ".md")
        rel_to_docs = filepath.relative_to(self.DOCS_ABSPATH)
        return self.CACHE_MARKDOWN_JUVIX_OUTPUT_PATH / rel_to_docs.parent / md_filename

    @lru_cache(maxsize=128)
    def _read_cache(self, filepath: Path) -> Optional[str]:
        if cache_ABSpath := self._get_filepath_for_juvix_markdown_in_cache(filepath):
            return cache_ABSpath.read_text()
        return None

    def _generate_markdown(self, filepath: Path) -> Optional[str]:
        if (
            not self.JUVIX_ENABLED
            or not self.JUVIX_AVAILABLE
            or not filepath.as_posix().endswith(".juvix.md")
        ):
            return None

        if self._new_or_changed_or_no_exist(filepath):
            log.info(f"Running Juvix Markdown on file: {filepath}")
            return self._run_juvix(filepath)

        log.debug(f"Reading cache for file: {filepath}")
        return self._read_cache(filepath)

    def _unqualified_module_name(self, filepath: Path) -> Optional[str]:
        fposix: str = filepath.as_posix()
        if not fposix.endswith(".juvix.md"):
            return None
        return os.path.basename(fposix).replace(".juvix.md", "")

    def _qualified_module_name(self, filepath: Path) -> Optional[str]:
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

    def _get_markdown_filename(self, filepath: Path) -> Optional[str]:
        """
        The markdown filename is the same as the juvix file name but without the .juvix.md extension.
        """
        module_name = self._unqualified_module_name(filepath)
        return module_name + ".md" if module_name else None

    def _run_juvix(self, _filepath: Path) -> Optional[str]:
        filepath = _filepath.absolute()
        fposix: str = filepath.as_posix()

        if not fposix.endswith(".juvix.md"):
            log.debug(f"The file: {fposix} is not a Juvix Markdown file.")
            return None

        rel_to_docs: Path = filepath.relative_to(self.DOCS_ABSPATH)

        juvix_markdown_cmd: List[str] = [
            self.JUVIX_BIN,
            "markdown",
            "--strip-prefix=docs",
            "--folder-structure",
            f"--prefix-url={self.SITE_URL}",
            "--stdout",
            fposix,
            "--no-colors",
        ]
        try:
            result_markdown = subprocess.run(
                juvix_markdown_cmd, cwd=self.DOCS_ABSPATH, capture_output=True
            )
            if result_markdown.returncode != 0:
                # The compiler found an error in the file
                juvix_error_message = (
                    result_markdown.stderr.decode("utf-8").replace("\n", " ").strip()
                )
                log.debug(
                    f"Error running Juvix on file: {fposix} -\n {juvix_error_message}"
                )
                return (
                    f"!!! failure\n\n    {juvix_error_message}\n\n"
                    + filepath.read_text().replace("```juvix", "```")
                )
        except Exception as e:
            log.error(f"Error running Juvix on file: {fposix} -\n {e}")
            return None

        md_output: str = result_markdown.stdout.decode("utf-8")

        cache_markdown_filename: Optional[str] = self._get_markdown_filename(filepath)
        if cache_markdown_filename is None:
            log.debug(f"Could not determine the markdown file name for: {fposix}")
            return None

        cache_markdown_filepath: Path = (
            self.CACHE_MARKDOWN_JUVIX_OUTPUT_PATH
            / rel_to_docs.parent
            / cache_markdown_filename
        )
        cache_markdown_filepath.parent.mkdir(parents=True, exist_ok=True)
        try:
            cache_markdown_filepath.write_text(md_output)
        except Exception as e:
            log.error(f"Error writing to cache markdown file: {e}")
            return None

        self._update_raw_file(filepath)
        self._update_hash_file(filepath)

        return md_output

    def _update_raw_file(self, filepath: Path) -> None:
        raw_path: Path = (
            self.CACHE_ORIGINAL_JUVIX_MARKDOWN_FILES_ABSPATH
            / filepath.relative_to(self.DOCS_ABSPATH)
        )
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy(filepath, raw_path)
        except Exception as e:
            log.error(f"Error copying file: {e}")

    def _update_hash_file(self, filepath: Path) -> Optional[Tuple[Path, str]]:
        filepath_hash = compute_hash_filepath(filepath, hash_dir=self.CACHE_HASHES_PATH)
        try:
            with open(filepath_hash, "w") as f:
                content_hash = hash_file(filepath)
                f.write(content_hash)
                return (filepath_hash, content_hash)
        except Exception as e:
            log.error(f"Error updating hash file: {e}")
            return None

    def _generate_code_block_footer_css_file(
        self, css_file: Path, compiler_version: Optional[str] = None
    ) -> Optional[Path]:
        css_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            if compiler_version is None:
                compiler_version = str(Version.parse(self.JUVIX_VERSION))
            compiler_version = f"Juvix v{compiler_version}".strip()
            css_file.write_text(
                (FIXTURES_PATH / "juvix_codeblock_footer.css")
                .read_text()
                .format(compiler_version=compiler_version)
            )
            log.info(f"CSS file generated at: {css_file.as_posix()}")
        except Exception as e:
            log.error(f"Error writing to CSS file: {e}")
            return None
        return css_file
