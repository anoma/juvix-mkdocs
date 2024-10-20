# Welcome to Your Documentation Project with support for Juvix Code Blocks

## Installation

This is a testing website for the `juvix-mkdocs` package, a MkDocs plugin for
Juvix that can render Juvix code blocks in Markdown files. To install it, run:

```bash
pip3 install mkdocs-juvix-plugin
```

If you already have a project, add the plugin and add the following to your
`mkdocs.yml` file:

```yaml title="mkdocs.yml"
plugins:
  - juvix
```

## Creating a new project (optional but recommended)

This website is an example of a documentation website that is built using this
package, and the CLI command `juvix-mkdocs new` included in this package.

Running `juvix-mkdocs new` without any flags will create a new project with a
minimal setup, all the files needed to get started.

```bash
juvix-mkdocs new my-juvix-project
```

Checkout all the options with:

```bash
juvix-mkdocs new --help
```

Or all the subcommands with:

```bash
juvix-mkdocs --help
```

if you want to use the Anoma setup, you can run:

```bash
juvix-mkdocs new my-juvix-project --anoma-setup
```

So, we'll assume that you have already installed `juvix` and `mkdocs` on your
system. If you haven't installed them yet, please follow the installation
instructions on the official [Juvix](https://docs.juvix.org) and
[MkDocs](https://www.mkdocs.org) websites.

## Building and running the website

The `juvix-mkdocs` package includes a CLI that helps you build and run the
website, assuming that you have a project already created and that it was built
using poetry.

To build the website, run:

```bash
juvix-mkdocs build
```

To run the website, run:

```bash
juvix-mkdocs serve
```

These commands are wrappers of `poetry run mkdocs build` and `poetry run mkdocs serve`.

## Juvix Markdown file structure


A Juvix Markdown file is a file with extension `.juvix.md`. These files are
preprocesses by the Juvix compiler to generate the final Markdown file using
this plugin.

Very important to note is that the first Juvix code block in a Juvix Markdown
file must declare a module with the name of the file, and each block should be a
sequence of well-defined expressions. This means submodules cannot be split
across blocks. The name of module must follow the folder structure of the file
is in. For example, the file `tutorial/basics.juvix.md` must declare the module
`tutorial.basics`.

```juvix title="tutorial/basics.juvix.md"
module tutorial.basics;
-- ...
```

Refer to the [[test|test.juvix.md]] file located in the
`docs` folder to see an example.

## Include Juvix code within Code Blocks

```yaml title="mkdocs.yml"
plugins:
  - juvix
```


### Hide Juvix code blocks

Juvix code blocks come with a few extra features, such as the ability to hide
the code block from the final output. This is done by adding the `hide`
attribute to the code block. For example:

<pre><code>````juvix hide
module tutorial.basics;
-- ...
```</code></pre>

### Extract inner module statements

Another feature is the ability to extract inner module statements from the code
block. This is done by adding the `extract-module-statements` attribute to the
code block. This option can be accompanied by a number to indicate the number of
statements to extract. For example, the following would only display the content
inside the module `B`, that is, the module `C`.

<pre><code>````juvix extract-module-statements
module B;
module C;
-- ...
```</code></pre>


## Generate Isabelle theories for inclusion in the documentation

Check out the [[isabelle|Isabelle generated content from Juvix]] page for more
information.

```yaml
---
isabelle: true
---
```

Or

```yaml
---
isabelle:
- generate: true
- include_at_bottom: true
---
```

### Snippet for generated Isabelle files

For including generated Isabelle files, the path of the file must end with
`!thy`, the raw content of the Isabelle theory file will be included. Of course,
you need to configure the `snippet` markdown extension.

```markdown
;--8<-- "docs/isabelle.juvix.md!thy:isabelle-add-def"
```

This provides the following output:

```isabelle title="isabelle.thy from isabelle.juvix.md"
--8<-- "docs/isabelle.juvix.md!thy:isabelle-add-def"
```

## Snippets Plugin

```yaml title="mkdocs.yml"
markdown_extensions:
  - mkdocs_juvix.snippets:
      check_paths: true
```

!!! info

    If you already have `wikilinks` enabled, you don't need to enable `mkdocs_juvix.snippets`. It's loaded
    automatically.

### Excerpt Wrapping Syntax

Enclose the excerpt with the following tags:

```markdown
<!-- Start snippet -->
;--8<-- [start:TAG]
...
;--8<-- [end:TAG]
<!-- End snippet -->
```

### Snippet Inclusion Syntax

To incorporate the excerpt elsewhere, specify its path and tag:

```markdown
;--8<-- "path/to/file.ext:TAG"
```

### Snippets of Juvix code

You can also include **snippets of Juvix code** in your Markdown files. This is done
by adding the `--8<--` comment followed by the path to the file, and optionally
a snippet identifier.

!!! note

    If the path of the file ends with `!`, the raw content of the file
    will be included. Otherwise, for Juvix Markdown files, the content will be
    preprocessed by the Juvix compiler and then the generated HTML will be
    included.


!!! info "Snippet identifier"

    To use a snippet identifier, you must wrap the Juvix code block with the syntax
    `<!-- --8<-- [start:snippet_identifier] -->` and `<!-- --8<-- [end:snippet_identifier] -->`.
    This technique is useful for including specific sections of a file. Alternatively, you
    use the standard `--8<--` markers within the code and extract the snippet by appending a ! at the end of the path.

### Snippet for generated Isabelle files

For including generated Isabelle files, the path of the file must end with
`!thy`, the raw content of the Isabelle theory file will be included.

```markdown
;--8<-- "docs/isabelle.juvix.md!thy:isabelle-add-def"
```

This provides the following output:

```isabelle title="isabelle.thy from isabelle.juvix.md"
--8<-- "docs/isabelle.juvix.md!thy:isabelle-add-def"
```


## Todos Plugin

```yaml title="mkdocs.yml"
plugins:
  - todos
```

Incorporate todos with the following syntax:

```text
!!! todo

    Content of the todo
```

The above renders as:

!!! todo

    Content of the todo

!!! info

    Be aware that todos are automatically removed from the online version. If you want to keep them, set `todos: True` in the front matter.

## Diagrams using Kroki

```yaml title="mkdocs.yml"
plugins:
  - kroki:  # docs: https://github.com/AVATEAM-IT-SYSTEMHAUS/mkdocs-kroki-plugin#readme
      ServerURL: !ENV [KROKI_SERVER_URL, 'https://kroki.io'] #https://kroki.io/examples.html
      FileTypes:
        - png
        - svg
      FileTypeOverrides:
        mermaid: png
      FailFast: !ENV CI
```

Check out the [[diagrams|Diagrams using Kroki]] page for more some examples.


## Support for Wiki Links

```yaml title="mkdocs.yml"
plugins:
  - wikilinks
```

Wiki links offer a simple method for citing and referencing other pages in the
documentation without lengthy URLs. **Wiki links are the preferred method for
linking to other pages** in the documentation, so please use them whenever
possible.

### Basic Syntax

The basic syntax for a wiki link is:

```
[[page]]
```

Where:

- `page` is the title of the target page

### Full Syntax

The full syntax for a wiki link is:
```markdown title="Wiki Link Syntax"
  [[hintpath/to:page#anchor|Custom caption]]
```

When resolving a wiki link, the system follows these rules:

#### Page Title

(**Mandatory**) The 'page' in a wiki link refers to the title
specified in the `nav` attribute of the `mkdocs.yml` file. For example,

  ```yaml title="mkdocs.yml"
  nav:
    - Home: index.md
    - MyRef X: reference.md
  ```

provides the following wiki link:

```markdown
[[MyRef X]]
```


#### Path Hints

(**Optional**) You can use path hints to specify the location of the file. The syntax is:

```markdown title="Path Hints"
[[hintpath/to:page]]
```

Where:

- `hintpath/to` is the path (or prefix) to the file
- `page` is the title of the target page

#### Anchors

(**Optional**) Use anchors to link to specific sections within a page. If the
page does not have an anchor, the link would render as the caption provided,
and you'll find a warning in the build process.

```markdown title="Anchors"
[[page#anchor]]
```

Where:

- `page` is the title of the target page
- `anchor` is a specific section within the page


#### Custom captions

(**Optional**) Provide custom text to display for the link instead of the page title.

```markdown title="Custom Captions"
[[page#anchor|Custom caption]]
```

Where:

- `page` is the title of the target page
- `anchor` is a specific section within the page

Captions can include icons, for example:

=== "Markdown"

    ```markdown
    [[index | :material-link: this is a caption with an icon ]]
    ```

=== "Preview"

    [[index | :material-link: this is a caption with an icon ]]


### List of wiki-style links per Page

By default, the build process will generate a list of all wiki-style links per
page. This list is displayed at the bottom of the page, and it is useful for
identifying broken links or pages that are not linked to from other pages.

To disable this feature, set the `list_wikilinks` option to `false` in the front
matter of the page.

```yaml
list_wikilinks: false
```

## Bibliography support

```
# mkdocs.yml
plugins:
  - bibtex:
      bib_dir: "docs/references"
```

Place your `.bib` files within the `docs/references` directory.

Any new `.bib`
file added to this folder will automatically be processed.

### Citing in Markdown

Use the citation key from your `.bib` files to cite references in your markdown
files. The syntax is as follows:

```text
This statement requires a citation [@citation_key].
```
