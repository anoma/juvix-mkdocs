import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import numpy as np  # type: ignore
from colorama import Fore, Style  # type: ignore
from fuzzywuzzy import fuzz  # type: ignore
from markdown.preprocessors import Preprocessor  # type: ignore
from mkdocs.plugins import get_plugin_logger
from mkdocs.structure.pages import Page
from ncls import NCLS  # type: ignore

from mkdocs_juvix.common.models import FileLoc, WikiLink
from mkdocs_juvix.env import ENV
from mkdocs_juvix.snippets import SnippetPreprocessor

WIKILINK_PATTERN = re.compile(
    r"""
(?:\\)?\[\[
(?:(?P<hint>[^:|\]]+):)?
(?P<page>[^|\]#]+)
(?:\#(?P<anchor>[^|\]]+))?
(?:\|(?P<display>[^\]]+))?
\]\]
""",
    re.VERBOSE,
)


log = get_plugin_logger(f"{Fore.BLUE}[juvix_mkdocs-wikilinks]{Style.RESET_ALL}")

REPORT_BROKEN_WIKILINKS = bool(os.environ.get("REPORT_BROKEN_WIKILINKS", False))


class WLPreprocessor(Preprocessor):
    run_snippet_preprocessor: bool = True

    def __init__(self, mkconfig, snippet_preprocessor, env: Optional[ENV] = None):
        self.mkconfig = mkconfig
        if env is None:
            self.env = ENV(mkconfig)
        else:
            self.env = env

        self.snippet_preprocessor: SnippetPreprocessor = snippet_preprocessor
        # remove the mkdocs_juvix.snippets plugin from the config
        if "mkdocs_juvix.snippets" in self.mkconfig.mdx_configs:
            self.mkconfig.mdx_configs.pop("mkdocs_juvix.snippets")
            self.run_snippet_preprocessor = False

        self.current_file = None
        self.links_found: List[Dict[str, Any]] = []

    def run(self, lines) -> List[str]:
        current_page_url = None
        original_filepath = None

        if "current_page" in self.mkconfig and isinstance(
            self.mkconfig["current_page"], Page
        ):
            page = self.mkconfig.get("current_page", None)

            if page:
                src_path = page.file.abs_src_path
                if not src_path:
                    log.warning(
                        "Source path not found. Wikilinks will not be processed."
                    )
                    return lines
                original_filepath = Path(src_path)
                url_relative = self.env.DOCS_PATH / Path(
                    page.url.replace(".html", ".md")
                )
                current_page_url = url_relative.as_posix()

        if not current_page_url:
            log.warning("Current page URL not found. Wikilinks will not be processed.")
            return lines

        filepath = Path(current_page_url).absolute()
        try:
            rel_to_docs = filepath.relative_to(self.env.DOCS_ABSPATH)
        except ValueError:
            rel_to_docs = filepath.relative_to(self.env.DOCS_PATH)
        finally:
            rel_to_docs = filepath

        try:
            cache_filepath: Optional[Path] = (
                self.env.get_filepath_for_wikilinks_in_cache(filepath)
            )
        except Exception as e:
            log.error(f"Error getting cache filepath for file {rel_to_docs}: {e}")
            return lines

        if original_filepath:
            self.env.update_hash_file(original_filepath)

        if (
            cache_filepath
            and cache_filepath.exists()
            and original_filepath
            and not self.env.new_or_changed_or_not_exists(original_filepath)
        ):
            return cache_filepath.read_text().split("\n")

        time_start = time.time()

        # if self.run_snippet_preprocessor:
        #     lines = self.snippet_preprocessor.run(lines)

        # Combine all lines into a single string
        full_text = "\n".join(lines)
        # Find all code blocks, HTML comments, and script tags in a single pass
        ignore_blocks = re.compile(
            r"(```(?:[\s\S]*?)```|<!--[\s\S]*?-->|<script>[\s\S]*?</script>)", re.DOTALL
        )

        intervals = []
        try:
            for match in ignore_blocks.finditer(full_text):
                intervals.append((match.start(), match.end(), 1))
        except TimeoutError:
            log.error("Timeout occurred while processing ignore patterns")
            return lines
        except Exception as e:
            log.error(f"Error occurred while processing ignore patterns: {str(e)}")
            return lines
        intervals_where_not_to_look = None
        if intervals:
            starts, ends, ids = map(np.array, zip(*intervals))
            intervals_where_not_to_look = NCLS(starts, ends, ids)

        # Find all wikilinks
        str_wikilinks = list(WIKILINK_PATTERN.finditer(full_text))

        replacements = []
        for m in str_wikilinks:
            start, end = m.start(), m.end()
            if intervals_where_not_to_look and not list(
                intervals_where_not_to_look.find_overlap(start, end)
            ):
                link = self.process_wikilink(
                    self.mkconfig, full_text, m, current_page_url
                )
                replacements.append(
                    (
                        start,
                        end,
                        link.markdown(),
                    )
                )
        for start, end, new_text in reversed(replacements):
            full_text = full_text[:start] + new_text + full_text[end:]
        time_end = time.time()
        log.debug(
            f"Snippet and wikilinks processing took {Fore.GREEN}{(time_end - time_start):.5f}{Style.RESET_ALL} seconds on file {Fore.GREEN}{rel_to_docs}{Style.RESET_ALL}"
        )

        if cache_filepath:
            try:
                cache_filepath.parent.mkdir(parents=True, exist_ok=True)
                cache_filepath.write_text(full_text)
            except Exception as e:
                log.error(
                    f"Error writing wikilinks to cache for file {original_filepath}: {e}"
                )
        return full_text.split("\n")

    def process_wikilink(self, config, full_text, match, current_page_url) -> WikiLink:
        """Adds the link to the links_found list and return the link"""
        loc = FileLoc(
            current_page_url,
            full_text[: match.start()].count("\n") + 1,
            match.start() - full_text.rfind("\n", 0, match.start()),
        )
        link = WikiLink(
            page=match.group("page"),
            hint=match.group("hint"),
            anchor=match.group("anchor"),
            display=match.group("display"),
            loc=loc,
        )

        link_page = link.page
        # print white space with "X"

        if (
            len(config["url_for"].get(link_page, [])) > 1
            and link_page in config["url_for"]
        ):
            possible_pages = config["url_for"][link_page]
            hint = link.hint if link.hint else ""
            token = hint + link_page
            coefficients = {
                p: fuzz.WRatio(fun_normalise(p), token) for p in possible_pages
            }

            sorted_pages = sorted(
                possible_pages, key=lambda p: coefficients[p], reverse=True
            )

            link.html_path = sorted_pages[0]
            log.warning(
                f"""{loc}\nReference: '{link_page}' at '{loc}' is ambiguous. It could refer to any of the
                following pages:\n  {', '.join(sorted_pages)}\nPlease revise the page alias or add a path hint to disambiguate,
                e.g. [[folderHintA/subfolderHintB:page#anchor|display text]].
                Our choice: {link.html_path}"""
            )

        elif link_page in config["url_for"]:
            link.html_path = config["url_for"].get(link_page, [""])[0]
            log.debug(f"Single page found. html_path: {link.html_path}")
        else:
            log.debug("Link page not in config['url_for']")

        if link.html_path:
            link.html_path = urljoin(
                config["site_url"],
                (link.html_path.replace(".juvix", "").replace(".md", ".html")),
            )

            # Update links_found TODO: move this to the model
            try:
                url_page = config["url_for"][link_page][0]
                if url_page in config["nodes"]:
                    actuallink = config["nodes"][url_page]
                    if actuallink:
                        pageName = actuallink["page"].get("names", [""])[0]
                        html_path: str = link.html_path if link.html_path else ""
                        self.links_found.append(
                            {
                                "index": actuallink["index"],
                                "path": actuallink["page"]["path"],
                                "url": html_path,
                                "name": pageName,
                            }
                        )

            except Exception as e:
                log.error(f"Error processing link: {link_page}\n {e}")
        else:
            msg = f"{loc}:\nUnable to resolve reference\n  {link_page}"
            if REPORT_BROKEN_WIKILINKS:
                log.warning(msg)
            config["wikilinks_issues"] += 1

        if len(self.links_found) > 0:
            config.update({"links_number": self.links_found})

        return link


def fun_normalise(s):
    return (
        s.replace("_", " ")
        .replace("-", " ")
        .replace(":", " ")
        .replace("/", " ")
        .replace(".md", "")
    )
