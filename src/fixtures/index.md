# Support for Juvix in MkDocs

## Installation

This is a testing website for the `juvix-mkdocs` plugin, a MkDocs plugin that
can render Juvix code blocks in Markdown files, generating Isabelle theories
from Juvix Markdown files, all this with support for snippets and wiki links.

### Quick Start

To install it, run:

```bash
pip3 install mkdocs-juvix-plugin
```

If you already have a project, add the plugin and add the following to your
`mkdocs.yml` file:

```yaml title="mkdocs.yml"
plugins:
  - juvix
  # - todos
```

Front-matter options can be added to any file to customize the behavior of the
plugin. For example, to generate Isabelle theories from Juvix Markdown files,
add the following to the front-matter of the file:

```yaml
---
preprocess:
  juvix: true
  isabelle: true
  isabelle_at_bottom: true
---
```

For more information, here are some tutorials:

- [[Tutorial Juvix Markdown|Juvix Markdown file structure]]
- [[Tutorial Isabelle|Generate Isabelle theories for inclusion in the documentation]]
- [[Snippets|Snippet support for inclusion of content from external files]]
- [[Wiki Links|Support for Wiki Links]]
- [[Bibliography|Bibliography support]]
- [[Todos|To-do Plugin]]
- [[Tutorial Diagrams|Diagrams using Kroki]]
