# Juvix MkDocs

This is a plugin for MkDocs to build static websites and highlight Juvix
codeblocks using [the Juvix Compiler](https://docs.juvix.org). It also adds a
CLI tool to help you get started with a new project called `juvix-mkdocs`.

## Features

- Highlight Juvix code blocks in Markdown files
- Support for hidden Juvix code blocks
- Extract statements from Juvix code blocks
- A CLI tool to get started with a new project

## Getting Started

### Prerequisites

- Python 3.9+
- [Poetry](https://python-poetry.org/docs/#installation)
- [Juvix Compiler](https://docs.juvix.org/)

### If you want to create a new MkDocs project

We ship the `juvix-mkdocs` CLI tool with a Python wheel, so you can install it
with pip, and later use it to create a new MkDocs project. For example:

```shell
pip3 install mkdocs-juvix-plugin
```

Then, create a new MkDocs project:

```shell
juvix-mkdocs new
```

By default, this command would interactively ask you a few questions. You can
skip the interaction by passing the `--no-interactive` flag. If you run this in
the interactive mode, it will create a new MkDocs project in the current
directory where you execute the command, say `my-project`. And then, it would
run the development server for you. All in all, you would end up with a project
that has the following structure:

```
my-project/
├── mkdocs.yml
├── poetry.lock
├── pyproject.toml
├── README.md
├── .gitignore
├── .github/
│   ├── workflows/
│   │   ├── ci.yml
├── docs/
│   ├── index.md
│   └── ...
```

You can run the development server at any time by running:

```shell
poetry run mkdocs serve
```

Or with `juvix-mkdocs` (which is a wrapper around `poetry run mkdocs serve`):

```shell
juvix-mkdocs serve
```

And build the project:

```shell
juvix-mkdocs build
```

## If you already have a MkDocs project

If you already have a MkDocs project, add the plugin to your existing project,
check out the fixtures in the `mkdocs.yml` file for reference, and the folder
(`src/fixtures`) for examples.

```yaml
# mkdocs.yml
plugins:
  - juvix
```