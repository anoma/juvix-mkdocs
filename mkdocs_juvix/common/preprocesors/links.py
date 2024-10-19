import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urljoin

from fuzzywuzzy import fuzz  # type: ignore
from markdown.preprocessors import Preprocessor  # type: ignore
from mkdocs.structure.pages import Page

from mkdocs_juvix.common.models import FileLoc, WikiLink
from mkdocs_juvix.env import ENV

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

log: logging.Logger = logging.getLogger("mkdocs")

REPORT_BROKEN_WIKILINKS = bool(os.environ.get("REPORT_BROKEN_WIKILINKS", False))


class WLPreprocessor(Preprocessor):
    def __init__(self, mkconfig, snippet_preprocessor, env: ENV):
        self.mkconfig = mkconfig
        self.snippet_preprocessor = snippet_preprocessor
        self.current_file = None
        self.links_found: List[Dict[str, Any]] = []
        self.env = env

    def run(self, lines):
        lines = self.snippet_preprocessor.run(lines)
        config = self.mkconfig
        current_page_url = None

        page = None

        if "current_page" in config and isinstance(config["current_page"], Page):
            page = config.get("current_page", None)
            if page:
                url_relative = self.env.DOCS_PATH / Path(
                    page.url.replace(".html", ".md")
                )
                current_page_url = url_relative.as_posix()

        if not current_page_url:
            log.warning("Current page URL not found. Wikilinks will not be processed.")
            return lines

        # Combine all lines into a single string
        full_text = "\n".join(lines)

        # Find all code blocks, HTML comments, and script tags
        code_blocks = list(re.finditer(r"```(?:[\s\S]*?)```", full_text, re.DOTALL))

        html_comments = list(re.finditer(r"<!--[\s\S]*?-->", full_text))
        script_tags = list(re.finditer(r"<script>[\s\S]*?</script>", full_text))

        # Create a set of ranges to ignore
        ignore_ranges = set()
        for match in code_blocks + html_comments + script_tags:
            ignore_ranges.add((match.start(), match.end()))

        # Find all wikilinks
        str_wikilinks = list(WIKILINK_PATTERN.finditer(full_text))

        replacements = []
        for str_wikilink_detected in str_wikilinks:
            is_in_ignore_range = False
            for start, end in ignore_ranges:
                if start <= str_wikilink_detected.start() < end:
                    is_in_ignore_range = True
                    break
            if not is_in_ignore_range:
                link = self.process_wikilink(
                    config, full_text, str_wikilink_detected, current_page_url
                )

                replacements.append(
                    (
                        str_wikilink_detected.start(),
                        str_wikilink_detected.end(),
                        link.markdown(),
                    )
                )

        for start, end, new_text in reversed(replacements):
            full_text = full_text[:start] + new_text + full_text[end:]

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
