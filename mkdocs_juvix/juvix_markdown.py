import json
import shutil
import subprocess
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from os import getenv
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, TypeVar
from urllib.parse import urljoin

import pathspec
import trio
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
from mkdocs_juvix.utils import (
    compute_sha_over_folder,
    fix_site_url,
    is_juvix_markdown_file,
    Tracer,
)

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

T = TypeVar("T")


class JuvixPlugin(BasePlugin):
    mkconfig: MkDocsConfig
    # juvix_md_files: List[Dict[str, Any]]
    env: ENV

    def on_config(self, config: MkDocsConfig) -> MkDocsConfig:
        self.env = ENV(config)
        config = fix_site_url(config)
        self.mkconfig = (
            config  # for internal use, not all methods have config as an argument
        )
        self.env.SITE_DIR = self.mkconfig.get("site_dir", getenv("SITE_DIR", None))
        self.env.SITE_URL = self.mkconfig.get("site_url", getenv("SITE_URL", ""))
        self._add_footer_css_file_to_extra_css()

        self.juvix_md_files: List[Path] = list(self.env.DOCS_ABSPATH.glob("*.juvix.md"))

        if self.env.JUVIX_ENABLED and not self.env.JUVIX_AVAILABLE:
            log.error(
                "You have requested Juvix but it is not available. Check your configuration."
                "\nEnvironment variables relevant to the build process:"
                "\n- JUVIX_ENABLED"
                "\n- JUVIX_BIN"
                "\n- JUVIX_PATH"
            )

        self.update_juvix_dependencies()
        return config

    @property
    def juvix_enabled(self) -> bool:
        return self.env.JUVIX_ENABLED and self.env.JUVIX_AVAILABLE

    @staticmethod
    def when_juvix_enabled(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if self.juvix_enabled:
                return func(self, *args, **kwargs)
            return None

        return wrapper

    async def process_juvix_markdown_file(self, filepath: Path) -> None:
        """
        Process a Juvix Markdown file and generate the corresponding HTML file.
        Returns True if the file was processed successfully and the cache was
        updated.
        """
        if not is_juvix_markdown_file(filepath):
            return None

        file_abs_path: Path = filepath.absolute()
        file_path_rel_to_docs: Path = file_abs_path.relative_to(self.env.DOCS_ABSPATH)

        file_url: str = urljoin(
            self.env.SITE_URL,
            file_path_rel_to_docs.as_posix().replace(".juvix.md", ".html"),
        )

        output: Optional[str] = await self._get_output_for_juvix_markdown(file_abs_path)

        if not output:
            log.error(
                f"Failed to generate output for {Fore.GREEN}{file_abs_path}{Style.RESET_ALL}"
            )
            return None

        metadata = {
            "module_name": self.env.unqualified_module_name(file_abs_path),
            "qualified_module_name": self.env.qualified_module_name(file_abs_path),
            "url": file_url,
            "file": file_abs_path.absolute().as_posix(),
        }

        # self.juvix_md_files.append(metadata)

    async def run_in_parallel(self, func, files_to_process: List[Path]) -> None:
        time_start = time.time()
        async with trio.open_nursery() as nursery:
            try:
                for input_file in files_to_process:
                    nursery.start_soon(func, input_file)
            except trio.Cancelled:
                log.error("Process was cancelled")

        time_end = time.time()
        log.info(
            f"Processed {Fore.GREEN}{len(files_to_process)}{Style.RESET_ALL} "
            f"files in parallel in {Fore.GREEN}{time_end - time_start:.2f}{Style.RESET_ALL} seconds"
        )

    def clean_juvix_dependencies(self) -> None:
        try:
            log.info("Cleaning Juvix dependencies for the first time...")
            res = subprocess.run(
                [
                    self.env.JUVIX_BIN,
                    "clean",
                    # "--global"
                ],
                cwd=self.env.DOCS_ABSPATH,
                capture_output=True,
            )
            if res.returncode != 0:
                log.error(
                    "A problem occurred when trying to clean Juvix dependencies: "
                    + res.stderr.decode("utf-8")
                )
            time.sleep(1)  # wait for the next run
        except Exception as e:
            log.error(f"A problem occurred while cleaning Juvix dependencies: {e}")

    def update_juvix_dependencies(self) -> bool:
        self.clean_juvix_dependencies()
        try:
            log.info("Updating Juvix dependencies...")
            time_start = time.time()
            res = subprocess.run(
                [self.env.JUVIX_BIN, "dependencies", "update"],
                cwd=self.env.DOCS_ABSPATH,
                capture_output=True,
            )
            time_end = time.time()
            if res.returncode != 0:
                log.error(
                    "A problem occurred when trying to update Juvix dependencies: "
                    + res.stderr.decode("utf-8")
                )
                return False
            else:
                log.info(
                    f"Updated Juvix dependencies in {Fore.GREEN}{time_end - time_start:.2f}{Style.RESET_ALL} seconds"
                )
        except Exception as e:
            log.error(f"A problem occurred while updating Juvix dependencies: {e}")
            return False
        return True

    async def preprocess_juvix_md_files(self) -> None:
        self.juvix_md_files = list(self.env.DOCS_ABSPATH.rglob("*.juvix.md"))[:3]

        log.info(
            f"{Fore.YELLOW}==== Preprocessing {Fore.GREEN}{len(self.juvix_md_files)}{Fore.YELLOW} "
            f"Juvix Markdown files in parallel ===={Style.RESET_ALL}"
        )
        time_start = time.time()
        async with trio.open_nursery() as nursery:
            try:
                for input_file in self.juvix_md_files:
                    nursery.start_soon(self.process_juvix_markdown_file, input_file)
            except trio.Cancelled:
                log.error("Process was cancelled")

        time_end = time.time()
        log.info(
            f"Processed {Fore.GREEN}{len(self.juvix_md_files)}{Style.RESET_ALL} "
            f"files in parallel in {Fore.GREEN}{time_end - time_start:.2f}{Style.RESET_ALL} seconds"
        )

    def on_pre_build(self, config: MkDocsConfig) -> None:
        # self.metadata_for_juvix_md_files: List[Dict[str, Any]] = []

        # aim to be fault-tolerant, so we don't care if some files fail
        # typechecking as part of the markdown processing, we include the error
        # message as part of the content of the page

        trio.run(self.preprocess_juvix_md_files
                #  , instruments=[Tracer()]
                 )

        exit(1)

        # check all the cached files exist
        for metadata in self.metadata_for_juvix_md_files:
            cached_filepath = (
                self.env.get_filepath_for_cache_markdown_output_of_juvix_markdown_file(
                    Path(metadata["file"])
                )
            )
            if not cached_filepath.exists():
                log.error(f"[!] Cached file not found for {metadata['file']}")

        self.metadata_for_juvix_md_files.sort(
            key=lambda x: x.get("qualified_module_name", "")
        )

        juvix_modules = self.env.CACHE_ABSPATH / "juvix_modules.json"
        juvix_modules.write_text(json.dumps(self.metadata_for_juvix_md_files, indent=2))

        hash_compund_of_juvix_markdown_files: Optional[str] = (
            self.env.CACHE_JUVIX_PROJECT_HASH_FILEPATH.read_text()
            if self.env.CACHE_JUVIX_PROJECT_HASH_FILEPATH.exists()
            else None
        )
        # The current hash is computed over the original Juvix Markdown files that are in the original
        current_sha: Optional[str] = compute_sha_over_folder(
            self.env.CACHE_ORIGINAL_JUVIX_MARKDOWN_FILES_ABSPATH
        )

        equal_hashes = current_sha == hash_compund_of_juvix_markdown_files

        if not equal_hashes:
            log.info(
                f"Computed hash for Juvix Markdown files: "
                f"{Fore.MAGENTA}{current_sha}{Style.RESET_ALL}"
            )
            log.info(
                f"Previous computed hash: "
                f"{Fore.MAGENTA}{hash_compund_of_juvix_markdown_files}{Style.RESET_ALL}"
            )
        else:
            log.info("The Juvix Markdown content has not changed.")

        generate: bool = self.juvix_enabled and (
            not equal_hashes
            or (
                self.env.CACHE_HTML_PATH.exists()
                and (len(list(self.env.CACHE_HTML_PATH.glob("*"))) == 0)
            )
        )

        if not generate:
            log.info(
                f"{Fore.GREEN}Skipping Juvix HTML generation for Juvix files.{Style.RESET_ALL}"
            )
        else:
            log.debug(
                "Generating auxiliary HTML for Juvix files."
                "This may take a while... It's only generated once per session."
            )

        if current_sha:
            self.env.CACHE_JUVIX_PROJECT_HASH_FILEPATH.write_text(current_sha)
        self._generate_html(generate=generate, move_cache=True)
        return

    @when_juvix_enabled
    def on_files(self, files: Files, *, config: MkDocsConfig) -> Optional[Files]:
        _files = []
        for file in files:
            if not file.abs_src_path:
                continue
            if ".juvix-build" not in file.abs_src_path:
                _files.append(file)
        return Files(_files)

    @when_juvix_enabled
    def on_nav(self, nav, config: MkDocsConfig, files: Files):
        return nav

    @when_juvix_enabled
    def on_pre_page(self, page: Page, config: MkDocsConfig, files: Files) -> Page:
        return page

    @when_juvix_enabled
    def on_page_read_source(self, page: Page, config: MkDocsConfig) -> Optional[str]:
        filepath: Optional[str] = page.file.abs_src_path
        if filepath and is_juvix_markdown_file(Path(filepath)):
            file_abs_path: Path = Path(filepath).absolute()
            file_rel_to_docs_path: Path = file_abs_path.relative_to(
                self.env.DOCS_ABSPATH
            )

            cached_filepath: Path = (
                self.env.get_filepath_for_cache_markdown_output_of_juvix_markdown_file(
                    file_abs_path
                )
            )

            if cached_filepath.exists():
                return cached_filepath.read_text()
            else:
                log.error(
                    f"Cached file not found for {file_rel_to_docs_path}"
                    f"\nWas expecting it to be at {cached_filepath}"
                )

        return None

    @when_juvix_enabled
    def on_page_markdown(
        self, markdown: str, page: Page, config: MkDocsConfig, files: Files
    ) -> Optional[str]:
        path: Optional[str] = page.file.abs_src_path

        if path and not is_juvix_markdown_file(Path(path)):
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

    @when_juvix_enabled
    def on_page_content(
        self, html: str, page: Page, config: MkDocsConfig, files: Files
    ) -> Optional[str]:
        return html

    @when_juvix_enabled
    def on_post_page(self, output: str, page: Page, config: MkDocsConfig) -> str:
        soup = BeautifulSoup(output, "html.parser")
        for a in soup.find_all("a"):
            a["href"] = a["href"].replace(".juvix.html", ".html")
        return str(soup)

    @when_juvix_enabled
    def on_post_build(self, config: MkDocsConfig) -> None:
        self._generate_html(generate=False, move_cache=True)

    @when_juvix_enabled
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
                f"""Consider creating a file named {Fore.GREEN}'everything.juvix.md'{Style.RESET_ALL} or \
                {Fore.GREEN}'index.juvix.md'{Style.RESET_ALL} in the docs directory to generate the HTML \
                for all Juvix Markdown file". Otherwise, the compiler will \
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
            f"Generated Auxiliary HTML in "
            f"{Fore.GREEN}{time_end - time_start:.5f}{Style.RESET_ALL} seconds"
        )

        return

    def _generate_html_per_file(
        self, filepath: Path, remove_cache: bool = False
    ) -> None:
        if remove_cache:
            try:
                shutil.rmtree(self.env.CACHE_HTML_PATH)
            except Exception as e:
                log.error(f"Error removing folder: {e}")

        self.env.CACHE_HTML_PATH.mkdir(parents=True, exist_ok=True)

        file_abs_path: Path = filepath.absolute()

        juvix_html_cmd: List[str] = [
            self.env.JUVIX_BIN,
            "html",
            "--strip-prefix",
            self.env.DOCS_DIRNAME,
            "--folder-structure",
            "--output-dir",
            self.env.CACHE_HTML_PATH.as_posix(),
            "--prefix-url",
            self.env.SITE_URL,
            "--prefix-assets",
            self.env.SITE_URL,
            file_abs_path.as_posix(),
        ]

        time_start = time.time()

        cd = subprocess.run(
            juvix_html_cmd,
            cwd=self.env.DOCS_ABSPATH,
            capture_output=True,
        )
        time_end = time.time()
        log.info(
            f"Time taken to run Juvix HTML: "
            f"{Fore.GREEN}{time_end - time_start:.2f}{Style.RESET_ALL} seconds"
        )
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

    async def _generate_isabelle_html(self, filepath: Path) -> Optional[str]:
        if not filepath.as_posix().endswith(".juvix.md"):
            return None

        # check the theory file in the cache
        isabelle_filepath = (
            self.env.get_expected_filepath_for_juvix_isabelle_output_in_cache(filepath)
        )
        cache_available: bool = (
            isabelle_filepath is not None and isabelle_filepath.exists()
        )

        if not cache_available or self.env.is_file_new_or_changed_for_cache(filepath):
            log.info(f"No Isabelle file in cache for {filepath}")
            return await self._run_juvix_isabelle(filepath)

        if isabelle_filepath is None:
            log.error(f"Isabelle filepath not found for {filepath}")
            return None
        return isabelle_filepath.read_text()

    async def _get_output_for_juvix_markdown(self, filepath: Path) -> Optional[str]:
        """
        Generate the output files for a Juvix Markdown file. It returns the
        content of the Markdown file processed with the Juvix compiler. If the
        filepath provided is not a JuvixMarkdown file or something goes wrong,
        it returns None.
        """
        if not is_juvix_markdown_file(filepath):
            return None

        file_abs_path: Path = filepath.absolute()
        file_path_rel_to_docs: Path = file_abs_path.relative_to(self.env.DOCS_ABSPATH)

        cache_filepath: Path = (
            self.env.get_filepath_for_cache_markdown_output_of_juvix_markdown_file(
                filepath
            )
        )

        if (
            not self.env.is_file_new_or_changed_for_cache(filepath)
            and cache_filepath.exists()
        ):
            log.info(
                f"Using cached file for {Fore.GREEN}{file_path_rel_to_docs}{Style.RESET_ALL}"
            )
            return cache_filepath.read_text()

        log.info(f"Running Juvix Markdown on {file_path_rel_to_docs}")

        time_start = time.time()
        markdown_output: Optional[str] = None
        with trio.move_on_after(4):
            try:
                res: Optional[
                    Tuple[int, str, str]
                ] = await self._async_run_juvix_markdown(file_abs_path)
                if res :
                    returncode, stdout, stderr = res
                    markdown_output = stdout
            except trio.TooSlowError as e:
                log.error(f"Too slow to run Juvix Markdown on {file_abs_path}: {e}")
            except trio.Cancelled as e:
                log.error(f"Cancelled running Juvix Markdown on {file_abs_path}: {e}")
        time_end = time.time()

        log.info(
            f"Finished processing {Fore.GREEN}{file_path_rel_to_docs}{Style.RESET_ALL} "
            f"in {Fore.GREEN}{time_end - time_start:.2f}s{Style.RESET_ALL}"
        )

        if not markdown_output:
            return None

        try:
            if not cache_filepath.exists():
                cache_filepath.parent.mkdir(parents=True, exist_ok=True)
                cache_filepath.write_text(markdown_output)
        except Exception as e:
            log.error(f"Error writing to cache file: {e}")

        try:
            self.env.update_cache_for_file(filepath, markdown_output)
        except Exception as e:
            log.error(f"Error updating cache for file: {e}")

        try:
            self.save_original_juvix_markdown_in_cache(
                filepath
            )  # necessary to have the original file in cache if something goes wrong
        except Exception as e:
            log.error(f"Error saving original Juvix Markdown file in cache: {e}")

        return markdown_output

    async def needs_isabelle_processing(
        self, filepath: Path, markdown_output: Optional[str]
    ) -> bool:
        filepath_abs = filepath.absolute()
        if not filepath_abs.exists():
            log.error(f"File {filepath_abs} does not exist")
            return False

        if markdown_output is None:
            markdown_output = filepath_abs.read_text()

        metadata_block = markdown_output.split("---")
        if len(metadata_block) < 3:
            return False

        metadata = metadata_block[1].strip()
        try:
            metadata = yaml.safe_load(metadata)
        except Exception as e:
            log.error(f"Error parsing metadata block: {e}")
            return False

        if not isinstance(metadata, dict):
            return False

        isabelle_meta = metadata.get("isabelle")
        if not isinstance(isabelle_meta, dict):
            return False

        requires_isabelle = isabelle_meta.get("generate", False) or metadata.get(
            "isabelle", False
        )
        include_isabelle_at_bottom = isabelle_meta.get("include_at_bottom", False)

        return requires_isabelle or include_isabelle_at_bottom

    async def process_isabelle(self, filepath: Path, markdown_output: str) -> str:
        try:
            log.info(f"Generating Isabelle theory for {filepath}")
            isabelle_html = await self._generate_isabelle_html(filepath)
            if isabelle_html:
                markdown_output += isabelle_html
        except Exception as e:
            log.error(f"Error generating Isabelle HTML for {filepath}: {e}")

        return markdown_output

    async def _run_juvix_isabelle(self, _filepath: Path) -> Optional[str]:
        file_abspath: Path = _filepath.absolute()
        file_rel_to_docs = file_abspath.relative_to(self.env.DOCS_ABSPATH)

        if not is_juvix_markdown_file(file_abspath):
            log.debug(f"The file: {file_rel_to_docs} is not a Juvix Markdown file.")
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
            file_abspath.as_posix(),
        ]

        try:
            log.info(f"Running Juvix Isabelle on file: {file_rel_to_docs}")
            result_isabelle = await trio.run_process(
                juvix_isabelle_cmd,
                cwd=self.env.DOCS_ABSPATH,
                check=False,
                capture_stdout=True,
                capture_stderr=True,
            )

            if result_isabelle.returncode != 0:
                juvix_isabelle_error_message = (
                    result_isabelle.stderr.decode("utf-8").replace("\n", " ").strip()
                )
                log.warning(
                    f"Error running Juvix Isabelle on file: {file_rel_to_docs}\n"
                    f"{juvix_isabelle_error_message}"
                )
                return (
                    f"!!! failure 'When translating to Isabelle, "
                    f"the Juvix compiler found the following error:'\n\n"
                    f"    {juvix_isabelle_error_message}\n\n"
                )

        except Exception as e:
            log.error(
                f"Error running Juvix to Isabelle pass on file: {file_rel_to_docs}\n {e}"
            )
            return None

        cache_isabelle_filepath: Optional[Path] = (
            self.env.get_expected_filepath_for_juvix_isabelle_output_in_cache(
                file_abspath
            )
        )

        if cache_isabelle_filepath is None:
            log.debug(
                f"Could not determine the Isabelle file name for: {file_rel_to_docs}"
            )
            return None

        cache_isabelle_filepath.parent.mkdir(parents=True, exist_ok=True)
        isabelle_output: str = result_isabelle.stdout.decode("utf-8")

        try:
            isabelle_output = self._fix_unclosed_snippet_annotations(isabelle_output)
            cache_isabelle_filepath.write_text(isabelle_output)
            return isabelle_output
        except Exception as e:
            log.error(f"Error writing to cache Isabelle file: {e}")
            return None

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

    # def _sync_run_juvix_markdown(self, filepath: Path) -> Optional[str]:
    #     file_abs_path: Path = filepath.absolute()
    #     file_rel_to_docs: Path = file_abs_path.relative_to(self.env.DOCS_ABSPATH)

    #     if not is_juvix_markdown_file(file_abs_path):
    #         log.debug(f"The file: {file_rel_to_docs} is not a Juvix Markdown file.")
    #         return None

    #     juvix_markdown_cmd: List[str] = [
    #         self.env.JUVIX_BIN,
    #         "markdown",
    #         "--strip-prefix=docs",
    #         "--folder-structure",
    #         f"--prefix-url={self.env.SITE_URL}",
    #         "--stdout",
    #         file_abs_path.as_posix(),
    #         "--no-colors",
    #         # "--offline",
    #         # "--internal-build-dir",
    #         # (self.env.ROOT_ABSPATH / ".juvix-build").as_posix(),
    #     ]

    #     result_markdown = None
    #     try:
    #         result_markdown = subprocess.run(
    #             juvix_markdown_cmd,
    #             cwd=self.env.DOCS_ABSPATH,
    #             check=True,
    #             capture_output=True,
    #             text=True,
    #         )
    #         time.sleep(1)

    #         returncode = result_markdown.returncode
    #         stdout = result_markdown.stdout
    #         stderr = result_markdown.stderr

    #         # log.info(f"returncode: {result_markdown.returncode}")
    #         # log.info(f"stdout: {Fore.MAGENTA}{stdout}{Style.RESET_ALL}")
    #         # log.info(f"stderr: {Fore.YELLOW}{stderr}{Style.RESET_ALL}")

    #         if returncode == 0:
    #             return stdout

    #         # The compiler found an error in the file
    #         juvix_error_message: str = stderr.replace("\n", " ").strip()
    #         log.error(
    #             f"Error when typechecking the Juvix Markdown file: "
    #             f"{Fore.GREEN}{file_rel_to_docs}{Style.RESET_ALL}\n"
    #             f"{juvix_error_message}"
    #         )

    #         formatted_error_message = (
    #             f"<details class='failure'><summary>When typechecking the Juvix Markdown file, "
    #             f"the Juvix compiler found the following error:</summary>\n\n"
    #             f"<pre><code>\n"
    #             f"    {textwrap.fill(juvix_error_message, width=70)}\n"
    #             f"</code></pre></details>\n\n"
    #         )

    #         metadata_block = filepath.read_text().split("---")
    #         if len(metadata_block) > 2:
    #             return f"{metadata_block[0]}\n{formatted_error_message}\n{metadata_block[2]}"
    #         else:
    #             return f"{formatted_error_message}\n\n{filepath.read_text()}"

    #     except Exception as e:
    #         log.error(
    #             f"Error running the following command: {Fore.GREEN}{' '.join(juvix_markdown_cmd)}{Style.RESET_ALL}\n\nError:{e}"
    #         )

    #     return None

    async def _async_run_juvix_markdown(
        self, filepath: Path
    ) -> Optional[Tuple[int, str, str]]:
        """
        It returns the output of the Juvix compiler when processing a Juvix Markdown file.
        If the file is not a Juvix Markdown file, it returns None.
        If there is an error, it returns the error message formatted as a Markdown
        details block. Otherwise, it returns None.
        """
        file_abs_path: Path = filepath.absolute()
        file_rel_to_docs: Path = file_abs_path.relative_to(self.env.DOCS_ABSPATH)

        if not is_juvix_markdown_file(file_abs_path):
            log.info(f"The file: {file_rel_to_docs} is not a Juvix Markdown file.")
            return None

        juvix_markdown_cmd: List[str] = [
            self.env.JUVIX_BIN,
            "--log-level=error",
            "markdown",
            "--strip-prefix",
            self.env.DOCS_DIRNAME,
            "--folder-structure",
            "--prefix-url",
            self.env.SITE_URL,
            "--stdout",
            file_abs_path.as_posix(),
        ]
        # "--no-colors",
        # "--offline",
        # "--internal-build-dir",
        # "--log-level",
        # "error",
        # (self.env.ROOT_ABSPATH / ".juvix-build").as_posix(),

        result_markdown = None
        try:
            result_markdown = await trio.run_process(
                juvix_markdown_cmd,
                cwd=self.env.ROOT_ABSPATH,
                # check=True,
                # shell=True,
                capture_stdout=True,
                capture_stderr=True,
            )
            log.info(f"result_markdown: {result_markdown}")
            returncode = result_markdown.returncode
            stdout = result_markdown.stdout.decode("utf-8")
            stderr = result_markdown.stderr.decode("utf-8")
            
            return (returncode, stdout, stderr)

        except Exception as e:
            cmd = juvix_markdown_cmd
            if isinstance(cmd, list):
                cmd = " ".join(cmd)  # type: ignore

            log.error(
                f"[!] Failed to run the following command:\n"
                f"{Fore.GREEN}{cmd}{Style.RESET_ALL}\n\n"
                f"Error:{e}"
            )
        return None

    def save_original_juvix_markdown_in_cache(self, filepath: Path) -> None:
        filepath_abs = filepath.absolute()
        filepath_rel_to_docs = filepath_abs.relative_to(self.env.DOCS_ABSPATH)
        raw_path: Path = (
            self.env.CACHE_ORIGINAL_JUVIX_MARKDOWN_FILES_ABSPATH / filepath_rel_to_docs
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
        except Exception as e:
            log.error(f"Error writing to CSS file: {e}")
            return None
        return css_file

    def _add_footer_css_file_to_extra_css(self) -> None:
        css_file = self.env.JUVIX_FOOTER_CSS_FILEPATH
        # Check if we need to create or update the codeblock footer CSS
        needs_to_update_cached_juvix_version = (
            not self.env.CACHE_JUVIX_VERSION_FILEPATH.exists()
            or Version.parse(self.env.CACHE_JUVIX_VERSION_FILEPATH.read_text().strip())
            != Version.parse(self.env.JUVIX_VERSION)
        )
        if needs_to_update_cached_juvix_version:
            log.info(
                f"Writing Juvix version to cache: "
                f"{Fore.GREEN}{self.env.JUVIX_VERSION}{Style.RESET_ALL}"
            )
            self.env.CACHE_JUVIX_VERSION_FILEPATH.write_text(self.env.JUVIX_VERSION)

        if not css_file.exists() or needs_to_update_cached_juvix_version:
            self._generate_code_block_footer_css_file(css_file, self.env.JUVIX_VERSION)
            log.info(
                f"Codeblock footer CSS file generated and saved to "
                f"{Fore.GREEN}{css_file.as_posix()}{Style.RESET_ALL}"
            )

        # Add CSS file to extra_css
        css_path = css_file.relative_to(self.env.DOCS_ABSPATH)

        if css_path not in self.mkconfig["extra_css"]:
            self.mkconfig["extra_css"].append(css_path.as_posix())
