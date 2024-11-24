"""
Modified version of pymdownx.snippet extension to support custom Juvix/Isabelle
snippets by Jonathan Prieto-Cubides 2024.

Snippet ---8<---.

pymdownx.snippet Inject snippets

MIT license.

Copyright (c) 2017 Isaac Muse <isaacmuse@gmail.com>

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

import codecs
import functools
import re
import sys
import textwrap
import urllib
from pathlib import Path
from typing import Any, List, Optional

from colorama import Fore, Style  # type: ignore
from markdown import Extension  # type: ignore
from markdown.preprocessors import Preprocessor  # type: ignore

from mkdocs_juvix.env import ENV
from mkdocs_juvix.logger import log
from mkdocs_juvix.utils import time_spent as time_spent_decorator


def time_spent(message: Optional[Any] = None, print_result: bool = False):
    return time_spent_decorator(log=log, message=message, print_result=print_result)


MI = 1024 * 1024  # mebibyte (MiB)
DEFAULT_URL_SIZE = MI * 32
DEFAULT_URL_TIMEOUT = 10.0  # in seconds
DEFAULT_URL_REQUEST_HEADERS = {}  # type: ignore

PY39 = (3, 9) <= sys.version_info

RE_ALL_SNIPPETS = re.compile(
    r"""(?x)
    ^(?P<space>[ \t]*)
    (?P<escape>;*)
    (?P<all>
        (?P<inline_marker>-{1,}8<-{1,}[ \t]+)
        (?P<snippet>(?:"(?:\\"|[^"\n\r])+?"|'(?:\\'|[^'\n\r])+?'))(?![ \t]) |
        (?P<block_marker>-{1,}8<-{1,})(?![ \t])
    )\r?$
    """
)

RE_SNIPPET = re.compile(
    r"""(?x)
    ^(?P<space>[ \t]*)
    (?P<snippet>.*?)\r?$
    """
)

RE_SNIPPET_SECTION = re.compile(
    r"""(?xi)
    ^(?P<pre>.*?)
    (?P<escape>;*)
    (?P<inline_marker>-{1,}8<-{1,}[ \t]+)
    (?P<section>\[[ \t]*(?P<type>start|end)[ \t]*:[ \t]*(?P<name>[a-z][-_0-9a-z]*)[ \t]*\])
    (?P<post>.*?)$
    """
)

RE_SNIPPET_FILE = re.compile(r"(?i)(.*?)(?:(:[0-9]*)?(:[0-9]*)?|(:[a-z][-_0-9a-z]*)?)$")


class SnippetMissingError(Exception):
    """Snippet missing exception."""


class SnippetPreprocessor(Preprocessor):
    """Handle snippets in Markdown content."""

    base_path: List[Path]
    restrict_base_path: bool
    encoding: str
    check_paths: bool
    auto_append: List[str]
    url_download: bool
    url_max_size: int
    url_timeout: float
    url_request_headers: dict
    dedent_subsections: bool
    tab_length: int
    env: ENV

    def __init__(
        self,
        config: Optional[Any] = None,
        md: Optional[Any] = None,
        env: Optional[ENV] = None,
    ):
        """Initialize."""

        self.base_path: List[Path] = [Path("."), Path("includes")]
        self.restrict_base_path: bool = True
        self.encoding: str = "utf-8"
        self.check_paths: bool = True
        self.auto_append: List[str] = []
        self.url_download: bool = True
        self.url_max_size: int = DEFAULT_URL_SIZE
        self.url_timeout: float = DEFAULT_URL_TIMEOUT
        self.url_request_headers: dict = DEFAULT_URL_REQUEST_HEADERS
        self.dedent_subsections: bool = True
        self.tab_length: int = 2

        if env is None:
            self.env = ENV(config)
        else:
            self.env = env

        base = self.base_path

        if config is not None:
            base = config.get("base_path")
            self.base_path = []
            for b in base:
                if not Path(b).exists():
                    continue
                self.base_path.append(Path(b).absolute())

            self.restrict_base_path = config["restrict_base_path"]
            self.encoding = config.get("encoding")
            self.check_paths = config.get("check_paths")
            self.auto_append = config.get("auto_append")
            self.url_download = config["url_download"]
            self.url_max_size = config["url_max_size"]
            self.url_timeout = config["url_timeout"]
            self.url_request_headers = config["url_request_headers"]
            self.dedent_subsections = config["dedent_subsections"]

            if md is not None and hasattr(md, "tab_length"):
                self.tab_length = md.tab_length
            else:
                self.tab_length = 2

        super().__init__()
        self.download.cache_clear()

    def extract_section(
        self,
        section,
        lines,
        backup_lines=None,
        backup_path=None,
    ):
        """Extract the specified section from the lines."""
        new_lines = []
        start = False
        found = False
        for _l in lines:
            ln = _l
            # Found a snippet section marker with our specified name
            m = RE_SNIPPET_SECTION.match(ln)

            # Handle escaped line
            if m and start and m.group("escape"):
                ln = (
                    m.group("pre")
                    + m.group("escape").replace(";", "", 1)
                    + m.group("inline_marker")
                    + m.group("section")
                    + m.group("post")
                )

            # Found a section we are looking for.
            elif m is not None and m.group("name") == section:
                # We found the start
                if not start and m.group("type") == "start":
                    start = True
                    found = True
                    continue

                # Ignore duplicate start
                elif start and m.group("type") == "start":
                    continue

                # We found the end
                elif start and m.group("type") == "end":
                    start = False
                    break

                # We found an end, but no start
                else:
                    break

            # Found a section we don't care about, so ignore it.
            elif m and start:
                continue

            # We are currently in a section, so append the line
            if start:
                new_lines.append(ln)
        if not found and self.check_paths:
            if backup_lines is not None:
                return self.extract_section(
                    section,
                    backup_lines,
                    backup_lines=None,
                    backup_path=backup_path,
                )
            new_lines.append(
                f"\n!!! failure\n\n"
                f"    Snippet section '{section}' not found! Please report this issue on GitHub!\n"
            )
        return self.dedent(new_lines) if self.dedent_subsections else new_lines

    def dedent(self, lines):
        """De-indent lines."""

        return textwrap.dedent("\n".join(lines)).split("\n")

    @functools.lru_cache()  # noqa: B019
    def download(self, url):
        """
        Actually download the snippet pointed to by the passed URL.

        The most recently used files are kept in a cache until the next reset.
        """

        http_request = urllib.request.Request(url, headers=self.url_request_headers)  # type: ignore
        timeout = None if self.url_timeout == 0 else self.url_timeout
        with urllib.request.urlopen(http_request, timeout=timeout) as response:  # type: ignore
            # Fail if status is not OK
            status = response.status if PY39 else response.code
            if status != 200:
                raise SnippetMissingError("Cannot download snippet '{}'".format(url))

            # We provide some basic protection against absurdly large files.
            # 32MB is chosen as an arbitrary upper limit. This can be raised if desired.
            length = response.headers.get("content-length")
            if length is None:
                raise ValueError("Missing content-length header")
            content_length = int(length)

            if self.url_max_size != 0 and content_length >= self.url_max_size:
                raise ValueError(
                    "refusing to read payloads larger than or equal to {}".format(
                        self.url_max_size
                    )
                )

            # Nothing to return
            if content_length == 0:
                return [""]

            # Process lines
            return [
                ln.decode(self.encoding).rstrip("\r\n") for ln in response.readlines()
            ]

    def _get_snippet_path(self, base_paths: List[Path], path: Path):
        snippet = None
        for base in base_paths:
            if Path(base).exists():
                if Path(base).is_dir():
                    log.debug(
                        f"Base path is a directory: {Fore.MAGENTA}{base}{Style.RESET_ALL}"
                    )
                    if self.restrict_base_path:
                        filename = Path(base).absolute() / path
                        log.debug(
                            f"Checking restricted base path: {Fore.MAGENTA}{filename}{Style.RESET_ALL}"
                        )
                        if not filename.as_posix().startswith(base.as_posix()):
                            log.debug(
                                f"Rejected file not under base path: {Fore.MAGENTA}{filename}{Style.RESET_ALL}"
                            )
                            continue
                        else:
                            if filename.exists():
                                log.debug(
                                    f"Accepted file under base path: {Fore.MAGENTA}{filename}{Style.RESET_ALL}"
                                )
                                return filename
                            else:
                                log.debug(
                                    f"File does not exist: {Fore.MAGENTA}{filename}{Style.RESET_ALL}"
                                )
                    else:
                        filename = Path(base).absolute() / path
                        log.debug(
                            f"Checking unrestricted base path: {Fore.MAGENTA}{filename}{Style.RESET_ALL}"
                        )
                        if filename.exists():
                            log.debug(
                                f"Snippet found: {Fore.MAGENTA}{filename}{Style.RESET_ALL}"
                            )
                            snippet = filename
                            break
                else:
                    dirname = Path(base).parent
                    filename = dirname / path
                    log.debug(
                        f"Checking file in directory: {Fore.MAGENTA}{filename}{Style.RESET_ALL}"
                    )
                    if filename.exists():
                        log.debug(
                            f"Snippet found: {Fore.MAGENTA}{filename}{Style.RESET_ALL}"
                        )
                        snippet = filename
                        break
        return snippet

    def get_snippet_path(self, path: Path | str):
        """Get snippet path."""
        log.debug(f"{Fore.CYAN}> getting snippet path for {path}{Style.RESET_ALL}")
        if isinstance(path, str):
            path = Path(path)
        base_paths = self.base_path
        just_raw = path and path.as_posix().endswith("!")
        search_for_juvix_isabelle_output = False

        if path and path.as_posix().endswith(".juvix.md!thy"):
            search_for_juvix_isabelle_output = True
            log.debug(
                f"Path ends with .juvix.md!thy: {Fore.MAGENTA}{path}{Style.RESET_ALL}"
            )
            juvix_path = path.with_name(path.name.replace("!thy", ""))
            log.debug(f"Juvix path: {Fore.MAGENTA}{juvix_path}{Style.RESET_ALL}")
            # isabelle_path = juvix_path
            isabelle_path = (
                self.env.compute_filepath_for_juvix_isabelle_output_in_cache(juvix_path)
            )
            log.debug(f"Isabelle path: {Fore.MAGENTA}{isabelle_path}{Style.RESET_ALL}")
            if isabelle_path is not None and isabelle_path.exists():
                path = isabelle_path
                log.debug(
                    f"Changed path to Isabelle file: {Fore.MAGENTA}{path}{Style.RESET_ALL}"
                )

        if just_raw:
            path = Path(path.as_posix()[:-1])
            log.debug(f"Requested raw snippet: {path}")
            base_paths = [self.env.DOCS_ABSPATH]

        if path.is_relative_to(self.env.DOCS_ABSPATH):
            path = path.relative_to(self.env.DOCS_ABSPATH)
        if path.is_relative_to("docs"):
            log.debug(f"Path is relative to docs: {path}")
            path = path.relative_to("docs")
        if path.is_relative_to("./docs"):
            log.debug(f"Path is relative to ./docs: {path}")
            path = path.relative_to("./docs")

        if path.is_relative_to(self.env.ISABELLE_OUTPUT_PATH):
            log.debug(f"Path is relative to Isabelle output path: {path}")
            path = path.relative_to(self.env.ISABELLE_OUTPUT_PATH)
        if path.is_relative_to(self.env.ISABELLE_THEORIES_DIRNAME):
            log.debug(f"Path is relative to Isabelle theories directory: {path}")
            path = path.relative_to(self.env.ISABELLE_THEORIES_DIRNAME)

        if path.as_posix().endswith(".thy") or search_for_juvix_isabelle_output:
            log.debug(f"Path is an Isabelle file: {path}")
            base_paths = [self.env.ISABELLE_OUTPUT_PATH]

        if not just_raw and path.as_posix().endswith(".juvix.md"):
            path = Path(path.as_posix().replace(".juvix.md", ".md"))

        return self._get_snippet_path(base_paths, path)

    def parse_snippets(
        self,
        lines,
        file_name: Optional[Path | str] = None,
        is_url: bool = False,
    ) -> list[str] | Exception:
        """Parse snippets snippet."""
        if file_name:
            # Track this file.
            self.seen.add(file_name)

        new_lines = []
        inline = False
        block = False

        for idx, line in enumerate(lines):
            # Check for snippets on line
            inline = False

            m = RE_ALL_SNIPPETS.match(line)
            if m:
                if m.group("escape"):
                    # The snippet has been escaped, replace first `;` and continue.
                    new_lines.append(line.replace(";", "", 1))
                    continue

                if block and m.group("inline_marker"):
                    # Don't use inline notation directly under a block.
                    # It's okay if inline is used again in sub file though.
                    continue

                elif m.group("inline_marker"):
                    # Inline
                    inline = True

                else:
                    # Block
                    block = not block
                    continue
            elif not block:
                # Not in snippet, and we didn't find an inline,
                # so just a normal line
                new_lines.append(line)
                continue

            if block and not inline:
                # We are in a block and we didn't just find a nested inline
                # So check if a block path
                m = RE_SNIPPET.match(line)

            if m:
                # Get spaces and snippet path.  Remove quotes if inline.
                space = m.group("space").expandtabs(self.tab_length)
                path = (
                    m.group("snippet")[1:-1].strip()
                    if inline
                    else m.group("snippet").strip()
                )

                if not inline:
                    # Block path handling
                    if not path:
                        # Empty path line, insert a blank line
                        new_lines.append("")
                        continue

                # Ignore commented out lines
                if path.startswith(";"):
                    continue

                # Get line numbers (if specified)
                end = None
                start = None
                section = None
                log.debug(f"{Fore.YELLOW}>>>>>> path: {path}{Style.RESET_ALL}")
                m = RE_SNIPPET_FILE.match(path)
                if m is None:
                    log.debug(f"{Fore.YELLOW}>>>>>> m is None{Style.RESET_ALL}")
                    continue

                path = m.group(1).strip()

                if not path:
                    if self.check_paths:
                        return SnippetMissingError("No path specified for snippet")
                    else:
                        continue

                ending = m.group(3)
                if ending and len(ending) > 1:
                    end = int(ending[1:])
                starting = m.group(2)
                if starting and len(starting) > 1:
                    start = max(0, int(starting[1:]) - 1)
                section_name = m.group(4)
                if section_name:
                    section = section_name[1:]

                # Ignore path links if we are in external, downloaded content
                is_link = path.lower().startswith(("https://", "http://"))
                if is_url and not is_link:
                    continue

                # If this is a link, and we are allowing URLs, set `url` to true.
                # Make sure we don't process `path` as a local file reference.
                url = self.url_download and is_link

                found_snippet = self.get_snippet_path(path)

                if found_snippet is None:
                    if self.check_paths:
                        msg = f"Error type 3. Snippet at path '{Fore.MAGENTA}{path}{Style.RESET_ALL}' could not be found"
                        return SnippetMissingError(msg)

                log.debug(f"{Fore.GREEN}Snippet found:{found_snippet}{Style.RESET_ALL}")

                if found_snippet is None:
                    log.debug(
                        f"<snippet> Snippet not found in cache, using path: {path}"
                    )
                    snippet = path
                else:
                    log.debug(
                        f"<snippet> Snippet found in cache, using filepath: {found_snippet}"
                    )
                    snippet = (
                        found_snippet.as_posix() if found_snippet and not url else path
                    )

                if snippet:
                    original = snippet

                    if isinstance(snippet, Path):
                        snippet = snippet.as_posix()

                    # This is in the stack and we don't want an infinite loop!
                    if snippet in self.seen:
                        continue

                    if not url:
                        # Read file content
                        if isinstance(snippet, Path):
                            snippet = snippet.as_posix()
                        with codecs.open(snippet, "r", encoding=self.encoding) as f:
                            s_lines = [ln.rstrip("\r\n") for ln in f]
                            if start is not None or end is not None:
                                s = slice(start, end)
                                s_lines = (
                                    self.dedent(s_lines[s])
                                    if self.dedent_subsections
                                    else s_lines[s]
                                )
                            elif section:
                                s_lines = self.extract_section(
                                    section,
                                    s_lines,
                                    original,
                                )
                            else:
                                in_metadata = False
                                start = 0
                                for i, ln in enumerate(s_lines):
                                    if ln.startswith("---"):
                                        if in_metadata:
                                            start = i
                                            break
                                        in_metadata = not in_metadata
                                s_lines = s_lines[start + 1 :]
                    else:
                        # Read URL content
                        try:
                            s_lines = self.download(snippet)
                            if start is not None or end is not None:
                                s = slice(start, end)
                                s_lines = (
                                    self.dedent(s_lines[s])
                                    if self.dedent_subsections
                                    else s_lines[s]
                                )
                            elif section:
                                s_lines = self.extract_section(section, s_lines)
                        except SnippetMissingError:
                            if self.check_paths:
                                return SnippetMissingError(
                                    f"Error type 2 while processing {Fore.MAGENTA}{file_name}{Style.RESET_ALL} when trying to extract snippet: {snippet}"
                                )
                            s_lines = []

                    # Process lines looking for more snippets
                    parsed_snippets = self.parse_snippets(
                        s_lines,
                        file_name=snippet,
                        is_url=url,
                    )
                    if isinstance(parsed_snippets, Exception):
                        return parsed_snippets
                    new_lines.extend([space + l2 for l2 in parsed_snippets])

                elif self.check_paths:
                    raise SnippetMissingError(
                        f"3. Snippet at path '{path}' could not be found!"
                    )

        # Pop the current file name out of the cache
        if file_name:
            self.seen.remove(file_name)

        return new_lines

    def run(
        self, lines: List[str], file_name: Optional[Path | str] = None
    ) -> List[str] | Exception:
        """Process snippets."""
        self.seen: set[Path | str] = set()
        if self.auto_append:
            lines.extend(
                "\n\n-8<-\n{}\n-8<-\n".format("\n\n".join(self.auto_append)).split("\n")
            )
        return self.parse_snippets(lines, file_name=file_name)


class SnippetExtension(Extension):
    """Snippet extension."""

    def __init__(self, *args, **kwargs):
        """Initialize."""
        self.config = {
            "base_path": [
                [".", "includes"],
                'Base path for snippet paths - Default: ["."]',
            ],
            "restrict_base_path": [
                True,
                "Restrict snippet paths such that they are under the base paths - Default: True",
            ],
            "encoding": ["utf-8", 'Encoding of snippets - Default: "utf-8"'],
            "check_paths": [
                True,
                'Make the build fail if a snippet can\'t be found - Default: "False"',
            ],
            "auto_append": [
                [],
                "A list of snippets (relative to the 'base_path') to auto append to the Markdown content - Default: []",
            ],
            "url_download": [
                True,
                'Download external URLs as snippets - Default: "False"',
            ],
            "url_max_size": [
                DEFAULT_URL_SIZE,
                "External URL max size (0 means no limit)- Default: 32 MiB",
            ],
            "url_timeout": [
                DEFAULT_URL_TIMEOUT,
                "Defualt URL timeout (0 means no timeout) - Default: 10 sec",
            ],
            "url_request_headers": [
                DEFAULT_URL_REQUEST_HEADERS,
                "Extra request Headers - Default: {}",
            ],
            "dedent_subsections": [
                True,
                "Dedent subsection extractions e.g. 'sections' and/or 'lines'.",
            ],
        }

        super().__init__(*args, **kwargs)

    def extendMarkdown(self, md):
        """Register the extension."""

        self.md = md
        md.registerExtension(self)
        config = self.getConfigs()
        snippet = SnippetPreprocessor(config, md)
        md.preprocessors.register(snippet, "snippet", 32)

    def reset(self):
        """Reset."""

        try:
            self.md.preprocessors["snippet"].download.cache_clear()  # type: ignore
        except AttributeError:
            log.warning("Failed to clear snippet cache, download method not found")


def makeExtension(*args, **kwargs):
    """Return extension."""

    return SnippetExtension(*args, **kwargs)
