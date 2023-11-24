# Juvix MkDocs

This is a plugin to be used with Mkdocs to build static websites and highlight
Juvix codeblocks such as:

<pre><code>
```juvix
module Test;
import Stdlib.Prelude open;

main : IO := printStringLn "Hello!";
```
</code></pre>

which can be hidden if you use ```juvix hide``` as the code block header. 

Or to include everything as one standalone module.

<pre><code>
```juvix-standalone
module Test;
import Stdlib.Prelude open;

main : IO := printStringLn "Hello!";
```
</code></pre>

## Getting started

To create a new website using Mkdocs, check out this: [MkDocs Getting Started
Guide](https://www.mkdocs.org/getting-started/)

Install MkDocs and create a new project:

```shell
pip3 install mkdocs
mkdocs new my-project
```

Now to install this plugin to support juvix code blocks run the following
command:

```shell
pip3 install mkdocs-juvix-plugin
```

We recommend installing the [`material` theme for
`mkdocs`](https://squidfunk.github.io/mkdocs-material/), but this step is
optional.

```shell
pip3 install mkdocs-material
```

With all the prerequisites installed, we can update the `mkdocs.yml` file that
you get after initializing the project using `mkdocs new myproject`.

```yaml
# mkdocs.yaml
...
plugins:
  - juvix

markdown_extensions:
  pymdownx.superfences:
      custom_fences:
        - name: juvix
          class: juvix
          format: !!python/name:juvix-mkdocs.render.render
...
```