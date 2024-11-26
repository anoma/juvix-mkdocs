import asyncio
import json
import os
import shutil
import subprocess
import textwrap
import warnings
from os import getenv
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar
from urllib.parse import urljoin
from rich.console import Console  # type: ignore
from rich.markdown import Markdown  # type: ignore
import pathspec
import questionary
import yaml  # type:ignore
from bs4 import BeautifulSoup  # type:ignore
from colorama import Back, Fore, Style  # type: ignore
from dotenv import load_dotenv
from mkdocs.config.defaults import MkDocsConfig
from mkdocs.plugins import BasePlugin
from mkdocs.structure.files import Files
from mkdocs.structure.pages import Page
from semver import Version
from tqdm import tqdm as sync_tqdm  # type: ignore
from tqdm.asyncio import tqdm as async_tqdm  # type: ignore
from watchdog.events import FileSystemEvent

from mkdocs_juvix.common.preprocesors.links import WLPreprocessor
from mkdocs_juvix.env import ENV, FIXTURES_PATH
from mkdocs_juvix.images import process_images
from mkdocs_juvix.links import TOKEN_LIST_WIKILINKS, WikilinksPlugin
from mkdocs_juvix.logger import clear_line, clear_screen, log
from mkdocs_juvix.snippets import RE_SNIPPET_SECTION, SnippetPreprocessor
from mkdocs_juvix.utils import (
    compute_sha_over_folder,
    fix_site_url,
    hash_content_of,
    is_juvix_markdown_file,
)
from mkdocs_juvix.utils import time_spent as time_spent_decorator

warnings.filterwarnings("ignore", category=DeprecationWarning)

load_dotenv()
console = Console()


# os.environ["DEBUG"] = "true"

SKIP_DIRS = [
    ".juvix-build",
    ".git",
    "images",
    "assets",
    "references",
]
ERROR_MESSAGE_EXTENSION = ".error-"


def time_spent(message: Optional[Any] = None, print_result: bool = False):
    return time_spent_decorator(log=log, message=message, print_result=print_result)


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


def template_error_message(
    filepath: Optional[Path], command: List[str], error_message: str
) -> str:
    return (
        f"Error processing {Fore.GREEN}{filepath}{Style.RESET_ALL}:\n"
        f"Command: {Back.WHITE}{Fore.BLACK}{' '.join(command)}{Style.RESET_ALL}\n"
        f"Error message:\n{Fore.RED}{error_message}{Style.RESET_ALL}"
    )


class EnhancedMarkdownFile:
    """
    A class that represents a Markdown file, which may contain:
    - Juvix code blocks
    - Wikilinks
    - Images
    - Incrusted Isabelle theories
    """

    def __init__(self, filepath: Path, env: ENV, config: MkDocsConfig):
        self.env: ENV = env
        self.config: MkDocsConfig = config
        self.absolute_filepath: Path = filepath.absolute()
        self.original_in_cache_filepath: Path = (
            self.env.CACHE_ORIGINALS_ABSPATH
            / self.absolute_filepath.relative_to(self.env.DOCS_ABSPATH)
        )

        self.src_uri: str = filepath.as_posix()
        self.relative_filepath: Path = self.absolute_filepath.relative_to(
            env.DOCS_ABSPATH
        )
        self.url: str = urljoin(
            env.SITE_URL,
            self.relative_filepath.as_posix()
            .replace(".juvix", "")
            .replace(".md", ".html"),
        )

        # Module information
        self.module_name: Optional[str] = env.unqualified_module_name(filepath)
        self.qualified_module_name: Optional[str] = env.qualified_module_name(filepath)

        # Markdown related, some filled later in the process
        self._markdown_output: Optional[str] = None
        self._metadata: Optional[dict] = None
        self.cache_filepath: Path = env.compute_processed_filepath(filepath)
        # the hash cache file is used to check if the file has changed
        self.hash_cache_filepath: Path = env.compute_filepath_for_cached_hash_for(
            self.absolute_filepath
        )
        self._root_juvix_project_path: Optional[Path] = None

        # Processing flags for each task (updating during the process)
        self._processed_juvix_markdown: bool = False
        self._processed_juvix_isabelle: bool = False
        self._processed_juvix_html: bool = False
        self._processed_images: bool = False
        self._processed_wikilinks: bool = False
        self._processed_snippets: bool = False
        self._processed_errors: bool = False

        # Isabelle related
        self._needs_isabelle: bool = False  # Fill later in the process
        self._include_isabelle_at_bottom: bool = False  # Fill later in the process
        self.cached_isabelle_filepath: Optional[Path] = (
            self.env.compute_filepath_for_juvix_isabelle_output_in_cache(
                self.absolute_filepath
            )
        )

        # Error handling
        self._cached_error_messages: Dict[str, Optional[str]] = {
            "juvix_markdown": None,
            "juvix_isabelle": None,
            "juvix_html": None,
            "images": None,
            "wikilinks": None,
            "snippets": None,
        }

    def __str__(self) -> str:
        return f"{Fore.GREEN}{self.relative_filepath}{Style.RESET_ALL}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            # File information
            "filepath": self.absolute_filepath.as_posix(),
            "module_name": self.module_name,
            "qualified_module_name": self.qualified_module_name,
            "root_juvix_project_path": self.root_juvix_project_path.as_posix()
            if self.root_juvix_project_path
            else None,
            "url": self.url,
            "content_hash": self.hash,
            # Error handling
            "error_messages": self._cached_error_messages,
            "processed": {
                "juvix_markdown": self._processed_juvix_markdown,
                "isabelle": self._processed_juvix_isabelle,
                "images": self._processed_images,
                "snippets": self._processed_snippets,
                "wikilinks": self._processed_wikilinks,
            },
        }

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    @property
    @time_spent(message="> extracting metadata")
    def metadata(self) -> Optional[dict]:
        """
        Extract the metadata from the markdown output of the file.
        Use it only after the markdown output is generated.
        """
        if self._metadata is not None:
            return self._metadata

        if self.markdown_output is None:
            return None
        self._metadata = parse_front_matter(self.markdown_output)
        return self._metadata

    # ------------------------------------------------------------------
    # Caching
    # ------------------------------------------------------------------

    def is_cached(self) -> bool:
        """
        Check if there is a cached markdown output generated by running `juvix
        markdown`.
        """
        return self.cache_filepath.exists()

    @property
    def cached_hash(self) -> Optional[str]:
        """
        Return the cached hash of the markdown output generated by running
        `juvix markdown`. The hash is used to check if the file has changed.
        """
        if self.is_cached() and self.hash_cache_filepath.exists():
            return self.hash_cache_filepath.read_text().strip()
        else:
            return None

    @property
    def hash(self) -> Optional[str]:
        """
        Compute the hash of the file content of the original file.
        """
        if self.absolute_filepath.exists():
            return hash_content_of(self.absolute_filepath)
        else:
            return None

    def reset_processed_flags(self):
        self._processed_juvix_markdown = False
        self._processed_juvix_isabelle = False
        self._processed_images = False
        self._processed_snippets = False
        self._processed_wikilinks = False
        self._processed_errors = False

    def changed_since_last_run(self) -> bool:
        """
        Check if the original file has changed since the last time `juvix markdown`
        was run on it, by checking if the hash of the file content at the original
        location is different from the cached hash.
        """
        if not self.is_cached():
            log.debug(
                f"> File {Fore.GREEN}{self}{Style.RESET_ALL} has no cached output"
            )
            self.reset_processed_flags()
            return True
        try:
            cached_hash = self.cached_hash
            if cached_hash is None:
                log.debug(
                    f"> The hash for this file {Fore.GREEN}{self}{Style.RESET_ALL} is not stored in the cache"
                )
                self.reset_processed_flags()
                return True
            cond = self.hash != cached_hash
            if cond:
                log.debug(
                    f"> The file {Fore.YELLOW}{self.relative_filepath}{Style.RESET_ALL} "
                    f"has changed since last run"
                )
                self.reset_processed_flags()
            return cond
        except Exception as e:
            log.error(
                f"Error checking if file changed: {e}, so we assume it has changed"
            )
            self.reset_processed_flags()
            return True

    # ------------------------------------------------------------------
    # Markdown Output property
    # ------------------------------------------------------------------

    @property
    def markdown_output(self) -> Optional[str]:
        """
        Return the cached output of running `juvix markdown` on the original file.
        If the output is not cached, it runs `juvix markdown` on the original
        file and returns the output.
        """
        if self._markdown_output is None:
            try:
                log.debug(
                    f"> Because it was asked markdown and it was not cached, "
                    f"generating markdown output for {Fore.GREEN}{self}{Style.RESET_ALL}"
                )
                self.run_pipeline(save_markdown=True, force=True)
                return self._markdown_output
            except Exception as e:
                log.error(f"Error generating markdown output: {e}")
                return None
        return self._markdown_output

    def run_pipeline(self, save_markdown: bool = True, force: bool = False) -> None:
        """
        Run the pipeline of tasks to generate the markdown output of the file.
        Be aware that this may get the wrong output if the snippets in the file
        are not cached.
        """
        if self.changed_since_last_run():
            self.generate_original_markdown(save_markdown=save_markdown)
            if (
                is_juvix_markdown_file(self.absolute_filepath)
                and self.env.juvix_enabled
            ):
                self.generate_juvix_markdown_output(
                    save_markdown=save_markdown, force=force
                )
                self.generate_isabelle_theories(
                    save_markdown=save_markdown, force=force
                )
            # self.generate_images(save_markdown=save_markdown, force=force)
            self.replaces_wikilinks_by_markdown_links(
                save_markdown=save_markdown, force=force
            )
            self.render_snippets(save_markdown=save_markdown, force=force)

    @time_spent(message="> saving markdown output")
    def save_markdown_output(self, md_output: str) -> Optional[Path]:
        """
        Cache the input provided as the cached markdown. Update the hash of the
        file to future checks.
        """
        log.debug(f"> length of markdown output: {len(md_output)}")
        self._markdown_output = md_output
        self.cache_filepath.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.cache_filepath.write_text(md_output)
        except Exception as e:
            log.error(f"Error saving markdown output: {e}")
            return None
        try:
            self.env.update_hash_file(self.absolute_filepath)
        except Exception as e:
            log.error(f"Error saving markdown output: {e}")
            return None

        return self.cache_filepath.absolute()

    def copy_original_file_to_cache(self) -> None:
        try:
            self.original_in_cache_filepath.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(self.absolute_filepath, self.original_in_cache_filepath)
        except Exception as e:
            log.error(f"Error copying original file to cache: {e}")

    def save_and_read_original_markdown_from_cache(self) -> Optional[str]:
        """
        Read the original markdown from the cache folder.
        """
        self.copy_original_file_to_cache()
        markdown_output = None
        if (
            self.original_in_cache_filepath.exists()
            and self.original_in_cache_filepath.is_file()
        ):
            markdown_output = self.original_in_cache_filepath.read_text()

        if markdown_output is None:
            log.error(
                f"Failed to extract original content from "
                f"{Fore.GREEN}{self.absolute_filepath}{Style.RESET_ALL}"
            )
        return markdown_output

    # ------------------------------------------------------------------
    # Error handling for markdown output
    # ------------------------------------------------------------------

    def has_error_message(self, kind: str = "markdown") -> bool:
        """Check if there is an error message for the given kind."""
        flag = False
        for value in self._cached_error_messages.values():
            if value is not None:
                flag = True
                break
        log.debug(
            f"> file flags:{Fore.YELLOW}{self.relative_filepath}{Style.RESET_ALL}"
        )
        log.debug(f"  has error message: {Fore.YELLOW}{flag}{Style.RESET_ALL}")
        return flag

    def save_error_message(self, error_message: str, kind: str = "markdown") -> None:
        """Save the error message to a cache file."""
        ext = ERROR_MESSAGE_EXTENSION + kind
        error_filepath = self.cache_filepath.with_suffix(ext)
        error_filepath.parent.mkdir(parents=True, exist_ok=True)
        error_filepath.write_text(error_message)
        self._cached_error_messages[kind] = error_message

    def get_error_message(self, kind: str = "markdown") -> Optional[str]:
        """Retrieve the error message from cache or file of previous run."""
        if self._cached_error_messages.get(kind, None):
            return self._cached_error_messages[kind]

        ext = ERROR_MESSAGE_EXTENSION + kind
        error_filepath = self.cache_filepath.with_suffix(ext)
        if error_filepath.exists():
            try:
                error_message = error_filepath.read_text()
                self._cached_error_messages[kind] = error_message
                return error_message
            except Exception as e:
                log.error(f"Error reading error message file: {e}")
                return None
        return None

    def load_and_print_saved_error_messages(self) -> None:
        """Print the error messages saved in the cache."""
        for kind in self._cached_error_messages:
            error_message = self.get_error_message(kind)
            self._cached_error_messages[kind] = error_message
            if error_message:
                log.error(
                    template_error_message(
                        self.relative_filepath,
                        [kind],
                        error_message,
                    )
                )

    def clear_error_messages(self, kind: Optional[str] = None) -> None:
        """Clear the error message from cache and file of previous run."""

        def clear_error_message(kind: str) -> None:
            if kind in self._cached_error_messages:
                self._cached_error_messages[kind] = None

            ext: str = ERROR_MESSAGE_EXTENSION + kind
            error_filepath: Path = self.cache_filepath.with_suffix(ext)
            if error_filepath.exists():
                error_filepath.unlink()

        if kind:
            clear_error_message(kind)
            return
        for kind in self._cached_error_messages:
            clear_error_message(kind)

    def add_errors_to_markdown(
        self,
        content: str,
    ) -> str:
        """
        Format the error message to include it in the Markdown output of the
        file, so that it is rendered nicely. The filepath is used to extract the
        metadata from the file if it is provided, otherwise the metadata is
        extracted from the markdown output of the current file.
        """

        # check if there are any error messages
        if all(value is None for value in self._cached_error_messages.values()):
            return content

        def format_error_message(kind: str) -> str:
            error_message = self.get_error_message(kind)
            if error_message is None:
                return ""
            formatted_error_message: str = (
                f"<details class='failure'><summary>{kind} error</summary>\n\n"
                f"<pre><code>\n"
                f"    {textwrap.fill(error_message, width=110)}\n\n"
                f"</code></pre></details>\n\n"
            )
            return formatted_error_message

        formatted_error_msgs = "\n\n".join(
            format_error_message(kind)
            for kind in self._cached_error_messages.keys()
            if self._cached_error_messages[kind]
        )

        _output = content
        metadata = parse_front_matter(_output)
        if metadata:
            end_index: int = _output.find("---", 3)
            front_matter: str = _output[3:end_index].strip()
            _output = (
                f"---\n"
                f"{front_matter}\n"
                f"---\n\n"
                f"{formatted_error_msgs}\n\n"
                f"{_output[end_index+3:]}"
            )
        else:
            _output = f"{formatted_error_msgs}\n\n{content or ''}"
        return _output

    # ------------------------------------------------------------
    # Root Juvix Project Path
    # ------------------------------------------------------------

    def _build_juvix_root_project_path_command(self) -> List[str]:
        return [
            self.env.JUVIX_BIN,
            "dev",
            "root",
            self.absolute_filepath.as_posix(),
        ]

    def _run_juvix_root_project_path(self) -> Optional[Path]:
        try:
            result = subprocess.run(
                self._build_juvix_root_project_path_command(),
                capture_output=True,
                text=True,
                timeout=self.env.TIMELIMIT,
            )
            return Path(result.stdout.strip())
        except Exception as e:
            self.save_error_message(str(e), "juvix_root")
            return None

    @property
    def root_juvix_project_path(self) -> Optional[Path]:
        if not self.env.juvix_enabled:
            return None
        if self._root_juvix_project_path is None:
            self._root_juvix_project_path = self._run_juvix_root_project_path()
        return self._root_juvix_project_path

    # ------------------------------------------------------------
    # Juvix Markdown tasks
    # ------------------------------------------------------------

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

    def _run_command_juvix_markdown(self, force: bool = False) -> Optional[str]:
        """
        Run the Juvix Markdown command and return the output.
        If the command fails, save the error message and return None.
        The error message is saved to be displayed in the markdown output of
        the file.
        """
        if (
            not is_juvix_markdown_file(self.absolute_filepath)
            or not self.env.juvix_enabled
        ):
            return None

        self._processed_juvix_markdown = (
            False if force else self._processed_juvix_markdown
        )

        self.clear_error_messages("juvix_markdown")
        module_name = ".".join(self.relative_filepath.parts[-2:])
        log.debug(f"> juvix markdown for {Fore.MAGENTA}{module_name}{Style.RESET_ALL}")

        try:
            result = subprocess.run(
                self._build_juvix_markdown_command(),
                cwd=self.env.DOCS_ABSPATH,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.env.TIMELIMIT,
            )
            if result.returncode != 0:
                raise Exception(result.stderr)
            return result.stdout
        except subprocess.CalledProcessError as e:
            self.save_error_message(e.stderr, "juvix_markdown")
            return None
        except Exception as e:
            self.save_error_message(str(e), "juvix_markdown")
            log.error(
                f"Unexpected error running Juvix Markdown on "
                f"{Fore.GREEN}{self}{Style.RESET_ALL}:\n{e}"
            )
            return None

    # ------------------------------------------------------------------
    # Juvix HTML tasks
    # ------------------------------------------------------------------

    def _build_juvix_html_command(self) -> List[str]:
        return [
            self.env.JUVIX_BIN,
            "--log-level=error",
            "--no-colors",
            "html",
            "--strip-prefix",
            self.env.DOCS_DIRNAME,
            "--folder-structure",
            # "--ext", # This flat is not present in Juvix Markdown, so it
            # creates broken links
            # ".judoc.html",
            "--output-dir",
            self.env.CACHE_HTML_PATH.as_posix(),
            "--prefix-url",
            self.env.SITE_URL,
            "--prefix-assets",
            self.env.SITE_URL,
            self.absolute_filepath.as_posix(),
        ]

    def _process_juvix_html(self, update_assets: bool = False) -> None:
        """
        Generate the HTML output running the pipeline if the file has changed
        since the last time `juvix html` was run on it. Otherwise, it reads
        the cached HTML output from the cache file.
        """
        if (
            not is_juvix_markdown_file(self.absolute_filepath)
            or not self.env.juvix_enabled
        ):
            return None

        if self._processed_juvix_html and not self.changed_since_last_run():
            log.debug(
                f"> Skipping HTML generation for {Fore.GREEN}{self.relative_filepath}{Style.RESET_ALL} using cached output"
            )
            return None

        self.env.CACHE_HTML_PATH.mkdir(parents=True, exist_ok=True)

        self.clear_error_messages("juvix_html")
        try:
            output = subprocess.run(
                self._build_juvix_html_command(),
                cwd=self.env.DOCS_ABSPATH,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.env.TIMELIMIT,
            )

            if output.returncode != 0:
                self.save_error_message(output.stderr, "juvix_html")
                return None

            self._processed_juvix_html = True
            # ------------------------------------------------------------
            # Rename the HTML files of Juvix Markdown files, .html -> .judoc.html
            # ------------------------------------------------------------

            for _file in self.env.CACHE_ORIGINALS_ABSPATH.rglob("*.juvix.md"):
                file = _file.absolute()
                html_file_path = (
                    self.env.CACHE_HTML_PATH
                    / file.relative_to(self.env.CACHE_ORIGINALS_ABSPATH).parent
                    / file.name.replace(".juvix.md", ".html")
                )

                if html_file_path.exists():
                    html_file_path.rename(
                        self.env.CACHE_HTML_PATH
                        / html_file_path.name.replace(".html", "-judoc.html")
                    )

            index_file = self.env.CACHE_HTML_PATH / "index.html"
            if index_file.exists():
                index_file.rename(
                    self.env.CACHE_HTML_PATH
                    / index_file.name.replace(".html", "-judoc.html")
                )

            # ------------------------------------------------------------
            # Update assets
            # ------------------------------------------------------------

            if update_assets:
                self._update_assets()
            else:
                log.debug("HTML generation completed but not saved to disk.")
        except subprocess.CalledProcessError as e:
            self.save_error_message(e.stderr, "html")
        except Exception as e:
            log.error(f"Unexpected error during HTML generation: {e}")

    @time_spent(message="> updating assets")
    def _update_assets(self) -> None:
        """
        Update the assets in the cache folder. If the assets folder already exists
        in the cache folder, it removes it. Then, it copies the assets folder from
        the original folder to the cache folder.
        """
        assets_in_cache_html_path = self.env.CACHE_HTML_PATH / "assets"
        if assets_in_cache_html_path.exists():
            self.env.remove_directory(assets_in_cache_html_path)
        assets_path = self.env.DOCS_ABSPATH / "assets"
        assets_path.mkdir(parents=True, exist_ok=True)
        self.env.copy_directory(assets_path, assets_in_cache_html_path)

    # ------------------------------------------------------------
    # Juvix to Isabelle translation tasks
    # ------------------------------------------------------------

    def _build_juvix_isabelle_command(self) -> List[str]:
        cmd = [
            self.env.JUVIX_BIN,
            "--log-level=error",
            "--no-colors",
            "isabelle",
            "--stdout",
            "--output-dir",
            self.env.ISABELLE_OUTPUT_PATH.as_posix(),
            self.absolute_filepath.as_posix(),
        ]
        # TODO: remove this once that branch is merged
        if "Branch: fix-implicit-record-args" in self.env.JUVIX_FULL_VERSION:
            cmd.insert(3, "--non-recursive")
        return cmd

    def _run_juvix_isabelle(self) -> Optional[str]:
        """
        Run the Juvix Isabelle command and return the output. If the command
        fails, save the error message and return None. The error message is
        saved to be displayed in the markdown output of the file. The output is
        not Markdown, it is Isabelle/HOL code.
        """
        if (
            not is_juvix_markdown_file(self.absolute_filepath)
            or not self.env.juvix_enabled
        ):
            return None

        self.clear_error_messages("juvix_isabelle")
        try:
            log.debug(
                f"> running juvix isabelle on {Fore.MAGENTA}{self.relative_filepath}{Style.RESET_ALL}"
            )
            result = subprocess.run(
                self._build_juvix_isabelle_command(),
                cwd=self.env.DOCS_ABSPATH,
                # check=True,
                capture_output=True,
                text=True,
                timeout=self.env.TIMELIMIT,
            )
            if result.returncode != 0:
                self.save_error_message(result.stderr, "juvix_isabelle")
            else:
                self.clear_error_messages("juvix_isabelle")
                return result.stdout
        except Exception as e:
            log.error(f"Error running Juvix Isabelle on {self}: {e}")
        return None

    @time_spent(message="> processing isabelle translation")
    def process_isabelle_translation(
        self, content: str, modify_markdown_output: bool = True
    ) -> Optional[str]:
        """
        Process the Isabelle translation, saving the output to the cache folder.
        If `modify_markdown_output` is True, the Isabelle output is added to the
        `content` at the bottom.
        """
        result_isabelle: Optional[str] = self._run_juvix_isabelle()
        # we save for snippets usage
        if result_isabelle is None:
            return None

        isabelle_output = self._save_isabelle_theory(result_isabelle)
        if modify_markdown_output and content:
            md_with_isabelle = content + (
                FIXTURES_PATH / "isabelle_at_bottom.md"
            ).read_text().format(
                filename=self.relative_filepath.name,
                block_title=self.relative_filepath.name.replace(".juvix.md", ".thy"),
                isabelle_html=isabelle_output,
                juvix_version=self.env.JUVIX_VERSION,
            )
            return md_with_isabelle
        return content

    @time_spent(message="> saving isabelle theory")
    def _save_isabelle_theory(self, result: str) -> Optional[str]:
        """
        Save the Isabelle output to the cache folder. This requires that the
        Isabelle file name is known beforehand.
        """
        if not self.cached_isabelle_filepath:
            log.error(
                template_error_message(
                    self.relative_filepath,
                    self._build_juvix_isabelle_command(),
                    "Could not determine the Isabelle file name for: "
                    f"{self.relative_filepath}",
                )
            )
            return None

        isabelle_output = self._fix_unclosed_snippet_annotations(result)

        try:
            self.cached_isabelle_filepath.parent.mkdir(parents=True, exist_ok=True)
            self.cached_isabelle_filepath.write_text(isabelle_output)
            return isabelle_output
        except Exception as e:
            log.error(f"Error writing to cache Isabelle file: {e}")
            return None

    # TODO: Remove this once the compiler fixes this, positional comments
    # are preserved in the output
    @staticmethod
    def _fix_unclosed_snippet_annotations(isabelle_output: str) -> str:
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
                    lines[j] = f"(* --8<-- [end:{name}] *)"
                    log.debug(
                        f"Added missing end tag for snippet '{name}' at line {j+1}"
                    )
                    break
            else:
                log.error(
                    f"Could not find a place to add missing end tag for snippet '{name}'"
                )

        return "\n".join(lines)

    # ------------------------------------------------------------------------
    # Generate and save markdown output, the task run over either markdown or
    # Juvix Markdown files
    # ------------------------------------------------------------------------

    def _skip_generation(self, processed_tags: List[str] = []) -> bool:
        """
        Skip the generation of the markdown output if the file has not changed
        since the last time the pipeline was run on it.
        """
        for tag in processed_tags:
            if tag == "juvix_markdown" and not self._processed_juvix_markdown:
                return False
            if tag == "isabelle" and not self._processed_juvix_isabelle:
                return False
            if tag == "snippets" and not self._processed_snippets:
                return False
            if tag == "wikilinks" and not self._processed_wikilinks:
                return False
            if tag == "images" and not self._processed_images:
                return False
            if tag == "errors" and not self._processed_errors:
                return False
        return False

    def skip_and_use_cache_for_process(
        self, processed_tag: str, force: bool = False
    ) -> Optional[str]:
        if force:
            setattr(self, processed_tag, False)
        try:
            if not self.changed_since_last_run():
                self.load_and_print_saved_error_messages()
                return None
            if self._skip_generation(processed_tags=[processed_tag]):
                log.debug(f"Reading cached markdown from {self.cache_filepath}")
                return self.cache_filepath.read_text()
        except Exception as e:
            log.error(
                f"Failed to read cached markdown from"
                f"{Fore.GREEN}{self.cache_filepath}{Style.RESET_ALL}:\n{e}"
            )
        return None

    # ------------------------------------------------------------------------
    # Generate and save markdown output, the task run over either markdown or
    # Juvix Markdown files
    # ------------------------------------------------------------------------

    def generate_original_markdown(self, save_markdown: bool = True) -> None:
        """
        Save the original markdown output for the file for later use.
        """
        _markdown_output = self.save_and_read_original_markdown_from_cache()
        if save_markdown and _markdown_output:
            try:
                self.save_markdown_output(_markdown_output)
            except Exception as e:
                log.error(f"Failed to save markdown output, we however continue: {e}")

    def generate_juvix_markdown_output(
        self, save_markdown: bool = True, force: bool = False
    ) -> None:
        """
        Generate the markdown output for the file.
        """
        if not is_juvix_markdown_file(self.absolute_filepath):
            log.debug(
                f"> Skipping markdown generation for {Fore.GREEN}{self.relative_filepath}{Style.RESET_ALL} "
                f"because it is not a Juvix Markdown file"
            )
            return None

        if (
            self._processed_juvix_markdown
            and not force
            and not self.changed_since_last_run()
        ):
            log.debug(
                f"> Skipping markdown generation for {Fore.GREEN}{self.relative_filepath}{Style.RESET_ALL} using cached output"
            )
            return None

        markdown_output: str = self.cache_filepath.read_text()
        metadata = parse_front_matter(markdown_output) or {}

        preprocess = metadata.get("preprocess", {})
        _output = None
        if preprocess.get("juvix", True) and (
            not self._processed_juvix_markdown or force
        ):
            _output = self._run_command_juvix_markdown()
            if _output and save_markdown:
                self._processed_juvix_markdown = True
                self.save_markdown_output(_output)
            else:
                self._processed_juvix_markdown = False

    @time_spent(message="> generating isabelle theories")
    def generate_isabelle_theories(
        self, save_markdown: bool = True, force: bool = False
    ) -> None:
        """
        Process the Isabelle translation, saving the output to the cache folder.
        """
        if not is_juvix_markdown_file(self.absolute_filepath):
            return None

        if (
            self._processed_juvix_isabelle
            and not force
            and not self.changed_since_last_run()
        ):
            log.debug(
                f"> Skipping isabelle generation for {Fore.GREEN}{self.relative_filepath}{Style.RESET_ALL} using cached output"
            )
            return None

        markdown_output: str = self.cache_filepath.read_text()
        metadata = parse_front_matter(markdown_output) or {}
        preprocess = metadata.get("preprocess", {})
        self._needs_isabelle = preprocess.get("isabelle", False)
        self._needs_isabelle_at_bottom = preprocess.get(
            "isabelle_at_bottom",
            self._needs_isabelle,
        )
        _output = None
        if (self._needs_isabelle or self._needs_isabelle_at_bottom) and (
            not self._processed_juvix_isabelle or force
        ):
            _output = self.process_isabelle_translation(
                content=markdown_output,
                modify_markdown_output=self._needs_isabelle_at_bottom,
            )
            if _output and save_markdown:
                self._processed_juvix_isabelle = True
                self.save_markdown_output(_output)
            else:
                self._processed_juvix_isabelle = False

    @time_spent(message="> extracting snippets")
    def render_snippets(self, save_markdown: bool = True, force: bool = False) -> None:
        """
        Modify the markdown output by adding the snippets found in the file.
        This requires the preprocess of Juvix and Isabelle to be ocurred before.
        """
        if self._processed_snippets and not force and not self.changed_since_last_run():
            log.debug(
                f"> Skipping snippets generation for {Fore.GREEN}{self.relative_filepath}{Style.RESET_ALL} using cached output"
            )
            return None

        log.debug(
            f"Processing snippets for {Fore.GREEN}{self.relative_filepath}{Style.RESET_ALL}"
        )

        _markdown_output: str = self.cache_filepath.read_text()
        metadata = parse_front_matter(_markdown_output) or {}
        preprocess = metadata.get("preprocess", {})
        needs_snippets = preprocess.get("snippets", True)
        _output = None
        if needs_snippets and (not self._processed_snippets or force):
            _output = self.run_snippet_preprocessor(content=_markdown_output)
            if _output and save_markdown:
                self._processed_snippets = True
                self.save_markdown_output(_output)
            else:
                self._processed_snippets = False

    @time_spent(message="> processing snippets")
    def run_snippet_preprocessor(
        self,
        content: Optional[str] = None,
    ) -> str:
        snippet_preprocessor = SnippetPreprocessor()
        snippet_preprocessor.enhanced_mdfile = self
        snippet_preprocessor.base_path = [
            self.cache_filepath.parent.resolve().absolute(),
            self.env.CACHE_PROCESSED_MARKDOWN_PATH.resolve().absolute(),
        ]

        if content:
            try:
                _output = snippet_preprocessor.run(
                    content.split("\n"), file_name=self.cache_filepath
                )
                if isinstance(_output, Exception):
                    raise _output
                content = "\n".join(_output)
            except Exception as e:
                self.save_error_message(str(e), "snippets")

        return content or "Something went wrong processing snippets"

    @time_spent(message="> generating wikilinks")
    def replaces_wikilinks_by_markdown_links(
        self, save_markdown: bool = True, force: bool = False
    ) -> None:
        """
        Modify the markdown output by replacing the wikilinks by markdown links.
        This requires the preprocess of Juvix and Isabelle to be ocurred before.
        """

        if (
            self._processed_wikilinks
            and not force
            and not self.changed_since_last_run()
        ):
            log.debug(
                f"> Skipping wikilinks generation for {Fore.GREEN}{self}{Style.RESET_ALL} using cached output"
            )
            return None

        log.debug(f"Processing wikilinks for {Fore.GREEN}{self}{Style.RESET_ALL}")
        _output = None
        _markdown_output = self.cache_filepath.read_text()
        log.debug(f"Read markdown content from {self.cache_filepath}")
        metadata = parse_front_matter(_markdown_output) or {}
        log.debug(f"Parsed front matter: {metadata}")
        preprocess = metadata.get("preprocess", {})
        needs_wikilinks = preprocess.get("wikilinks", True)
        log.debug(f"Needs wikilinks: {needs_wikilinks}")
        if needs_wikilinks and (not self._processed_wikilinks or force):
            _output = self.run_wikilinks_preprocessor(
                content=_markdown_output,
                modify_markdown_output=True,
            )
            log.debug(f"Ran wikilinks preprocessor, output: {_output}")
            if _output and save_markdown:
                self._processed_wikilinks = True
                self.save_markdown_output(_output)
                log.debug(f"Saved markdown output for {self.relative_filepath}")
            else:
                self._processed_wikilinks = False
                log.debug(f"Did not save markdown output for {self.relative_filepath}")

    @time_spent(message="> processing wikilinks")
    def run_wikilinks_preprocessor(
        self,
        content: str,
        modify_markdown_output: bool = True,
    ) -> str:
        assert "url_for" in self.config, "url_for is not in the config"
        assert "nodes" in self.config, "nodes is not in the config"

        wl_preprocessor = WLPreprocessor(config=self.config, env=self.env)
        wl_preprocessor.absolute_path = self.absolute_filepath
        wl_preprocessor.relative_path = self.relative_filepath
        wl_preprocessor.url = self.url

        if modify_markdown_output:
            content = wl_preprocessor._run(content)
        if TOKEN_LIST_WIKILINKS not in content:
            content = content + "\n" + TOKEN_LIST_WIKILINKS + "\n"
        return content

    def generate_images(
        self, save_markdown: bool = True, force: bool = False
    ) -> Optional[str]:
        """
        Modify the markdown output by adding the images. This requires the
        preprocess of Juvix and Isabelle to be ocurred before.
        """
        if self._processed_images and not force and not self.changed_since_last_run():
            log.debug(
                f"> Skipping images generation for {Fore.GREEN}{self.relative_filepath}{Style.RESET_ALL} using cached output"
            )
            return None

        log.info(f"{Fore.MAGENTA}Generating images for {self.relative_filepath}{Style.RESET_ALL}")
        _output = None
        _markdown_output = self.cache_filepath.read_text()
        metadata = parse_front_matter(_markdown_output) or {}
        preprocess = metadata.get("preprocess", {})
        needs_images = preprocess.get("images", True)
        log.debug(f"Needs images: {needs_images}")
        if needs_images:
            _output = process_images(
                self.env,
                _markdown_output,
                self.absolute_filepath,
            )
            if _output and save_markdown:
                self._processed_images = True
                self.save_markdown_output(_output)
            else:
                self._processed_images = False
        return _output


class EnhancedMarkdownCollection:
    """
    A collection of EnhancedMarkdownFile objects.
    """

    env: ENV
    config: MkDocsConfig
    force_wikilinks_generation: bool = False

    # @time_spent(message="> initializing enhanced markdown collection")
    def __init__(self, config, env: ENV, docs: Optional[Path] = None):
        self.env: ENV = env
        self.config = config
        self.docs_path: Path = docs or env.DOCS_ABSPATH

        try:
            # The list of markdown files to be processed, filled later
            self.files: Optional[List[EnhancedMarkdownFile]] = None

            # The "everything" file is a special Juvix Markdown file that contains
            # links to all the Juvix Markdown files in the folder.
            self.everything_html_file: Optional[EnhancedMarkdownFile] = (
                EnhancedMarkdownFile(
                    self.docs_path / "everything.juvix.md",
                    env=self.env,
                    config=self.config,
                )
            )
            if not self.everything_html_file.absolute_filepath.exists():
                self.everything_html_file = None

            # The hash is used to check if the markdown files have changed since the
            # last time the project was built.
            self.cached_hash: Optional[str] = None

        except Exception as e:
            log.error(f"Error initializing JuvixMarkdownCollection: {e}")
            raise

    @time_spent(message="> storing original files in cache for faster lookup")
    def scanning_originals(self) -> List[EnhancedMarkdownFile]:
        """
        Cache the original Juvix Markdown files in the cache folder for faster
        lookup.
        """

        try:
            md_files = list(self.docs_path.rglob("*.md"))
            log.debug(
                f"Collecting {Fore.GREEN}{len(md_files)}{Style.RESET_ALL} "
                f"Markdown files for pre-processing from "
                f"{Fore.GREEN}{self.docs_path}{Style.RESET_ALL}"
            )

            self.files = []
            files_to_process = [
                file for file in md_files if not set(file.parts) & set(SKIP_DIRS)
            ]

            with sync_tqdm(
                total=len(files_to_process), desc="Scanning files for faster lookup"
            ) as pbar:
                for file in files_to_process:
                    pbar.set_postfix_str(
                        f"{Fore.MAGENTA}{file.relative_to(self.docs_path)}{Style.RESET_ALL}"
                    )
                    enhanced_file = EnhancedMarkdownFile(file, self.env, self.config)
                    self.files.append(enhanced_file)
                    enhanced_file.original_in_cache_filepath.parent.mkdir(
                        parents=True, exist_ok=True
                    )
                    log.debug(
                        f"Copying original content from {file} to {enhanced_file.original_in_cache_filepath} for safe content extraction"
                    )
                    shutil.copy(file, enhanced_file.original_in_cache_filepath)
                    pbar.update(1)

            return self.files

        except Exception as e:
            log.error(f"Error getting Markdown files in {self.docs_path}: {e}")
            return []

    def get_enhanced_file_entry(self, filepath: Path) -> Optional[EnhancedMarkdownFile]:
        """
        Get the EnhancedMarkdownFile object for the given filepath in the docs
        folder.
        """
        if self.files is None:
            return None
        return next(
            (
                file
                for file in self.files
                if filepath == file.absolute_filepath
                or filepath == file.relative_filepath
                or filepath.as_posix() == file.src_uri
            ),
            None,
        )

    @property
    def hash(self) -> str:
        """
        Compute the hash of the folder containing the original Juvix Markdown
        files. These files were moved to the cache folder during the build
        process for faster lookup.
        """
        try:
            return compute_sha_over_folder(self.env.CACHE_ORIGINALS_ABSPATH)
        except Exception as e:
            log.error(f"Error computing hash: {e}")
            return ""

    def has_changes(self) -> bool:
        """
        Check if the markdown files, including Juvix Files, have changed since
        the last time the project was built.
        """
        return self.cached_hash is None or self.hash != self.cached_hash

    @time_spent(
        message="> updating cached hash of the entire project", print_result=True
    )
    def update_cached_hash(self) -> Optional[str]:
        """
        Update the cached hash of the entire project. Write it to the file
        system for future lookups.
        """
        try:
            hash = self.hash
            self.env.CACHE_PROJECT_HASH_FILEPATH.write_text(hash)
            self.cached_hash = hash
            return hash
        except Exception as e:
            log.error(f"Error updating cached hash of the entire project: {e}")
            return None

    def is_html_cache_empty(self) -> bool:
        """Check if the folder containing the HTML cache is empty."""
        return len(list(self.env.CACHE_HTML_PATH.glob("*"))) == 0

    def save_juvix_modules_json(self) -> Optional[Path]:
        """
        Save the Juvix modules JSON file to the cache folder.
        Return the path of the JSON file relative to the root of the project.
        """
        if self.files is None:
            return None
        try:
            json_path = self.env.CACHE_ABSPATH / "juvix_modules.json"
            json_content = json.dumps(
                [file.to_dict() for file in self.files if file.absolute_filepath],
                indent=2,
            )
            json_path.write_text(json_content)
            return json_path.relative_to(self.env.ROOT_ABSPATH)
        except Exception as e:
            log.error(f"Error saving juvix_modules.json: {e}")
            return None

    @time_spent()
    def run_pipeline_on_collection(
        self,
        generate_juvix_markdown: bool = True,
        generate_juvix_isabelle: bool = True,
        generate_snippets: bool = True,
        generate_wikilinks: bool = True,
        generate_images: bool = True,
    ) -> None:
        """
        Process the files pipeline. First, generate the markdown output for all
        the Juvix Markdown files. Then, generate the HTML output for all the
        Juvix Markdown files.
        """
        if self.files is None:
            log.debug("> no files to process")
            return

        log.info(
            f"> running pipeline on {Fore.GREEN}{len(self.files)}{Style.RESET_ALL} files"
        )

        files_to_process: List[EnhancedMarkdownFile] = [
            file
            for file in self.files
            if file.changed_since_last_run() or file.has_error_message()
        ]

        if len(files_to_process) == 0:
            log.debug(f"{Fore.YELLOW}no files to process{Style.RESET_ALL}")
            return

        log.info(
            f"> {Fore.GREEN}{len(files_to_process)}{Style.RESET_ALL} file"
            f"{'s' if len(files_to_process) > 1 else ''} need to be processed "
            "because it's the first time, their cached version is not up to date, "
            "or the file has errors on previous processing"
        )

        @time_spent(message="collecting original markdowns for caching")
        async def process_original_markdowns():
            await async_tqdm.gather(
                *[
                    asyncio.to_thread(file.generate_original_markdown)
                    for file in files_to_process
                ],
                desc="> collecting original markdowns for caching",
            )

        asyncio.run(process_original_markdowns())
        clear_line()

        juvix_files = [
            file
            for file in files_to_process
            if is_juvix_markdown_file(file.absolute_filepath)
        ]

        if generate_juvix_markdown and self.env.juvix_enabled:
            with sync_tqdm(
                total=len(juvix_files), desc="> running Juvix markdown"
            ) as pbar:
                for file in juvix_files:
                    current_file = file.relative_filepath
                    pbar.set_postfix_str(
                        f"{Fore.MAGENTA}{current_file}{Style.RESET_ALL}"
                    )
                    file.generate_juvix_markdown_output()
                    pbar.update(1)
            clear_line()

        if generate_juvix_isabelle and self.env.juvix_enabled:
            with sync_tqdm(
                total=len(juvix_files), desc="> generating Isabelle theories"
            ) as pbar:
                for file in juvix_files:
                    current_file = file.relative_filepath
                    pbar.set_postfix_str(
                        f"{Fore.MAGENTA}{current_file}{Style.RESET_ALL}"
                    )
                    file.generate_isabelle_theories()
                    pbar.update(1)
            clear_line()

        clear_line()
        if generate_images:
            with sync_tqdm(
                total=len(files_to_process), desc="> processing images"
            ) as pbar:
                for file in files_to_process:
                    file.generate_images()
                    current_file = file.relative_filepath
                    pbar.set_postfix_str(
                        f"{Fore.MAGENTA}{current_file}{Style.RESET_ALL}"
                    )
                    pbar.update(1)

        if generate_wikilinks:

            @time_spent(message="> processing wikilinks")
            async def process_wikilinks():
                flist = (
                    files_to_process
                    if not self.force_wikilinks_generation
                    else self.files
                )
                await async_tqdm.gather(
                    *[
                        asyncio.to_thread(file.replaces_wikilinks_by_markdown_links)
                        for file in flist
                    ],
                    total=len(flist),
                    desc="> processing wikilinks",
                )

            asyncio.run(process_wikilinks())
            clear_line()

        if generate_snippets:

            async def process_snippets():
                await async_tqdm.gather(
                    *[asyncio.to_thread(file.render_snippets) for file in self.files],
                    total=len(self.files),
                    desc="> processing snippets",
                )

            asyncio.run(process_snippets())
            clear_line()

        self.update_cached_hash()
        self.save_juvix_modules_json()

    @time_spent(message="> removing html cache")
    def remove_html_cache(self) -> None:
        try:
            shutil.rmtree(self.env.CACHE_HTML_PATH)
        except Exception as e:
            log.error(f"Error removing HTML cache folder: {e}")

    def generate_html(self, force: bool = False) -> None:
        """
        Generate the HTML output for all the Juvix Markdown files. In case the
        `everything.md` file exists, we use it to generate the HTML output for
        all the Juvix Markdown files. Otherwise, we generate the HTML output for
        every Juvix Markdown file individually (not recommended).
        """
        if not self.env.JUVIX_ENABLED:
            log.info(
                f"{Fore.YELLOW}Juvix is not enabled, skipping HTML generation{Style.RESET_ALL}"
            )
            return

        needs_to_generate_html = self.is_html_cache_empty() or self.has_changes()
        if not needs_to_generate_html and not force:
            log.info("No files or changes detected, skipping HTML generation")
            return

        log.info("> adding auxiliary HTML files...")
        if self.everything_html_file and (needs_to_generate_html or force):
            self.everything_html_file._process_juvix_html(update_assets=True)

        if not self.is_html_cache_empty():
            return

        # we'll run the html generation over the entire collection so we can
        # have at least one html file to be used as the "everything" file

        self.remove_html_cache()
        self.env.CACHE_HTML_PATH.mkdir(parents=True, exist_ok=True)

        @time_spent(message="> generating HTML for files")
        def run_html_generation(files: List[EnhancedMarkdownFile]) -> None:
            juvix_files = [
                file for file in files if is_juvix_markdown_file(file.absolute_filepath)
            ]
            with sync_tqdm(
                total=len(juvix_files), desc="> generating HTML for files"
            ) as pbar:
                for file in juvix_files:
                    pbar.set_postfix_str(
                        f"{Fore.MAGENTA}{file.relative_filepath}{Style.RESET_ALL}"
                    )
                    file._process_juvix_html(update_assets=True)
                    pbar.update(1)

        run_html_generation(self.files)

    # --------------------------------------------------------------------------
    # Juvix dependencies
    # --------------------------------------------------------------------------

    @time_spent()
    def clean_juvix_dependencies(self) -> None:
        """
        Clean the Juvix dependencies. This is necessary to avoid typechecking
        errors when the Juvix compiler version changes.
        """
        if not self.env.CLEAN_DEPS:
            log.info(
                f"Skipping Juvix dependencies cleaning because "
                f"{Fore.GREEN}{self.env.CLEAN_DEPS}{Style.RESET_ALL} is not set."
            )
            return

        clean_command = [self.env.JUVIX_BIN, "clean", "--global"]
        res = subprocess.run(
            clean_command,
            cwd=self.env.DOCS_ABSPATH,
            capture_output=True,
            timeout=self.env.TIMELIMIT,
        )
        if res.returncode != 0:
            log.error(
                template_error_message(
                    filepath=None,
                    command=clean_command,
                    error_message=res.stderr.decode("utf-8"),
                )
            )

    @time_spent(message="> updating juvix dependencies", print_result=True)
    def update_juvix_dependencies(self) -> bool:
        """
        Update the Juvix dependencies.
        """
        update_command = [self.env.JUVIX_BIN, "dependencies", "update"]
        res = subprocess.run(
            update_command,
            cwd=self.env.DOCS_ABSPATH,
            capture_output=True,
            timeout=self.env.TIMELIMIT,
        )
        if res.returncode != 0:
            log.error(
                template_error_message(
                    filepath=None,
                    command=update_command,
                    error_message=res.stderr.decode("utf-8"),
                )
            )
            return False
        return True


class JuvixPlugin(BasePlugin):
    enhanced_collection: EnhancedMarkdownCollection
    wikilinks_plugin: WikilinksPlugin
    first_run: bool = True

    def on_startup(self, *, command: str, dirty: bool) -> None:
        clear_screen()

    def on_config(self, config: MkDocsConfig) -> MkDocsConfig:
        self.env = ENV(config)
        config = fix_site_url(config)

        self.env.SITE_DIR = config.get("site_dir", getenv("SITE_DIR", None))

        if os.getenv("SKIP_JUVIX"):
            self.env.JUVIX_ENABLED = False

        if self.env.JUVIX_ENABLED and not self.env.JUVIX_AVAILABLE:
            log.error(
                "You have requested Juvix but it is not available. Check your configuration."
                "\nEnvironment variables relevant to the build process:"
                "\n- JUVIX_ENABLED"
                "\n- JUVIX_BIN"
                "\n- JUVIX_PATH"
            )

        if self.first_run:
            self.wikilinks_plugin = WikilinksPlugin(config, self.env)
            config = self.wikilinks_plugin.on_config(config)
            self.enhanced_collection = EnhancedMarkdownCollection(
                env=self.env,
                config=config,
            )
            self.enhanced_collection.scanning_originals()
            self.add_footer_css_file_to_extra_css()

            if self.env.CLEAN_DEPS:
                self.enhanced_collection.clean_juvix_dependencies()
            if self.env.UPDATE_DEPS:
                self.enhanced_collection.update_juvix_dependencies()
            self.first_run = False

        return config

    def on_pre_build(self, config: MkDocsConfig) -> None:
        """
        Aim to be fault-tolerant, so we don't care if some files fail
        typechecking as part of the markdown processing, we include the error
        message as part of the content of the page
        """
        self.wikilinks_plugin.on_pre_build(config)  # This needs to be run first
        self.enhanced_collection.run_pipeline_on_collection()

    def on_files(self, files: Files, *, config: MkDocsConfig) -> Optional[Files]:
        """
        List of the files to be included in the final build. These are copied to
        the site directory.
        """
        self.wikilinks_plugin.on_files(files, config)
        Files(
            [
                file
                for file in files
                if file.abs_src_path
                and not set(Path(file.abs_src_path).parts)
                & set([".juvix-build", ".git"])
            ]
        )
        # if mkdocs.yml is in the files, we need to process the wikilinks
        mkdocs_config_filepath = self.env.ROOT_ABSPATH / "mkdocs.yml"
        if mkdocs_config_filepath in [file.abs_src_path for file in files]:
            self.enhanced_collection.force_wikilinks_generation = True
        return files

    def on_nav(self, nav, config: MkDocsConfig, files: Files):
        return nav

    def on_pre_page(self, page: Page, config: MkDocsConfig, files: Files) -> Page:
        return page

    def on_page_read_source(self, page: Page, config: MkDocsConfig) -> Optional[str]:
        abs_src_str: Optional[str] = page.file.abs_src_path
        if not abs_src_str:
            return None

        abs_src_path: Path = Path(abs_src_str)
        try:
            file: Optional[EnhancedMarkdownFile] = (
                self.enhanced_collection.get_enhanced_file_entry(abs_src_path)
            )
            if file:
                output = file.cache_filepath.read_text()
                return file.add_errors_to_markdown(output)
            else:
                log.error(
                    f"{Fore.RED}File not found in collection: "
                    f"{Fore.GREEN}{abs_src_path}{Style.RESET_ALL}, Try rerun "
                    f"the build process."
                )
        except Exception as e:
            log.error(f"Error getting file from collection: {e}")
        return None

    def on_page_markdown(
        self, markdown: str, page: Page, config: MkDocsConfig, files: Files
    ) -> Optional[str]:
        """
        For Juvix Markdown files, we remove the `.juvix` suffix from the file
        name. This is done to avoid having to change the file name in the
        navigation menu and to make the URLs consistent.
        """
        config["current_page"] = page
        abs_src_str: Optional[str] = page.file.abs_src_path

        if not abs_src_str:
            return markdown

        page.file.name = page.file.name.replace(".juvix", "")
        page.file.url = page.file.url.replace(".juvix", "")
        page.file.dest_uri = page.file.dest_uri.replace(".juvix", "")
        page.file.abs_dest_path = page.file.abs_dest_path.replace(".juvix", "")

        config["links_number"] = []
        return markdown

    def on_page_content(
        self, html: str, page: Page, config: MkDocsConfig, files: Files
    ) -> Optional[str]:
        return self.wikilinks_plugin.on_page_content(html, page, config, files)

    def on_post_page(self, output: str, page: Page, config: MkDocsConfig) -> str:
        soup = BeautifulSoup(output, "html.parser")
        for a in soup.find_all("a"):
            a["href"] = a["href"].replace(".juvix.html", ".html")
        return str(soup)

    def on_post_build(self, config: MkDocsConfig) -> None:
        log.debug("> post build task: generating HTML for files")
        if self.env.JUVIX_ENABLED:
            self.enhanced_collection.generate_html()
            self.move_html_cache_to_site_dir()
            self.enhanced_collection.update_cached_hash()
            self.enhanced_collection.save_juvix_modules_json()

        files_to_check = (
            self.enhanced_collection.files if self.enhanced_collection.files else []
        )
        for file in files_to_check:
            file.load_and_print_saved_error_messages()

    def move_html_cache_to_site_dir(self) -> None:
        """
        Move the HTML cache to the site directory. Otherwise, the HTML files
        pointing to the e.g., Standard Library files will not accessible.
        Notice that as part of the build process, we need to remove/rename the
        HTML files generated for the Juvix Markdown files. These files are not
        the right ones but the output by MkDocs.
        """
        if not self.env.SITE_DIR:
            log.error("No site directory specified. Skipping HTML cache move.")
            return

        log.info(
            f"> moving HTML cache to site directory: {Fore.GREEN}{self.env.SITE_DIR}{Style.RESET_ALL}"
        )

        dest_folder = Path(self.env.SITE_DIR)

        if not dest_folder.exists():
            log.info(f"Creating directory: {dest_folder}")
            dest_folder.mkdir(parents=True, exist_ok=True)

        # Patch: remove all the .html files in the destination folder of the
        # Juvix Markdown file to not lose the generated HTML files in the site
        # directory.

        try:
            shutil.copytree(self.env.CACHE_HTML_PATH, dest_folder, dirs_exist_ok=True)
        except Exception as e:
            log.error(f"Error moving HTML cache to site directory: {e}")
        return

    # --------------------------------------------------------------------------
    # Serve (Not important for the build process but for the development process)
    # --------------------------------------------------------------------------

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

                if (
                    ".juvix-build" in fpathstr
                    or self.env.CACHE_DIRNAME in fpathstr
                    or self.env.CACHE_ABSPATH.as_posix() in fpathstr
                    # .css files are not served
                    or fpathstr.endswith(".css")
                ):
                    return

                # clear the console
                clear_screen()
                fpath = Path(fpathstr)
                if fpath.is_relative_to(self.env.DOCS_ABSPATH):
                    log.info(
                        f"> {Fore.CYAN}Serving file: {Fore.GREEN}{fpath.relative_to(self.env.DOCS_ABSPATH)}{Style.RESET_ALL}"
                    )
                else:
                    log.info(
                        f"> {Fore.CYAN}Serving file: {Fore.GREEN}{fpath}{Style.RESET_ALL}"
                    )

                file: Optional[EnhancedMarkdownFile] = (
                    self.enhanced_collection.get_enhanced_file_entry(fpath)
                )
                if file:
                    if not file.changed_since_last_run():
                        if fpath.is_relative_to(self.env.DOCS_ABSPATH):
                            log.info(
                                f"{Fore.YELLOW}No changes detected in "
                                f"{Fore.GREEN}{fpath.relative_to(self.env.DOCS_ABSPATH) }{Style.RESET_ALL}"
                            )
                        else:
                            log.info(
                                f"{Fore.YELLOW}No changes detected in "
                                f"{Fore.GREEN}{fpath}{Style.RESET_ALL}"
                            )
                        return
                    else:
                        if fpath.is_relative_to(self.env.DOCS_ABSPATH):
                            log.info(
                                f"> changes detected in {Fore.GREEN}{fpath.relative_to(self.env.DOCS_ABSPATH)}{Style.RESET_ALL}"
                            )
                        else:
                            log.info(
                                f"> changes detected in {Fore.GREEN}{fpath}{Style.RESET_ALL}"
                            )
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

    # --------------------------------------------------------------------------
    # CSS file generation
    # --------------------------------------------------------------------------

    def _generate_code_block_footer_css_file(
        self, css_file: Path, compiler_version: Optional[str] = None
    ) -> Optional[Path]:
        css_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            if compiler_version is None:
                compiler_version = str(Version.parse(self.env.JUVIX_VERSION))

            compiler_version = f"Juvix v{compiler_version}".strip()
            css_file.write_text(
                (FIXTURES_PATH / "juvix_codeblock_footer.template")
                .read_text()
                .format(compiler_version=compiler_version)
            )
            if css_file.exists():
                return css_file
        except Exception as e:
            log.error(f"Error writing to CSS file: {e}")
        return None

    def add_footer_css_file_to_extra_css(self) -> MkDocsConfig:
        css_file = self.env.JUVIX_FOOTER_CSS_FILEPATH
        # Check if we need to create or update the codeblock footer CSS
        needs_to_update_cached_juvix_version = (
            not self.env.CACHE_JUVIX_VERSION_FILEPATH.exists()
            or Version.parse(self.env.CACHE_JUVIX_VERSION_FILEPATH.read_text().strip())
            != Version.parse(self.env.JUVIX_VERSION)
        )
        if needs_to_update_cached_juvix_version:
            log.debug(
                f"> Juvix version: {Back.WHITE}{Fore.BLACK}{self.env.JUVIX_VERSION.strip()}{Back.RESET}{Style.RESET_ALL}"
            )
            self.env.CACHE_JUVIX_VERSION_FILEPATH.write_text(self.env.JUVIX_VERSION)

        if not css_file.exists() or needs_to_update_cached_juvix_version:
            path = self._generate_code_block_footer_css_file(
                css_file, self.env.JUVIX_VERSION
            )
            if path:
                log.debug(
                    f"> codeblock footer CSS file generated and saved to "
                    f"{Fore.GREEN}{path.as_posix()}{Style.RESET_ALL}"
                )

        # Add CSS file to extra_css
        css_path = css_file.relative_to(self.env.DOCS_ABSPATH)
        if css_path not in self.config.get("extra_css", []):
            self.config["extra_css"] = self.config.get("extra_css", []) + [
                css_path.as_posix()
            ]
        return self.config


# --------------------------------------------------------------------------
# Auxiliary functions
# --------------------------------------------------------------------------


def parse_front_matter(content: str) -> Optional[dict]:
    if not content.startswith("---"):
        return None
    front_matter = ""
    end_index = content.find("---", 3)
    front_matter = content[3:end_index].strip()
    if end_index != -1:
        try:
            return yaml.safe_load(front_matter)
        except Exception as e:
            log.error(f"Error parsing metadata block: {e}")
    return None
