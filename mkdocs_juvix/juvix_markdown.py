import json
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, wait
from functools import wraps
from os import getenv
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin

import pathspec
import yaml  # type:ignore
from bs4 import BeautifulSoup  # type:ignore
from colorama import Fore, Style  # type: ignore
from dotenv import load_dotenv
from mkdocs.config.defaults import MkDocsConfig
from mkdocs.plugins import BasePlugin, get_plugin_logger
from mkdocs.structure.files import Files
from mkdocs.structure.pages import Page
from semver import Version
from watchdog.events import FileSystemEvent

from mkdocs_juvix.env import ENV, FIXTURES_PATH
from mkdocs_juvix.snippets import RE_SNIPPET_SECTION
from mkdocs_juvix.utils import compute_sha_over_folder, fix_site_url

load_dotenv()

log = get_plugin_logger(f"{Fore.BLUE}[juvix_mkdocs-to-markdown]{Style.RESET_ALL}")

_pipeline: str = """ For reference, the Mkdocs Pipeline is the following:
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


class JuvixPlugin(BasePlugin):
    mkconfig: MkDocsConfig
    juvix_md_files: List[Dict[str, Any]]
    env: ENV

    def on_config(self, config: MkDocsConfig) -> MkDocsConfig:
        self.env = ENV(config)
        self.env.FIRST_RUN = True

        # Check if we need to create or update the codeblock footer CSS
        version_diff = (
            not self.env.CACHE_JUVIX_VERSION_FILEPATH.exists()
            or Version.parse(self.env.CACHE_JUVIX_VERSION_FILEPATH.read_text().strip())
            != Version.parse(self.env.JUVIX_VERSION)
        )

        if version_diff:
            log.info("Writing Juvix version to cache: %s", self.env.JUVIX_VERSION)
            self.env.CACHE_JUVIX_VERSION_FILEPATH.write_text(self.env.JUVIX_VERSION)

        if not self.env.JUVIX_FOOTER_CSS_FILEPATH.exists() or version_diff:
            log.info("Generating codeblock footer CSS file")
            self._generate_code_block_footer_css_file(
                self.env.JUVIX_FOOTER_CSS_FILEPATH, self.env.JUVIX_VERSION
            )
            log.info(
                "Codeblock footer CSS file generated and saved to %s",
                self.env.JUVIX_FOOTER_CSS_FILEPATH.as_posix(),
            )

        config = fix_site_url(config)
        self.mkconfig = config

        # Add CSS file to extra_css
        css_path = self.env.JUVIX_FOOTER_CSS_FILEPATH.relative_to(
            self.env.DOCS_ABSPATH
        ).as_posix()

        if css_path not in self.mkconfig["extra_css"]:
            self.mkconfig["extra_css"].append(css_path)
        self.juvix_md_files: List[Dict[str, Any]] = []

        self.env.SITE_DIR = self.mkconfig.get("site_dir", getenv("SITE_DIR", None))
        self.env.SITE_URL = self.mkconfig.get("site_url", getenv("SITE_URL", ""))

        if not self.env.JUVIX_AVAILABLE and self.env.JUVIX_ENABLED:
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
        return self.env.JUVIX_AVAILABLE and self.env.JUVIX_ENABLED

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
        if self.env.FIRST_RUN:
            try:
                time_start = time.time()
                subprocess.run(
                    [self.env.JUVIX_BIN, "dependencies", "update"], capture_output=True
                )
                time_end = time.time()
                log.info(
                    f"Updated Juvix dependencies in {Fore.GREEN}{time_end - time_start:.2f}{Style.RESET_ALL} seconds"
                )
                self.env.FIRST_RUN = False
            except Exception as e:
                log.error(f"A problem occurred while updating Juvix dependencies: {e}")
                return

        time_start = time.time()

        def process_file(_file: Path) -> None:
            filepath: Path = _file.absolute()
            relative_to: Path = filepath.relative_to(self.env.DOCS_ABSPATH)
            url = urljoin(
                self.env.SITE_URL, relative_to.as_posix().replace(".juvix.md", ".html")
            )
            self.juvix_md_files.append(
                {
                    "module_name": self.env.unqualified_module_name(filepath),
                    "qualified_module_name": self.env.qualified_module_name(filepath),
                    "url": url,
                    "file": filepath.absolute().as_posix(),
                }
            )
            self._generate_output_files_for_juvix_markdown(filepath)

        juvix_md_files = list(self.env.DOCS_ABSPATH.rglob("*.juvix.md"))
        log.info(
            f"==== Processing {Fore.GREEN}{len(juvix_md_files)}{Style.RESET_ALL} Juvix Markdown files ===="
        )

        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(process_file, file) for file in juvix_md_files]

        # Wait for all futures to complete
        wait(futures)
        for juvix_md_file in juvix_md_files:
            if not juvix_md_file.exists():
                log.error(
                    f"Juvix Markdown file not found: {Fore.RED}{juvix_md_file}{Style.RESET_ALL}"
                )
                exit(1)
        log.info("Finished processing all Juvix Markdown files")

        # exit(1)
        time_end = time.time()

        log.info(
            f"Generated Markdown for {Fore.GREEN}{len(self.juvix_md_files)}{Style.RESET_ALL} Juvix Markdown files in {Fore.GREEN}{time_end - time_start:.2f}{Style.RESET_ALL} seconds"
        )
        self.juvix_md_files.sort(key=lambda x: x["qualified_module_name"])
        juvix_modules = self.env.CACHE_ABSPATH.joinpath("juvix_modules.json")
        juvix_modules.write_text(json.dumps(self.juvix_md_files, indent=4))

        sha_filecontent = (
            self.env.CACHE_JUVIX_PROJECT_HASH_FILEPATH.read_text()
            if self.env.CACHE_JUVIX_PROJECT_HASH_FILEPATH.exists()
            else None
        )

        current_sha: str = compute_sha_over_folder(
            self.env.CACHE_ORIGINAL_JUVIX_MARKDOWN_FILES_ABSPATH
        )
        equal_hashes = current_sha == sha_filecontent
        log.info(
            f"Computed Hash for Juvix Markdown files: {Fore.MAGENTA}{current_sha}{Style.RESET_ALL}"
        )

        if not equal_hashes:
            log.info(
                f"The hashes are different! (previous: {Fore.MAGENTA}{sha_filecontent}{Style.RESET_ALL})"
            )
        else:
            log.info("The Juvix Markdown content has not changed.")

        generate: bool = (
            self.env.JUVIX_ENABLED
            and self.env.JUVIX_AVAILABLE
            and (
                not equal_hashes
                or (
                    self.env.CACHE_HTML_PATH.exists()
                    and (len(list(self.env.CACHE_HTML_PATH.glob("*"))) == 0)
                )
            )
        )

        if not generate:
            log.info(
                f"{Fore.GREEN}Skipping Juvix HTML generation for Juvix files.{Style.RESET_ALL}"
            )
        else:
            log.debug(
                "Generating auxiliary HTML for Juvix files. This may take a while... It's only generated once per session."
            )

        with open(self.env.CACHE_JUVIX_PROJECT_HASH_FILEPATH, "w") as f:
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
    def on_pre_page(self, page: Page, config: MkDocsConfig, files: Files) -> Page:
        return page

    @if_juvix_enabled
    def on_page_read_source(self, page: Page, config: MkDocsConfig) -> Optional[str]:
        if not page.file.abs_src_path:
            return None

        filepath = Path(page.file.abs_src_path)

        if not filepath.as_posix().endswith(".juvix.md"):
            return None

        return self._generate_output_files_for_juvix_markdown(filepath)

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

        required_isabelle_output: Optional[dict | bool] = page.meta.get("isabelle")
        include_isabelle_at_bottom = False

        if isinstance(required_isabelle_output, dict):
            include_isabelle_at_bottom = required_isabelle_output.get(
                "include_at_bottom", False
            )

        if include_isabelle_at_bottom:
            log.debug(f"Including Isabelle at the bottom of {page.file.name}")
            src_path = page.file.abs_src_path
            if not src_path:
                return markdown
            filepath = Path(src_path)
            isabelle_path = (
                self.env.get_expected_filepath_for_juvix_isabelle_output_in_cache(
                    filepath
                )
            )
            if isabelle_path and not isabelle_path.exists():
                log.error(
                    f"Isabelle output file not found for {page.file.name}. Try to build the project again."
                )
                return markdown

            if isabelle_path and include_isabelle_at_bottom:
                return markdown + (
                    FIXTURES_PATH / "isabelle_at_bottom.md"
                ).read_text().format(
                    filename=page.file.name,
                    block_title=page.file.name,
                    isabelle_html=isabelle_path.read_text(),
                    juvix_version=self.env.JUVIX_VERSION,
                )
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
        if (gitignore_file := self.env.ROOT_ABSPATH / ".gitignore").exists():
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
        rel_to_docs = filepath.relative_to(self.env.DOCS_ABSPATH)
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

        for _file in self.env.CACHE_ORIGINAL_JUVIX_MARKDOWN_FILES_ABSPATH.rglob(
            "*.juvix.md"
        ):
            file = _file.absolute()

            html_file_path = (
                self.env.CACHE_HTML_PATH
                / file.relative_to(
                    self.env.CACHE_ORIGINAL_JUVIX_MARKDOWN_FILES_ABSPATH
                ).parent
                / file.name.replace(".juvix.md", ".html")
            )

            if html_file_path.exists():
                log.debug(f"Removing file: {html_file_path}")
                html_file_path.unlink()

        index_file = self.env.CACHE_HTML_PATH / "index.html"
        if index_file.exists():
            index_file.unlink()

        # move the generated HTML files to the site directory
        shutil.copytree(self.env.CACHE_HTML_PATH, dest_folder, dirs_exist_ok=True)
        return

    def _generate_html(self, generate: bool = True, move_cache: bool = True) -> None:
        everythingJuvix = self.env.DOCS_ABSPATH.joinpath("everything.juvix.md")
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
                    "module_name": self.env.unqualified_module_name(everythingJuvix),
                    "qualified_module_name": self.env.qualified_module_name(
                        everythingJuvix
                    ),
                    "url": urljoin(self.env.SITE_URL, everythingJuvix.name).replace(
                        ".juvix.md", ".html"
                    ),
                }
            ]
        )

        def process_file(filepath_info: dict) -> None:
            filepath = Path(filepath_info["file"])

            if generate:
                self._generate_html_per_file(filepath)
            if self.env.SITE_DIR and move_cache:
                self._move_html_cache_to_site_dir(filepath, Path(self.env.SITE_DIR))

        time_start = time.time()
        with ThreadPoolExecutor() as executor:
            executor.map(process_file, files_to_process)
            executor.shutdown(wait=True)
        time_end = time.time()
        log.info(
            f"\033[92mGenerated HTML for {len(files_to_process)} files in {time_end - time_start} seconds\033[0m"
        )

        return

    def _generate_html_per_file(
        self, _filepath: Path, remove_cache: bool = False
    ) -> None:
        if remove_cache:
            try:
                shutil.rmtree(self.env.CACHE_HTML_PATH)
            except Exception as e:
                log.error(f"Error removing folder: {e}")

        self.env.CACHE_HTML_PATH.mkdir(parents=True, exist_ok=True)

        filepath: Path = _filepath.absolute()

        juvix_html_cmd: List[str] = (
            [self.env.JUVIX_BIN, "html"]
            + ["--strip-prefix=docs"]
            + ["--folder-structure"]
            + [f"--output-dir={self.env.CACHE_HTML_PATH.as_posix()}"]
            + [f"--prefix-url={self.env.SITE_URL}"]
            + [f"--prefix-assets={self.env.SITE_URL}"]
            + [filepath.as_posix()]
        )

        log.info(f"{' '.join(juvix_html_cmd)}")

        time_start = time.time()

        cd = subprocess.run(
            juvix_html_cmd, cwd=self.env.DOCS_ABSPATH, capture_output=True
        )
        time_end = time.time()
        log.info(f"Time taken to run Juvix HTML: {time_end - time_start} seconds")
        if cd.returncode != 0:
            log.error(cd.stderr.decode("utf-8") + "\n\n" + "Fix the error first.")
            return

        # The following is necessary as this project may
        # contain assets with changes that are not reflected
        # in the generated HTML by Juvix.

        good_assets: Path = self.env.DOCS_ABSPATH / "assets"
        good_assets.mkdir(parents=True, exist_ok=True)

        assets_in_html: Path = self.env.CACHE_HTML_PATH / "assets"

        if assets_in_html.exists():
            try:
                shutil.rmtree(assets_in_html, ignore_errors=True)
            except Exception as e:
                log.error(f"Error removing folder: {e}")

        try:
            shutil.copytree(good_assets, assets_in_html, dirs_exist_ok=True)
        except Exception as e:
            log.error(f"Error copying folder: {e}")

    def _generate_isabelle_html(self, filepath: Path) -> Optional[str]:
        if not filepath.as_posix().endswith(".juvix.md"):
            return None

        # check the theory file in the cache
        isabelle_filepath = (
            self.env.get_expected_filepath_for_juvix_isabelle_output_in_cache(filepath)
        )
        cache_available: bool = (
            isabelle_filepath is not None and isabelle_filepath.exists()
        )

        if not cache_available or self.env.new_or_changed_or_not_exists(filepath):
            log.info(f"No Isabelle file in cache for {filepath}")
            return self._run_juvix_isabelle(filepath)

        if isabelle_filepath is None:
            log.error(f"Isabelle filepath not found for {filepath}")
            return None
        return isabelle_filepath.read_text()

    @if_juvix_enabled
    def _generate_output_files_for_juvix_markdown(
        self, filepath: Path
    ) -> Optional[str]:
        if not filepath.as_posix().endswith(".juvix.md"):
            return None

        new_or_changed = self.env.new_or_changed_or_not_exists(filepath)

        if not new_or_changed:
            log.debug(f"Reading cached file for: {filepath}")
            if cache_filepath := self.env.get_filepath_for_juvix_markdown_in_cache(
                filepath
            ):
                return cache_filepath.read_text()
        markdown_output = self._run_juvix_markdown(filepath)
        try:
            content = filepath.read_text()
            # Extract metadata block checking it has exist it may not be
            metadata_block = content.split("---")
            if len(metadata_block) < 3:
                return markdown_output

            metadata = metadata_block[1].strip()
            try:
                metadata = yaml.safe_load(metadata)
                if isinstance(metadata, dict):
                    isabelle_meta = metadata.get("isabelle", {})
                    if not isinstance(isabelle_meta, dict):
                        isabelle_meta = {}

                    generate_isabelle = isabelle_meta.get(
                        "generate", False
                    ) or metadata.get("isabelle", False)

                    include_isabelle_at_bottom = isabelle_meta.get(
                        "include_at_bottom", False
                    )
                    if generate_isabelle or include_isabelle_at_bottom:
                        try:
                            log.info(f"Generating Isabelle HTML for {filepath}")
                            self._generate_isabelle_html(filepath)
                        except Exception as e:
                            log.error(
                                f"Error generating Isabelle HTML for {filepath}: {e}"
                            )

            except Exception as e:
                log.error(f"Error parsing metadata block: {e}")
                return markdown_output

        except Exception as e:
            log.error(f"Error generating Isabelle output files for {filepath}: {e}")

        return markdown_output

    def _run_juvix_isabelle(self, _filepath: Path) -> Optional[str]:
        filepath: Path = _filepath.absolute()
        fposix: str = filepath.as_posix()

        if not fposix.endswith(".juvix.md"):
            log.debug(f"The file: {fposix} is not a Juvix Markdown file.")
            return None

        juvix_isabelle_cmd: List[str] = [
            self.env.JUVIX_BIN,
            "--log-level=error",
            "isabelle",
        ]
        if "Branch: fix-implicit-record-args" in self.env.JUVIX_FULL_VERSION:
            juvix_isabelle_cmd += ["--non-recursive"]

        juvix_isabelle_cmd += [
            "--stdout",
            "--output-dir",
            self.env.CACHE_ISABELLE_OUTPUT_PATH.as_posix(),
            fposix,
        ]

        try:
            log.info(f"Running Juvix Isabelle on file: {fposix}")
            result_isabelle = subprocess.run(
                juvix_isabelle_cmd, cwd=self.env.DOCS_ABSPATH, capture_output=True
            )

            if result_isabelle.returncode != 0:
                juvix_isabelle_error_message = (
                    result_isabelle.stderr.decode("utf-8").replace("\n", " ").strip()
                )
                log.warning(
                    f"Error running Juvix Isabelle on file: {fposix} -\n {juvix_isabelle_error_message}"
                )
                return f"!!! failure 'When translating to Isabelle, the Juvix compiler found the following error:'\n\n    {juvix_isabelle_error_message}\n\n"

        except Exception as e:
            log.error(f"Error running Juvix to Isabelle pass on file: {fposix} -\n {e}")
            return None

        cache_isabelle_filepath: Optional[Path] = (
            self.env.get_expected_filepath_for_juvix_isabelle_output_in_cache(filepath)
        )

        if cache_isabelle_filepath is None:
            log.debug(f"Could not determine the Isabelle file name for: {fposix}")
            return None

        cache_isabelle_filepath.parent.mkdir(parents=True, exist_ok=True)

        isabelle_output: str = result_isabelle.stdout.decode("utf-8")

        try:
            isabelle_output = self._fix_unclosed_snippet_annotations(isabelle_output)
            cache_isabelle_filepath.write_text(isabelle_output)
        except Exception as e:
            log.error(f"Error writing to cache Isabelle file: {e}")
            return None
        return isabelle_output

    # TODO: remove when the compiler respects the closing annotation in the comments
    def _fix_unclosed_snippet_annotations(self, isabelle_output: str) -> str:
        # process each line of the output and if the line matches RE
        lines = isabelle_output.split("\n")
        counted_lines = len(lines)
        closed_successfully = False
        JLine: Optional[int] = None
        for i, _l in enumerate(lines):
            m = RE_SNIPPET_SECTION.match(_l)
            if m and m.group("type") == "start":
                section_name = m.group("name")
                closed_successfully = False
                JLine = None
                for j in range(i + 1, counted_lines):
                    if lines[j].strip() == "" and JLine is not None:
                        JLine = j
                    if (
                        (m2 := RE_SNIPPET_SECTION.match(lines[j]))
                        and m2.group("type") == "end"
                        and m2.group("name") == section_name
                    ):
                        closed_successfully = True
                        break
                if not closed_successfully and JLine:
                    lines[JLine] = lines[JLine].replace("start", "end")
                    log.warning("Could not close the last opened snippet section")
                    return isabelle_output
        return "\n".join(lines)

    def _run_juvix_markdown(self, _filepath: Path) -> Optional[str]:
        filepath = _filepath.absolute()
        fposix: str = filepath.as_posix()

        if not fposix.endswith(".juvix.md"):
            log.debug(f"The file: {fposix} is not a Juvix Markdown file.")
            return None

        rel_to_docs: Path = filepath.relative_to(self.env.DOCS_ABSPATH)

        juvix_markdown_cmd: List[str] = [
            self.env.JUVIX_BIN,
            "markdown",
            "--strip-prefix=docs",
            "--folder-structure",
            f"--prefix-url={self.env.SITE_URL}",
            "--stdout",
            fposix,
            "--no-colors",
        ]
        try:
            log.info(
                f"Generating Markdown for {Fore.GREEN}'{filepath.relative_to(self.env.DOCS_ABSPATH)}'{Style.RESET_ALL}"
            )
            result_markdown = subprocess.run(
                juvix_markdown_cmd, cwd=self.env.DOCS_ABSPATH, capture_output=True
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
                    f"!!! failure 'When typechecking the Juvix Markdown file, the Juvix compiler found the following error:'\n\n    {juvix_error_message}\n\n"
                    + filepath.read_text().replace("```juvix", "```")
                )
        except Exception as e:
            log.error(f"Error running Juvix on file: {fposix} -\n {e}")
            return None

        md_output: str = result_markdown.stdout.decode("utf-8")

        cache_markdown_filename: Optional[str] = (
            self.env.get_filename_module_by_extension(filepath, extension=".md")
        )

        if cache_markdown_filename is None:
            log.debug(f"Could not determine the markdown file name for: {fposix}")
            return None

        cache_markdown_filepath: Path = (
            self.env.CACHE_MARKDOWN_JUVIX_OUTPUT_PATH
            / rel_to_docs.parent
            / cache_markdown_filename
        )
        cache_markdown_filepath.parent.mkdir(parents=True, exist_ok=True)

        try:
            cache_markdown_filepath.write_text(md_output)
        except Exception as e:
            log.error(f"Error writing to cache markdown file: {e}")
            return md_output

        self._update_markdown_file_as_in_docs(filepath)
        self.env.update_hash_file(filepath)
        return md_output

    def _update_markdown_file_as_in_docs(self, filepath: Path) -> None:
        raw_path: Path = (
            self.env.CACHE_ORIGINAL_JUVIX_MARKDOWN_FILES_ABSPATH
            / filepath.relative_to(self.env.DOCS_ABSPATH)
        )
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy(filepath, raw_path)
        except Exception as e:
            log.error(f"Error copying file: {e}")

    def _generate_code_block_footer_css_file(
        self, css_file: Path, compiler_version: Optional[str] = None
    ) -> Optional[Path]:
        css_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            if compiler_version is None:
                compiler_version = str(Version.parse(self.env.JUVIX_VERSION))
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
