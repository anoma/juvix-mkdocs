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
import logging
import os
import re
import textwrap
import urllib
from pathlib import Path

from markdown import Extension
from markdown.preprocessors import Preprocessor
from pymdownx import util

log: logging.Logger = logging.getLogger("mkdocs")

MI = 1024 * 1024  # mebibyte (MiB)
DEFAULT_URL_SIZE = MI * 32
DEFAULT_URL_TIMEOUT = 10.0  # in seconds
DEFAULT_URL_REQUEST_HEADERS = {}

ROOT_DIR = Path(__file__).parent.parent.absolute()
CACHE_DIR: Path = ROOT_DIR / ".hooks"
JUVIX_OUTPUT = CACHE_DIR / ".MD"
DOCS_DIR = ROOT_DIR / "docs"


class SnippetMissingError(Exception):
    """Snippet missing exception."""


class SnippetPreprocessor(Preprocessor):
    """Handle snippets in Markdown content."""

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

    RE_SNIPPET_FILE = re.compile(
        r"(?i)(.*?)(?:(:[0-9]*)?(:[0-9]*)?|(:[a-z][-_0-9a-z]*)?)$"
    )

    def __init__(self, config, md):
        """Initialize."""

        base = config.get("base_path")
        if isinstance(base, (str, os.PathLike)):
            base = [base]
        self.base_path = [os.path.abspath(b) for b in base]
        self.restrict_base_path = config["restrict_base_path"]
        self.encoding = config.get("encoding")
        self.check_paths = config.get("check_paths")
        self.auto_append = config.get("auto_append")
        self.url_download = config["url_download"]
        self.url_max_size = config["url_max_size"]
        self.url_timeout = config["url_timeout"]
        self.url_request_headers = config["url_request_headers"]
        self.dedent_subsections = config["dedent_subsections"]
        self.tab_length = md.tab_length
        super().__init__()
        log.error("HEREEE"*30)

        self.download.cache_clear()

    def extract_section(
        self, section, lines, is_juvix=False, backup_lines=None, backup_path=None
    ):
        """Extract the specified section from the lines."""

        new_lines = []
        start = False
        found = False
        for _l in lines:
            ln = _l
            # Found a snippet section marker with our specified name
            m = self.RE_SNIPPET_SECTION.match(ln)

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
            if not is_juvix:
                raise SnippetMissingError(
                    "Snippet section '{}' could not be located".format(section)
                )
            elif backup_lines is not None:
                return self.extract_section(
                    section,
                    backup_lines,
                    is_juvix=False,
                    backup_lines=None,
                    backup_path=backup_path,
                )

            raise SnippetMissingError(
                f"""
The snippet section '{section}' could not be located.
This is likely because the section is inside a Juvix code block,
which is currently not supported in Juvix v0.6.6 or previous versions.
Consider wrapping the Juvix code block with a section snippet instead.

Error found in the file '{backup_path}' for the section '{section}'.
"""
            )
        return self.dedent(new_lines) if self.dedent_subsections else new_lines

    def dedent(self, lines):
        """De-indent lines."""

        return textwrap.dedent("\n".join(lines)).split("\n")

    def get_snippet_path(self, path):
        """Get snippet path."""

        snippet = None
        for base in self.base_path:
            if os.path.exists(base):
                if os.path.isdir(base):
                    if self.restrict_base_path:
                        filename = os.path.abspath(os.path.join(base, path))
                        # If the absolute path is no longer under the specified base path, reject the file
                        if not filename.startswith(base):
                            continue
                    else:
                        filename = os.path.join(base, path)
                    if os.path.exists(filename):
                        snippet = filename
                        break
                else:
                    dirname = os.path.dirname(base)
                    filename = os.path.join(dirname, path)
                    if os.path.exists(filename) and os.path.samefile(filename, base):
                        snippet = filename
                        break
        return snippet

    @functools.lru_cache()  # noqa: B019
    def download(self, url):
        """
        Actually download the snippet pointed to by the passed URL.

        The most recently used files are kept in a cache until the next reset.
        """

        http_request = urllib.request.Request(url, headers=self.url_request_headers)
        timeout = None if self.url_timeout == 0 else self.url_timeout
        with urllib.request.urlopen(http_request, timeout=timeout) as response:
            # Fail if status is not OK
            status = response.status if util.PY39 else response.code
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

    def parse_snippets(self, lines, file_name=None, is_url=False):
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
            m = self.RE_ALL_SNIPPETS.match(line)
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
                m = self.RE_SNIPPET.match(line)

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
                m = self.RE_SNIPPET_FILE.match(path)
                path = m.group(1).strip()

                if not path:
                    if self.check_paths:
                        raise SnippetMissingError(
                            "1. Snippet at path '{}' could not be found".format(path)
                        )
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

                just_raw = path and path.endswith("!")
                if just_raw:
                    path = path[:-1]

                snippet = self.get_snippet_path(path) if not url else path

                is_juvix = False

                if snippet:
                    original = snippet

                    if not just_raw and snippet.endswith(".juvix.md"):
                        snippet = JUVIX_OUTPUT / Path(
                            snippet.replace(".juvix.md", ".md")
                        ).relative_to(DOCS_DIR)
                        snippet = snippet.as_posix()
                        is_juvix = True

                    # This is in the stack and we don't want an infinite loop!
                    if snippet in self.seen:
                        continue

                    original_lines = []

                    if is_juvix:
                        with codecs.open(original, "r", encoding=self.encoding) as f:
                            original_lines = [ln.rstrip("\r\n") for ln in f]
                            if start is not None or end is not None:
                                s = slice(start, end)
                                original_lines = (
                                    self.dedent(original_lines[s])
                                    if self.dedent_subsections
                                    else original_lines[s]
                                )

                    if not url:
                        # Read file content
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
                                    section, s_lines, is_juvix, original_lines, original
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
                                raise
                            s_lines = []

                    # Process lines looking for more snippets
                    new_lines.extend(
                        [
                            space + l2
                            for l2 in self.parse_snippets(s_lines, snippet, is_url=url)
                        ]
                    )

                elif self.check_paths:
                    raise SnippetMissingError(
                        "2. Snippet at path '{}' could not be found".format(path)
                    )

        # Pop the current file name out of the cache
        if file_name:
            self.seen.remove(file_name)

        return new_lines

    def run(self, lines):
        """Process snippets."""

        self.seen = set()
        if self.auto_append:
            lines.extend(
                "\n\n-8<-\n{}\n-8<-\n".format("\n\n".join(self.auto_append)).split("\n")
            )

        return self.parse_snippets(lines)


class SnippetExtension(Extension):
    """Snippet extension."""

    def __init__(self, *args, **kwargs):
        """Initialize."""

        self.config = {
            "base_path": [["."], 'Base path for snippet paths - Default: ["."]'],
            "restrict_base_path": [
                True,
                "Restrict snippet paths such that they are under the base paths - Default: True",
            ],
            "encoding": ["utf-8", 'Encoding of snippets - Default: "utf-8"'],
            "check_paths": [
                False,
                'Make the build fail if a snippet can\'t be found - Default: "False"',
            ],
            "auto_append": [
                [],
                "A list of snippets (relative to the 'base_path') to auto append to the Markdown content - Default: []",
            ],
            "url_download": [
                False,
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
                False,
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

        self.md.preprocessors["snippet"].download.cache_clear()


def makeExtension(*args, **kwargs):
    """Return extension."""

    return SnippetExtension(*args, **kwargs)
