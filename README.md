# Juvix MkDocs

This is a plugin to be used with Mkdocs to build static websites and highlight
Juvix codeblocks using [the Juvix Compiler](https://docs.juvix.org).

To utilize this feature provided by the compiler, the file should have the
`.juvix.md` extension. Within this file, any Markdown is valid; the compiler
would only concern itself with *juvix code blocks*.

A Juvix code block in Markdown appears as follows:

<pre><code>
```juvix
module Test;
import Stdlib.Prelude open;

main : IO := printStringLn "Hello!";
```
</code></pre>

Juvix code blocks can be hidden from the final build if you use <pre>```juvix
hide```</pre> as the code block header.


A special addition, exclusive for MkDocs, is the *juvix-standalone files*. These
are modules which are compiled as standalone modules/programs. One key advantage
of these is that they can contain all the definitions which the module depends
on within a HTML *details* environment. To define such blocks, use the
`juvix-standalone` header.

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
```