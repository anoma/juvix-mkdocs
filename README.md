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
juvix-mkdocs new
```

This will create a new MkDocs project in the current directory where you execute
the command, say `my-project`. Then navigate into the project directory:

```shell
cd my-project
```

and run the development server:

```shell
poetry run mkdocs serve
```

4. Otherwise, just add the plugin to your existing MkDocs project:

```shell
# mkdocs.yml
plugins:
  - juvix
```

