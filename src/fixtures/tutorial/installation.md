# Installation and Setup

## Quick Installation

To install the `juvix-mkdocs` plugin, run:

```bash
pip3 install mkdocs-juvix-plugin
```

Add the plugin to your `mkdocs.yml`:

```yaml title="mkdocs.yml"
plugins:
  - juvix
  # - todos
```

## Front-matter Options

Customize plugin behavior using front-matter options:

```yaml
---
preprocess:
  juvix: true
  isabelle: true
  include_at_bottom: true
---
```

## Creating a New Project

Create a new project using the CLI command:

```bash
juvix-mkdocs new my-juvix-project
```

View all options with:

```bash
juvix-mkdocs new --help
```

For Anoma setup:

```bash
juvix-mkdocs new my-juvix-project --anoma-setup
```

## Building and Running

Build the website:
```bash
juvix-mkdocs build
```

Run the development server:
```bash
juvix-mkdocs serve
```

Some flags are available for these commands:

- `--remove-cache`: Remove the cache database.
- `--verbose`: Print verbose output.
- `--debug`: Print debug output.
- `--no-open`: Do not open the browser after building.
- `--quiet`: Do not print any output.


!!! info "Development Mode"


    For development, after `poetry install` and `poetry shell`:
    ```bash
    juvix-mkdocs new -n -f -D
    juvix-mkdocs serve -p my-juvix-project
    ```