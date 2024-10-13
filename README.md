# Juvix MkDocs

This is a plugin for MkDocs to build static websites and highlight Juvix
codeblocks using [the Juvix Compiler](https://docs.juvix.org).

## Features

- Highlight Juvix code blocks in Markdown files
- Support for hidden Juvix code blocks
- Extract statements from Juvix code blocks

## Getting Started

### Prerequisites

- Python 3.9+
- [Poetry](https://python-poetry.org/docs/#installation)

### Installation

1. Initialize a Poetry project:

```shell
poetry init
```

2. Add the required dependencies:

```shell
poetry add mkdocs-juvix-plugin
```

3. Create a new MkDocs project:

```shell
mkdocs-juvix new
```

4. Run the development server:

```shell
poetry run mkdocs serve
```
