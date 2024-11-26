"""
Support for wiki-style links in MkDocs in tandem of pydownx_snippets.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from os import getenv
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

from colorama import Fore, Style  # type: ignore
from markdown.extensions import Extension  # type: ignore
from mkdocs.config.defaults import MkDocsConfig
from mkdocs.structure.files import File, Files
from mkdocs.structure.pages import Page
from mkdocs.utils import meta

from mkdocs_juvix.common.models.entry import ResultEntry
from mkdocs_juvix.common.preprocesors.links import WLPreprocessor
from mkdocs_juvix.common.utils import fix_site_url, get_page_title
from mkdocs_juvix.env import ENV
from mkdocs_juvix.logger import log

files_relation: List[ResultEntry] = []
EXCLUDED_DIRS = [
    ".git",
    ".juvix_build",
    ".vscode",
    ".hooks",
    ".github",
]


class WLExtension(Extension):
    config: MkDocsConfig
    env: Optional[ENV] = None
    base_path: List[Path] = []

    def __init__(self, config: MkDocsConfig, env: Optional[ENV] = None):
        self.config = config
        if env is None:
            self.env = ENV(config)
        else:
            self.env = env

    def __repr__(self):
        return "WLExtension"

    def extendMarkdown(self, md):  # noqa: N802
        self.md = md
        md.registerExtension(self)
        self.wlpp = WLPreprocessor(self.config, self.env)
        md.preprocessors.register(self.wlpp, "wl-pp", 100)


TOKEN_LIST_WIKILINKS: str = "<!-- list_wikilinks -->"


class WikilinksPlugin:
    env: Optional[ENV] = None

    def __init__(self, config: MkDocsConfig, env: Optional[ENV] = None):
        self.config = config
        if env is None:
            self.env = ENV(config)
        else:
            self.env = env
        self.LINKS_JSONNAME: str = getenv("LINKS_JSONNAME", "aliases.json")
        self.GRAPH_JSONNAME: str = getenv("GRAPH_JSONNAME", "graph.json")
        self.NODES_JSONNAME: str = getenv("NODES_JSONNAME", "nodes.json")
        self.PAGE_LINK_DIAGSNAME: str = getenv("PAGE_LINK_DIAGSNAME", "page_link_diags")
        self.LINKS_JSON: Path = self.env.CACHE_PATH / self.LINKS_JSONNAME
        self.GRAPH_JSON: Path = self.env.CACHE_PATH / self.GRAPH_JSONNAME
        self.NODES_JSON: Path = self.env.CACHE_PATH / self.NODES_JSONNAME
        self.PAGE_LINK_DIAGS: Path = self.env.CACHE_PATH / self.PAGE_LINK_DIAGSNAME
        self.REPORT_BROKEN_WIKILINKS: bool = bool(
            getenv("REPORT_BROKEN_WIKILINKS", True)
        )

    def on_config(self, config: MkDocsConfig, **kwargs) -> MkDocsConfig:
        config = fix_site_url(config)
        if self.env is None:
            self.env = ENV(config)

        self.LINKS_JSON = self.env.CACHE_PATH / self.LINKS_JSONNAME
        self.GRAPH_JSON = self.env.CACHE_PATH / self.GRAPH_JSONNAME
        self.NODES_JSON = self.env.CACHE_PATH / self.NODES_JSONNAME

        self.PAGE_LINK_DIAGS = self.env.CACHE_PATH / self.PAGE_LINK_DIAGSNAME
        self.PAGE_LINK_DIAGS.mkdir(parents=True, exist_ok=True)

        log.debug("Wikilinks plugin initialized")
        return config

    def on_pre_build(self, config: MkDocsConfig) -> None:
        config["aliases_for"] = {}
        config["url_for"] = {}
        config["wikilinks_issues"] = 0
        config["nodes"] = {}
        node_index = 0

        for _url, page in _extract_aliases_from_nav(config["nav"]):
            url = urljoin(config["site_url"], _url)

            config["aliases_for"][url] = [page]
            config["url_for"].setdefault(page, [])
            config["url_for"][page].append(url)

            # Create a new entry if the URL is not already present in config["nodes"]
            if url not in config["nodes"]:
                config["nodes"][url] = {
                    "index": node_index,
                    "page": {"names": [], "path": _url.replace("./", "")},
                }
            # Append the page to the "names" list
            config["nodes"][url]["page"]["names"].append(page)
            node_index += 1

        if self.NODES_JSON.exists():
            self.NODES_JSON.unlink()

        with open(self.NODES_JSON, "w") as f:
            json.dump(
                {
                    "nodes": config.get("nodes", {}),
                },
                f,
                indent=2,
            )
        config["current_page"] = None  # current page being processed
        return

    def on_files(self, files: Files, config: MkDocsConfig) -> None:
        """When MkDocs loads its files, extract aliases from any Markdown files
        that were found.
        """
        SKIP_DIRS = [".juvix-build", ".hooks", ".git"]
        files = Files(
            [
                file
                for file in files
                if not set(Path(file.src_uri).parts) & set(SKIP_DIRS)
                and file.is_documentation_page()
                and not file.is_media_file()
            ]
        )

        def process_file(file: File) -> None:
            pathFile: str | None = file.abs_src_path
            if pathFile is not None:
                with open(pathFile, encoding="utf-8-sig", errors="strict") as handle:
                    source, meta_data = meta.get_data(handle.read())
                    alias_names: Optional[List[str]] = _get_alias_names(meta_data)

                    if alias_names is None or len(alias_names) < 1:
                        _title: Optional[str] = get_page_title(source, meta_data)

                        if _title:
                            _title = _title.strip()
                            _title = re.sub(r'^[\'"`]|["\'`]$', "", _title)

                            if _title not in config["url_for"]:
                                url = urljoin(config["site_url"], file.url)
                                config["url_for"][_title] = [url]
                                config["aliases_for"][url] = [_title]

        with ThreadPoolExecutor() as executor:
            list(
                executor.map(
                    process_file, filter(lambda f: f.is_documentation_page(), files)
                )
            )
            executor.shutdown(wait=True)

        if self.LINKS_JSON.exists():
            self.LINKS_JSON.unlink()

        with open(self.LINKS_JSON, "w") as f:
            json.dump(
                {
                    "aliases_for": config.get("aliases_for", {}),
                    "url_for": {
                        k: [
                            p.replace(".md", ".html") if p.endswith(".md") else p
                            for p in v
                        ]
                        for k, v in config["url_for"].items()
                    },
                },
                f,
                indent=2,
            )

    def on_page_content(
        self, html, page: Page, config: MkDocsConfig, files: Files
    ) -> str:
        """
        Process the page content to add the wiki links to the page if the
        frontmatter has the `list_wikilinks` flag set to true.
        """
        if "current_page" not in config or "nodes" not in config:
            return html
        current_page = config["current_page"]
        url = current_page.canonical_url.replace(".html", ".md")
        if url not in config["nodes"]:
            return html

        if url not in config["nodes"] or "index" not in config["nodes"][url]:
            return html
        links_number: List[Dict[str, int]] = config.get("links_number", [])
        if len(links_number) > 0:
            actualindex = config["nodes"][url]["index"]
            result_entry = ResultEntry(
                file=current_page.url,
                index=actualindex,
                matches=links_number,
                url=current_page.canonical_url,
                name=current_page.title,
            )
            files_relation.append(result_entry)

            if page.meta.get("list_wikilinks", False):
                # Creat a bullet list of links
                wrapped_links = "<details class='quote'><summary>Relevant internal links on this page</summary><ul>"
                unique_links = {
                    link["url"]: (link["path"], link["name"]) for link in links_number
                }
                for url, (path, name) in unique_links.items():
                    wrapped_links += f"<li><a href='{url}' alt='{path}'>{name}</a></li>"
                wrapped_links += "</ul></details>"

                html = html.replace(TOKEN_LIST_WIKILINKS, wrapped_links)

        return html

    def on_post_build(self, config: MkDocsConfig):
        if self.GRAPH_JSON.exists():
            self.GRAPH_JSON.unlink()

        serialized_files_relation = [entry.to_dict() for entry in files_relation]
        with open(self.GRAPH_JSON, "w") as graph_json_file:
            json.dump(
                {"graph": serialized_files_relation},
                graph_json_file,
                indent=2,
            )


# -----------------------------------------------------------------------------


def _extract_aliases_from_nav(item, parent_key=None):
    result = []
    if isinstance(item, str):
        if parent_key:
            result.append((item, parent_key))
    elif isinstance(item, list):
        for i in item:
            result.extend(_extract_aliases_from_nav(i, parent_key))
    elif isinstance(item, dict):
        for k, v in item.items():
            if isinstance(v, str):
                result.append((v, k))
            else:
                result.extend(_extract_aliases_from_nav(v, k))
    return result


def _get_alias_names(meta_data: dict) -> Optional[List[str]]:
    """Returns the list of configured alias names."""
    if len(meta_data) <= 0 or "alias" not in meta_data:
        return None
    aliases = meta_data["alias"]
    if isinstance(aliases, list):
        return list(filter(lambda value: isinstance(value, str), aliases))
    if isinstance(aliases, dict) and "name" in aliases:
        return [aliases["name"]]
    if isinstance(aliases, str):
        return [aliases]
    return None
