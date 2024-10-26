import json
import shutil
import subprocess
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from os import getenv
from pathlib import Path
from typing import List, Optional, Dict, Any, TypeVar
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

from mkdocs.plugins import PrefixedLogger
from mkdocs_juvix.env import ENV, FIXTURES_PATH
from mkdocs_juvix.snippets import RE_SNIPPET_SECTION
from mkdocs_juvix.utils import (
    compute_sha_over_folder,
    fix_site_url,
    is_juvix_markdown_file,
    hash_content_of,
    time_spent as time_spent_decorator,
)

load_dotenv()

log : PrefixedLogger = get_plugin_logger(f"{Fore.BLUE}[juvix_mkdocs]{Style.RESET_ALL}")

def time_spent(message: Optional[Any] = None, print_result: bool = False):
    return time_spent_decorator(log = log, message = message, print_result = print_result)

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


class JuvixRelatedClass:
    def __init__(self, env: ENV):
        self.env: ENV = env
    
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

class JuvixMarkdownFile(JuvixRelatedClass):
    """
    A class that represents a Juvix Markdown file.
    """

    def __init__(self, filepath: Path, env: ENV):
        super().__init__(env)
        try:
            self.absolute_filepath: Path = filepath.absolute()
            self.relative_filepath: Path = self.absolute_filepath.relative_to(
                env.DOCS_ABSPATH
            )
            self.url: str = urljoin(env.SITE_URL, self.relative_filepath.as_posix().replace(".juvix.md", ".html"))
            self.module_name: Optional[str] = env.unqualified_module_name(filepath)
            self.qualified_module_name: Optional[str] = env.qualified_module_name(
                filepath
            )
            self.needs_isabelle: bool = False  # This can be determined later if needed
            self._markdown_output: Optional[str] = None
            self.cache_filepath: Path = (
                env.get_filepath_for_cache_markdown_output_of_juvix_markdown_file(
                    filepath
                )
            )
            self.hash_cache_filepath: Path = (
                env.get_expected_filepath_for_cached_hash_for(self.absolute_filepath)
            )
        except Exception as e:
            log.error(f"Error initializing JuvixMarkdownFile: {e}")
            raise

    def __str__(self) -> str:
        return f"{Fore.GREEN}{self.relative_filepath}{Style.RESET_ALL}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filepath": self.absolute_filepath.as_posix(),
            "module_name": self.module_name,
            "qualified_module_name": self.qualified_module_name,
            "url": self.url,
            "needs_isabelle": self.needs_isabelle,
            "content_hash": self.hash,
        }

    @property
    def hash_in_cache(self) -> str:
        if self.is_cached() and self.hash_cache_filepath.exists():
            return self.hash_cache_filepath.read_text().strip()
        else:
            return ""

    @property
    def hash(self) -> str:
        return hash_content_of(self.absolute_filepath)

    @property
    @time_spent(message="> reading markdown output")
    def markdown_output(self) -> Optional[str]:
        if self._markdown_output is None:
            try:
                self._markdown_output = self.generate_markdown_output()
            except Exception as e:
                log.error(f"Error generating markdown output: {e}")
                return None
        return self._markdown_output

    def is_cached(self) -> bool:
        return self.cache_filepath.exists()

    @time_spent(message="> checking if file exists in docs folder", print_result=True)
    def exists(self) -> bool:
        return self.absolute_filepath.exists()

    @time_spent(message="> checking if file changed", print_result=True)
    def changed_since_last_run(self) -> bool:
        if not self.is_cached():
            return True
        try:
            return self.env.is_file_new_or_changed_for_cache(self.absolute_filepath)
        except Exception as e:
            log.error(f"Error checking if file changed: {e}")
            return True

    def _build_juvix_markdown_command(self) -> List[str]:
        return [
            self.env.JUVIX_BIN,
            "--log-level=error",
            "markdown",
            "--strip-prefix",
            self.env.DOCS_DIRNAME,
            "--folder-structure",
            "--prefix-url",
            self.env.SITE_URL,
            "--stdout",
            self.absolute_filepath.as_posix(),
            "--no-colors",
        ]

    @time_spent(message="> running juvix markdown")
    def _run_juvix_markdown(self) -> Optional[str]:
        """
        Return the output of the Juvix Markdown command (--stdout).
        """
        try:
            result = subprocess.run(
                self._build_juvix_markdown_command(),
                cwd=self.env.DOCS_ABSPATH,
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            log.error(f"Error running Juvix Markdown on {self}: {e}")
            return None
        except Exception as e:
            log.error(f"Unexpected error running Juvix Markdown on {self}: {e}")
            return None

    @time_spent(message="> reading cached markdown")
    def read_cached_markdown(self) -> Optional[str]:
        if self.is_cached() and not self.changed_since_last_run():
            return self.cache_filepath.read_text()
        return None

    @time_spent(message="> generating markdown output")
    def generate_markdown_output(self, save: bool = True) -> Optional[str]:
        try:
            if cached_markdown := self.read_cached_markdown():
                return cached_markdown

            markdown_output = self._run_juvix_markdown()
            if markdown_output and save:
                self.save_markdown_output(markdown_output)
            return markdown_output
        except Exception as e:
            log.error(f"Error generating markdown output: {e}")
            return None

    @property
    def excerpt(self, length: int = 300, width: int = 80) -> Optional[str]:
        """
        Return the first `length` characters of the markdown output.
        Width `width` characters.
        """
        if self.markdown_output:
            return textwrap.fill(self.markdown_output[:length], width=width)
        else:
            return None

    @time_spent(message="> saving markdown output in cache", print_result=True)
    def save_markdown_output(self, md_output: str) -> Optional[Path]:
        try:
            self._markdown_output = md_output
            self.cache_filepath.parent.mkdir(parents=True, exist_ok=True)
            self.cache_filepath.write_text(md_output)
            self.env.update_hash_file(self.absolute_filepath)
            return self.cache_filepath.relative_to(self.env.ROOT_ABSPATH)
        except Exception as e:
            log.error(f"Error saving markdown output: {e}")
            return None
    
    def _build_juvix_html_command(self) -> List[str]:
        return [
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
            self.absolute_filepath.as_posix(),
        ]

    @time_spent()
    def generate_html(self, update_assets: bool = False) -> None:
        self.env.CACHE_HTML_PATH.mkdir(parents=True, exist_ok=True)
        try:
            output = subprocess.run(
                self._build_juvix_html_command(),
                cwd=self.env.DOCS_ABSPATH,
                check=True,
                capture_output=True,
                text=True,
            )

            if output.returncode != 0:
                raise Exception(output.stderr)

            if update_assets:
                self._update_assets()
            else:
                log.info("HTML generation completed but not saved to disk.")
        except subprocess.CalledProcessError as e:
            log.error(f"Error running Juvix HTML command on {self}: {e}")
        except Exception as e:
            log.error(f"Unexpected error during HTML generation: {e}")

    @time_spent(message="> updating assets")
    def _update_assets(self) -> None:
        assets_path = self.env.DOCS_ABSPATH / "assets"
        assets_path.mkdir(parents=True, exist_ok=True)

        assets_in_html_path = self.env.CACHE_HTML_PATH / "assets"

        if assets_in_html_path.exists():
            self.env.remove_directory(assets_in_html_path)

        self.env.copy_directory(assets_path, assets_in_html_path)

    def needs_isabelle_processing(self, markdown_output: Optional[str] = None) -> bool:
        if not self.exists():
            log.error(f"File {self} does not exist")
            return False

        if markdown_output is None:
            markdown_output = self.absolute_filepath.read_text()

        metadata = self.extract_metadata(markdown_output)
        if not metadata:
            return False

        isabelle_meta = metadata.get("isabelle", {})
        if not isinstance(isabelle_meta, dict):
            return False

        requires_isabelle = isabelle_meta.get("generate", False) or metadata.get(
            "isabelle", False
        )
        include_isabelle_at_bottom = isabelle_meta.get("include_at_bottom", False)

        return requires_isabelle or include_isabelle_at_bottom

    def extract_metadata(self, content: str) -> Optional[dict]:
        metadata_block = content.split("---")
        if len(metadata_block) < 3:
            return None

        try:
            return yaml.safe_load(metadata_block[1].strip())
        except Exception as e:
            log.error(f"Error parsing metadata block: {e}")
            return None

    def generate_isabelle_output(self, modify_markdown_output: bool = True) -> None:
        log.info(f"Generating Isabelle theory for {self}")
        if not self.exists():
            log.debug(f"The file: {self} does not exist")
            return

        result_isabelle = subprocess.run(
            self._build_juvix_isabelle_command(),
            cwd=self.env.DOCS_ABSPATH,
            check=False,
            capture_output=True,
            text=True,
        )

        isabelle_html = self._process_isabelle_result(result_isabelle)

        if isabelle_html and modify_markdown_output and self._markdown_output:
            self._markdown_output += isabelle_html
        return

    def _build_juvix_isabelle_command(self) -> List[str]:
        cmd = [
            self.env.JUVIX_BIN,
            "--log-level=error",
            "isabelle",
            "--stdout",
            "--output-dir",
            self.env.CACHE_ISABELLE_OUTPUT_PATH.as_posix(),
            self.absolute_filepath.as_posix(),
        ]
        if "Branch: fix-implicit-record-args" in self.env.JUVIX_FULL_VERSION:
            cmd.insert(3, "--non-recursive")
        return cmd

    def _process_isabelle_result(
        self, result: subprocess.CompletedProcess
    ) -> Optional[str]:
        if result.returncode != 0:
            error_message = result.stderr.replace("\n", " ").strip()
            log.warning(
                f"Error running Juvix Isabelle on file: {self.relative_filepath}\n{error_message}"
            )
            return f"!!! failure 'When translating to Isabelle, the Juvix compiler found the following error:'\n\n    {error_message}\n\n"

        cached_isabelle_filepath = (
            self.env.get_expected_filepath_for_juvix_isabelle_output_in_cache(
                self.absolute_filepath
            )
        )

        if not cached_isabelle_filepath:
            log.debug(
                f"Could not determine the Isabelle file name for: {self.relative_filepath}"
            )
            return None

        isabelle_output = self._fix_unclosed_snippet_annotations(result.stdout)
        try:
            cached_isabelle_filepath.parent.mkdir(parents=True, exist_ok=True)
            cached_isabelle_filepath.write_text(isabelle_output)
            return isabelle_output
        except Exception as e:
            log.error(f"Error writing to cache Isabelle file: {e}")
            return None

    def _fix_unclosed_snippet_annotations(self, isabelle_output: str) -> str:
        lines = isabelle_output.split("\n")
        stack = []
        for i, line in enumerate(lines):
            m = RE_SNIPPET_SECTION.match(line)
            if m:
                if m.group("type") == "start":
                    stack.append((i, m.group("name")))
                elif m.group("type") == "end":
                    if stack and stack[-1][1] == m.group("name"):
                        stack.pop()
                    else:
                        log.warning(f"Mismatched end tag at line {i+1}")

        while stack:
            start_index, name = stack.pop()
            for j in range(start_index + 1, len(lines)):
                if lines[j].strip() == "":
                    lines[j] = f"(* snippet {name} end *)"
                    log.warning(
                        f"Added missing end tag for snippet '{name}' at line {j+1}"
                    )
                    break
            else:
                log.warning(
                    f"Could not find a place to add missing end tag for snippet '{name}'"
                )

        return "\n".join(lines)


class JuvixMarkdownCollection(JuvixRelatedClass):
    def __init__(self, env: ENV, folder: Optional[Path] = None):
        super().__init__(env)
        try:
            self.folder: Path = folder or env.DOCS_ABSPATH
            self.cache_original_juvix_markdown_files_folder: Path = (
                env.CACHE_ORIGINAL_JUVIX_MARKDOWN_FILES_ABSPATH
            )
            self.files: List[JuvixMarkdownFile] = self._get_juvix_markdown_files()
            self.everything_html_file: JuvixMarkdownFile = JuvixMarkdownFile(
                self.folder / "everything.juvix.md", self.env
            )
            self._current_hash: Optional[str] = None
            self._stored_hash: Optional[str] = None

        except Exception as e:
            log.error(f"Error initializing JuvixMarkdownCollection: {e}")
            raise

    @time_spent(message="> checking if everything file exists", print_result=True)
    def exists_everything_file(self) -> bool:
        try:
            return self.everything_html_file.absolute_filepath.exists()
        except Exception as e:
            log.error(f"Error checking if everything file exists: {e}")
            return False

    def _get_juvix_markdown_files(self) -> List[JuvixMarkdownFile]:
        try:
            return [
                JuvixMarkdownFile(file, self.env)
                for file in self.folder.rglob("*.juvix.md")
            ]
        except Exception as e:
            log.error(f"Error getting Juvix Markdown files: {e}")
            return []

    def _compute_hash(self) -> str:
        try:
            return compute_sha_over_folder(
                self.cache_original_juvix_markdown_files_folder
            )
        except Exception as e:
            log.error(f"Error computing hash: {e}")
            return ""

    def _get_stored_hash(self) -> Optional[str]:
        hash_project_filepath = self.env.CACHE_JUVIX_PROJECT_HASH_FILEPATH
        if not hash_project_filepath.exists():
            return None
        try:
            return hash_project_filepath.read_text().strip()
        except Exception as e:
            log.error(f"Error getting stored hash: {e}")
            return None

    @property
    def hash(self) -> str:
        if self._current_hash is None:
            self._current_hash = self._compute_hash()
        return self._current_hash

    @time_spent(message="Did Juvix Markdown files change?", print_result=True)
    def has_changes(self) -> bool:
        try:
            if self._stored_hash is None:
                self._stored_hash = self._get_stored_hash()

            if self._stored_hash is None:
                log.info("No stored hash found. Assuming changes.")
                return True

            if self.hash != self._stored_hash:
                log.info("Changes detected in Juvix Markdown files.")
                return True
            else:
                log.info("No changes detected in Juvix Markdown files.")
                return False
        except Exception as e:
            log.error(f"Error checking for changes: {e}")
            return True  # Assume changes if there's an error

    @time_spent(message="> updating stored hash", print_result=True)
    def update_stored_hash(self) -> Optional[Path]:
        try:
            self.env.CACHE_JUVIX_PROJECT_HASH_FILEPATH.write_text(self.hash)
            self._stored_hash = self.hash
            return self.env.CACHE_JUVIX_PROJECT_HASH_FILEPATH.relative_to(self.env.ROOT_ABSPATH)
        except Exception as e:
            log.error(f"Error updating stored hash: {e}")
            return None

    @time_spent(message="> checking if html cache is empty", print_result=True)
    def html_cache_is_empty(self) -> bool:
        """On the post build, we must move the cache to the site folder"""
        return len(list(self.env.CACHE_HTML_PATH.glob("*"))) == 0

    @time_spent(message="> saving juvix modules json", print_result=True)
    def save_juvix_modules_json(self) -> Optional[Path]:
        try:
            json_path = self.env.CACHE_ABSPATH / "juvix_modules.json"
            json_content = json.dumps([file.to_dict() for file in self.files], indent=2)
            json_path.write_text(json_content)
            return json_path.relative_to(self.env.ROOT_ABSPATH)
        except Exception as e:
            log.error(f"Error saving juvix_modules.json: {e}")
            return None

    @time_spent()
    def process_files_pipeline(self, markdown=True, isabelle=True, html=True) -> None:
        try:
            log.info(f"Processing {len(self.files)} files...")
            for file in self.files:
                if markdown:
                    log.info(f"Processing markdown for {file}")
                    file.generate_markdown_output(save=True)
                if isabelle:
                    log.info(f"Processing Isabelle for {file}")
                    file.generate_isabelle_output(modify_markdown_output=markdown)
            log.info(f"Total Juvix Markdown files processed: {Fore.GREEN}{len(self.files)}{Style.RESET_ALL}")
            if html:
                log.info("Adding auxiliary files to the HTML...")
                self.generate_html()
                
            log.info("Extra steps...")
            self.update_stored_hash()
            self.save_juvix_modules_json()
        except Exception as e:
            log.error(f"Error processing files: {e}")

    @time_spent(message="> removing html cache")
    def _remove_html_cache(self) -> None:
        try:
            shutil.rmtree(self.env.CACHE_HTML_PATH)
        except Exception as e:
            log.error(f"Error removing HTML cache folder: {e}")

    @time_spent(message="> generating html")
    def generate_html(self) -> None:
        try:
            if self.html_cache_is_empty():
                if self.exists_everything_file():
                    self.everything_html_file.generate_html(update_assets=True)
                else:
                    log.info(f"{Fore.YELLOW}Generating HTML per file... (Recommend to create an `everything.juvix.md` file at the level of the docs folder){Style.RESET_ALL}")
                    for file in self.files:
                        file.generate_html(update_assets=True)
            else:
                log.info(
                    "No changes detected in Juvix Markdown files. Skipping HTML generation."
                )
        except Exception as e:
            log.error(f"Error generating HTML: {e}")

    @time_spent()
    def clean_juvix_dependencies(self) -> None:
        if not self.env.CLEAN_DEPS:
            log.info("Skipping Juvix dependencies cleaning because CLEAN_DEPS is not set.")
            return

        try:
            res = subprocess.run(
                [self.env.JUVIX_BIN, "clean", "--global"],
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

    @time_spent(message="> updating juvix dependencies", print_result=True)
    def update_juvix_dependencies(self) -> bool:
        try:
            res = subprocess.run(
                [self.env.JUVIX_BIN, "dependencies", "update"],
                cwd=self.env.DOCS_ABSPATH,
                capture_output=True,
            )
            if res.returncode != 0:
                log.error(
                    "A problem occurred when trying to update Juvix dependencies: "
                    + res.stderr.decode("utf-8")
                )
                return False
        except Exception as e:
            log.error(f"A problem occurred while updating Juvix dependencies: {e}")
            return False
        return True


class JuvixPlugin(BasePlugin):
    mkconfig: MkDocsConfig
    env: ENV
    juvix_md_collection: JuvixMarkdownCollection

    def on_config(self, config: MkDocsConfig) -> MkDocsConfig:
        self.env = ENV(config)
        config = fix_site_url(config)
        self.mkconfig = config
        self.env.SITE_DIR = self.mkconfig.get("site_dir", getenv("SITE_DIR", None))
        self.env.SITE_URL = self.mkconfig.get("site_url", getenv("SITE_URL", ""))
        # self._add_footer_css_file_to_extra_css()

        self.juvix_md_collection = JuvixMarkdownCollection(self.env)

        if self.env.JUVIX_ENABLED and not self.env.JUVIX_AVAILABLE:
            log.error(
                "You have requested Juvix but it is not available. Check your configuration."
                "\nEnvironment variables relevant to the build process:"
                "\n- JUVIX_ENABLED"
                "\n- JUVIX_BIN"
                "\n- JUVIX_PATH"
            )
        else:
            log.info("Juvix is enabled and available.")

            self.juvix_md_collection.update_juvix_dependencies()
        return config


    def _format_error_message_for_material(
        self, error_message: str, filepath: Path
    ) -> str:
        formatted_error_message = (
            f"<details class='failure'><summary>Juvix Markdown Error:</summary>\n\n"
            f"<pre><code>\n"
            f"    {textwrap.fill(error_message, width=70)}\n"
            f"</code></pre></details>\n\n"
        )

        metadata_block = filepath.read_text().split("---")
        if len(metadata_block) > 2:
            return (
                f"{metadata_block[0]}\n{formatted_error_message}\n{metadata_block[2]}"
            )
        else:
            return f"{formatted_error_message}\n\n{filepath.read_text()}"

    def on_pre_build(self, config: MkDocsConfig) -> None:
        # aim to be fault-tolerant, so we don't care if some files fail
        # typechecking as part of the markdown processing, we include the error
        # message as part of the content of the page

        self.juvix_md_collection.process_files_pipeline(
            markdown=True, isabelle=False, html=True
        )

        exit(1)


    # @when_juvix_enabled
    # def on_files(self, files: Files, *, config: MkDocsConfig) -> Optional[Files]:
    #     return Files([file for file in files if ".juvix-build" not in file.abs_src_path])

    # @when_juvix_enabled
    # def on_nav(self, nav, config: MkDocsConfig, files: Files):
    #     return nav

    # @when_juvix_enabled
    # def on_pre_page(self, page: Page, config: MkDocsConfig, files: Files) -> Page:
    #     return page

    # @when_juvix_enabled
    # def on_page_read_source(self, page: Page, config: MkDocsConfig) -> Optional[str]:
    #     filepath: Optional[str] = page.file.abs_src_path
    #     if filepath and is_juvix_markdown_file(Path(filepath)):
    #         file = self.juvix_md_collection.get_file(Path(filepath))
    #         if file:
    #             return file.get_cached_content()
    #         else:
    #             log.error(f"File not found in collection: {filepath}")
    #     return None

    # @when_juvix_enabled
    # def on_page_markdown(
    #     self, markdown: str, page: Page, config: MkDocsConfig, files: Files
    # ) -> Optional[str]:
    #     path: Optional[str] = page.file.abs_src_path

    #     if path and not is_juvix_markdown_file(Path(path)):
    #         return markdown

    #     page.file.name = page.file.name.replace(".juvix", "")
    #     page.file.url = page.file.url.replace(".juvix", "")
    #     page.file.dest_uri = page.file.dest_uri.replace(".juvix", "")
    #     page.file.abs_dest_path = page.file.abs_dest_path.replace(".juvix", "")

    #     required_isabelle_output: Optional[dict | bool] = page.meta.get("isabelle")
    #     include_isabelle_at_bottom = False

    #     if isinstance(required_isabelle_output, dict):
    #         include_isabelle_at_bottom = required_isabelle_output.get(
    #             "include_at_bottom", False
    #         )

    #     if include_isabelle_at_bottom:
    #         log.debug(f"Including Isabelle at the bottom of {page.file.name}")
    #         src_path = page.file.abs_src_path
    #         if not src_path:
    #             return markdown
    #         file = self.juvix_md_collection.get_file(Path(src_path))
    #         if file:
    #             isabelle_content = file.get_isabelle_content()
    #             if isabelle_content:
    #                 return markdown + (
    #                     FIXTURES_PATH / "isabelle_at_bottom.md"
    #                 ).read_text().format(
    #                     filename=page.file.name,
    #                     block_title=page.file.name,
    #                     isabelle_html=isabelle_content,
    #                     juvix_version=self.env.JUVIX_VERSION,
    #                 )
    #             else:
    #                 log.error(
    #                     f"Isabelle output file not found for {page.file.name}. Try to build the project again."
    #                 )
    #     return markdown

    # @when_juvix_enabled
    # def on_page_content(
    #     self, html: str, page: Page, config: MkDocsConfig, files: Files
    # ) -> Optional[str]:
    #     return html

    # @when_juvix_enabled
    # def on_post_page(self, output: str, page: Page, config: MkDocsConfig) -> str:
    #     soup = BeautifulSoup(output, "html.parser")
    #     for a in soup.find_all("a"):
    #         a["href"] = a["href"].replace(".juvix.html", ".html")
    #     return str(soup)

    # @when_juvix_enabled
    # def on_post_build(self, config: MkDocsConfig) -> None:
    #     self._generate_html(generate=False, move_cache=True)

    # @when_juvix_enabled
    # def on_serve(self, server: Any, config: MkDocsConfig, builder: Any) -> None:
    #     gitignore = None
    #     if (gitignore_file := self.env.ROOT_ABSPATH / ".gitignore").exists():
    #         with open(gitignore_file) as file:
    #             gitignore = pathspec.PathSpec.from_lines(
    #                 pathspec.patterns.GitWildMatchPattern,  # type: ignore
    #                 file,  # type: ignore
    #             )

    #     def callback_wrapper(
    #         callback: Callable[[FileSystemEvent], None],
    #     ) -> Callable[[FileSystemEvent], None]:
    #         def wrapper(event: FileSystemEvent) -> None:
    #             if gitignore and gitignore.match_file(
    #                 Path(event.src_path).relative_to(config.docs_dir).as_posix()  # type: ignore
    #             ):
    #                 return

    #             fpath: Path = Path(event.src_path).absolute()  # type: ignore
    #             fpathstr: str = fpath.as_posix()

    #             if ".juvix-build" in fpathstr:
    #                 return

    #             if fpathstr.endswith(".juvix.md"):
    #                 log.debug("Juvix file changed: %s", fpathstr)
    #             return callback(event)

    #         return wrapper

    #     handler = (
    #         next(
    #             handler
    #             for watch, handler in server.observer._handlers.items()
    #             if watch.path == config.docs_dir
    #         )
    #         .copy()
    #         .pop()
    #     )
    #     handler.on_any_event = callback_wrapper(handler.on_any_event)

    # # The rest of the methods are for internal use and assume the plugin/juvix is enabled

    # def _move_html_cache_to_site_dir(self, filepath: Path, site_dir: Path) -> None:
    #     rel_to_docs = filepath.relative_to(self.env.DOCS_ABSPATH)
    #     dest_folder = (
    #         site_dir / rel_to_docs
    #         if filepath.is_dir()
    #         else site_dir / rel_to_docs.parent
    #     )

    #     if not dest_folder.exists():
    #         log.info(f"Creating directory: {dest_folder}")
    #         dest_folder.mkdir(parents=True, exist_ok=True)

    #     # Patch: remove all the .html files in the destination folder of the
    #     # Juvix Markdown file to not lose the generated HTML files in the site
    #     # directory.

    #     for _file in self.env.CACHE_ORIGINAL_JUVIX_MARKDOWN_FILES_ABSPATH.rglob(
    #         "*.juvix.md"
    #     ):
    #         file = _file.absolute()

    #         html_file_path = (
    #             self.env.CACHE_HTML_PATH
    #             / file.relative_to(
    #                 self.env.CACHE_ORIGINAL_JUVIX_MARKDOWN_FILES_ABSPATH
    #             ).parent
    #             / file.name.replace(".juvix.md", ".html")
    #         )

    #         if html_file_path.exists():
    #             log.debug(f"Removing file: {html_file_path}")
    #             html_file_path.unlink()

    #     index_file = self.env.CACHE_HTML_PATH / "index.html"
    #     if index_file.exists():
    #         index_file.unlink()

    #     # move the generated HTML files to the site directory
    #     shutil.copytree(self.env.CACHE_HTML_PATH, dest_folder, dirs_exist_ok=True)
    #     return

    # def _generate_html(self, generate: bool = True, move_cache: bool = True) -> None:
    #     everythingJuvix = self.env.DOCS_ABSPATH.joinpath("everything.juvix.md")
    #     if not everythingJuvix.exists():
    #         log.warning(
    #             f"""Consider creating a file named {Fore.GREEN}'everything.juvix.md'{Style.RESET_ALL} or \
    #             {Fore.GREEN}'index.juvix.md'{Style.RESET_ALL} in the docs directory to generate the HTML \
    #             for all Juvix Markdown file". Otherwise, the compiler will \
    #             generate the HTML for each Juvix Markdown file on each run."""
    #         )

    #     files_to_process = (
    #         self.juvix_md_collection.files
    #         if not everythingJuvix.exists()
    #         else [self.juvix_md_collection.get_file(everythingJuvix)]
    #     )

    #     def process_file(file: JuvixMarkdownFile) -> None:
    #         if generate:
    #             file.generate_html()
    #         if self.env.SITE_DIR and move_cache:
    #             self._move_html_cache_to_site_dir(file.absolute_filepath, Path(self.env.SITE_DIR))

    #     time_start = time.time()
    #     with ThreadPoolExecutor() as executor:
    #         executor.map(process_file, files_to_process)
    #         executor.shutdown(wait=True)
    #     time_end = time.time()
    #     log.info(
    #         f"Generated Auxiliary HTML in "
    #         f"{Fore.GREEN}{time_end - time_start:.5f}{Style.RESET_ALL} seconds"
    #     )

    #     return

    # async def _generate_isabelle_html(self, filepath: Path) -> Optional[str]:
    #     if not filepath.as_posix().endswith(".juvix.md"):
    #         return None

    #     file = self.juvix_md_collection.get_file(filepath)
    #     if not file:
    #         return None

    #     if not file.has_isabelle_content() or file.is_new_or_changed():
    #         log.info(f"No Isabelle file in cache for {filepath}")
    #         return await self._run_juvix_isabelle(filepath)

    #     return file.get_isabelle_content()

    # async def _get_output_for_juvix_markdown(self, filepath: Path) -> Optional[str]:
    #     if not is_juvix_markdown_file(filepath):
    #         return None

    #     file = self.juvix_md_collection.get_file(filepath)
    #     if not file:
    #         return None

    #     if not file.is_new_or_changed():
    #         log.info(f"Using cached file for {Fore.GREEN}{file.relative_filepath}{Style.RESET_ALL}")
    #         return file.get_cached_content()

    #     log.info(f"Running Juvix Markdown on {file.relative_filepath}")

    #     time_start = time.time()
    #     markdown_output: Optional[str] = None
    #     with trio.move_on_after(4):
    #         try:
    #             res: Optional[Tuple[int, str, str]] = await self._async_run_juvix_markdown(file.absolute_filepath)
    #             if res:
    #                 returncode, stdout, stderr = res
    #                 markdown_output = stdout
    #         except Exception as e:
    #             log.error(f"Too slow to run Juvix Markdown on {file.absolute_filepath}: {e}")
    #     time_end = time.time()

    #     log.info(
    #         f"Finished processing {Fore.GREEN}{file.relative_filepath}{Style.RESET_ALL} "
    #         f"in {Fore.GREEN}{time_end - time_start:.2f}s{Style.RESET_ALL}"
    #     )

    #     if not markdown_output:
    #         return None

    #     try:
    #         file.update_cache(markdown_output)
    #     except Exception as e:
    #         log.error(f"Error updating cache for file: {e}")

    #     try:
    #         file.save_original_in_cache()
    #     except Exception as e:
    #         log.error(f"Error saving original Juvix Markdown file in cache: {e}")

    #     return markdown_output

    # # def _sync_run_juvix_markdown(self, filepath: Path) -> Optional[str]:
    # #     file_abs_path: Path = filepath.absolute()
    # #     file_rel_to_docs: Path = file_abs_path.relative_to(self.env.DOCS_ABSPATH)

    # #     if not is_juvix_markdown_file(file_abs_path):
    # #         log.debug(f"The file: {file_rel_to_docs} is not a Juvix Markdown file.")
    # #         return None

    # #     juvix_markdown_cmd: List[str] = [
    # #         self.env.JUVIX_BIN,
    # #         "markdown",
    # #         "--strip-prefix=docs",
    # #         "--folder-structure",
    # #         f"--prefix-url={self.env.SITE_URL}",
    # #         "--stdout",
    # #         file_abs_path.as_posix(),
    # #         "--no-colors",
    # #         # "--offline",
    # #         # "--internal-build-dir",
    # #         # (self.env.ROOT_ABSPATH / ".juvix-build").as_posix(),
    # #     ]

    # #     result_markdown = None
    # #     try:
    # #         result_markdown = subprocess.run(
    # #             juvix_markdown_cmd,
    # #             cwd=self.env.DOCS_ABSPATH,
    # #             check=True,
    # #             capture_output=True,
    # #             text=True,
    # #         )
    # #         time.sleep(1)

    # #         returncode = result_markdown.returncode
    # #         stdout = result_markdown.stdout
    # #         stderr = result_markdown.stderr

    # #         # log.info(f"returncode: {result_markdown.returncode}")
    # #         # log.info(f"stdout: {Fore.MAGENTA}{stdout}{Style.RESET_ALL}")
    # #         # log.info(f"stderr: {Fore.YELLOW}{stderr}{Style.RESET_ALL}")

    # #         if returncode == 0:
    # #             return stdout

    # #         # The compiler found an error in the file
    # #         juvix_error_message: str = stderr.replace("\n", " ").strip()
    # #         log.error(
    # #             f"Error when typechecking the Juvix Markdown file: "
    # #             f"{Fore.GREEN}{file_rel_to_docs}{Style.RESET_ALL}\n"
    # #             f"{juvix_error_message}"
    # #         )

    # #         formatted_error_message = (
    # #             f"<details class='failure'><summary>When typechecking the Juvix Markdown file, "
    # #             f"the Juvix compiler found the following error:</summary>\n\n"
    # #             f"<pre><code>\n"
    # #             f"    {textwrap.fill(juvix_error_message, width=70)}\n"
    # #             f"</code></pre></details>\n\n"
    # #         )

    # #         metadata_block = filepath.read_text().split("---")
    # #         if len(metadata_block) > 2:
    # #             return f"{metadata_block[0]}\n{formatted_error_message}\n{metadata_block[2]}"
    # #         else:
    # #             return f"{formatted_error_message}\n\n{filepath.read_text()}"

    # #     except Exception as e:
    # #         log.error(
    # #             f"Error running the following command: {Fore.GREEN}{' '.join(juvix_markdown_cmd)}{Style.RESET_ALL}\n\nError:{e}"
    # #         )

    # #     return None

    # async def _async_run_juvix_markdown(
    #     self, filepath: Path
    # ) -> Optional[Tuple[int, str, str]]:
    #     """
    #     It returns the output of the Juvix compiler when processing a Juvix Markdown file.
    #     If the file is not a Juvix Markdown file, it returns None.
    #     If there is an error, it returns the error message formatted as a Markdown
    #     details block. Otherwise, it returns None.
    #     """
    #     file_abs_path: Path = filepath.absolute()
    #     file_rel_to_docs: Path = file_abs_path.relative_to(self.env.DOCS_ABSPATH)

    #     if not is_juvix_markdown_file(file_abs_path):
    #         log.info(f"The file: {file_rel_to_docs} is not a Juvix Markdown file.")
    #         return None

    #     juvix_markdown_cmd: List[str] = [
    #         self.env.JUVIX_BIN,
    #         "--log-level=error",
    #         "markdown",
    #         "--strip-prefix",
    #         self.env.DOCS_DIRNAME,
    #         "--folder-structure",
    #         "--prefix-url",
    #         self.env.SITE_URL,
    #         "--stdout",
    #         file_abs_path.as_posix(),
    #     ]
    #     # "--no-colors",
    #     # "--offline",
    #     # "--internal-build-dir",
    #     # "--log-level",
    #     # "error",
    #     # (self.env.ROOT_ABSPATH / ".juvix-build").as_posix(),

    #     result_markdown = None
    #     try:
    #         result_markdown = await trio.run_process(
    #             juvix_markdown_cmd,
    #             cwd=self.env.ROOT_ABSPATH,
    #             # check=True,
    #             # shell=True,
    #             capture_stdout=True,
    #             capture_stderr=True,
    #         )
    #         log.info(f"result_markdown: {result_markdown}")
    #         returncode = result_markdown.returncode
    #         stdout = result_markdown.stdout.decode("utf-8")
    #         stderr = result_markdown.stderr.decode("utf-8")

    #         return (returncode, stdout, stderr)

    #     except Exception as e:
    #         cmd = juvix_markdown_cmd
    #         if isinstance(cmd, list):
    #             cmd = " ".join(cmd)  # type: ignore

    #         log.error(
    #             f"[!] Failed to run the following command:\n"
    #             f"{Fore.GREEN}{cmd}{Style.RESET_ALL}\n\n"
    #             f"Error:{e}"
    #         )
    #     return None

    # def save_original_juvix_markdown_in_cache(self, filepath: Path) -> None:
    #     filepath_abs = filepath.absolute()
    #     filepath_rel_to_docs = filepath_abs.relative_to(self.env.DOCS_ABSPATH)
    #     raw_path: Path = (
    #         self.env.CACHE_ORIGINAL_JUVIX_MARKDOWN_FILES_ABSPATH / filepath_rel_to_docs
    #     )
    #     raw_path.parent.mkdir(parents=True, exist_ok=True)
    #     try:
    #         shutil.copy(filepath, raw_path)
    #     except Exception as e:
    #         log.error(f"Error copying file: {e}")

    # def _generate_code_block_footer_css_file(
    #     self, css_file: Path, compiler_version: Optional[str] = None
    # ) -> Optional[Path]:
    #     css_file.parent.mkdir(parents=True, exist_ok=True)
    #     try:
    #         if compiler_version is None:
    #             compiler_version = str(Version.parse(self.env.JUVIX_VERSION))
    #         compiler_version = f"Juvix v{compiler_version}".strip()
    #         css_file.write_text(
    #             (FIXTURES_PATH / "juvix_codeblock_footer.css")
    #             .read_text()
    #             .format(compiler_version=compiler_version)
    #         )
    #     except Exception as e:
    #         log.error(f"Error writing to CSS file: {e}")
    #         return None
    #     return css_file

    # def _add_footer_css_file_to_extra_css(self) -> None:
    #     css_file = self.env.JUVIX_FOOTER_CSS_FILEPATH
    #     # Check if we need to create or update the codeblock footer CSS
    #     needs_to_update_cached_juvix_version = (
    #         not self.env.CACHE_JUVIX_VERSION_FILEPATH.exists()
    #         or Version.parse(self.env.CACHE_JUVIX_VERSION_FILEPATH.read_text().strip())
    #         != Version.parse(self.env.JUVIX_VERSION)
    #     )
    #     if needs_to_update_cached_juvix_version:
    #         log.info(
    #             f"Writing Juvix version to cache: "
    #             f"{Fore.GREEN}{self.env.JUVIX_VERSION}{Style.RESET_ALL}"
    #         )
    #         self.env.CACHE_JUVIX_VERSION_FILEPATH.write_text(self.env.JUVIX_VERSION)

    #     if not css_file.exists() or needs_to_update_cached_juvix_version:
    #         self._generate_code_block_footer_css_file(css_file, self.env.JUVIX_VERSION)
    #         log.info(
    #             f"Codeblock footer CSS file generated and saved to "
    #             f"{Fore.GREEN}{css_file.as_posix()}{Style.RESET_ALL}"
    #         )

    #     # Add CSS file to extra_css
    #     css_path = css_file.relative_to(self.env.DOCS_ABSPATH)

    #     if css_path not in self.mkconfig["extra_css"]:
    #         self.mkconfig["extra_css"].append(css_path.as_posix())
