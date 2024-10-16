# Welcome to Your Documentation Project with support for Juvix Code Blocks

This is a testing website for the `juvix-mkdocs` package, a MkDocs plugin for
Juvix that can render Juvix code blocks in Markdown files. To install it, run:

```bash
pip3 install mkdocs-juvix-plugin
```

This website is an example of a documentation website that is built using this
package.

We created this website by running `juvix-mkdocs new` with the `--anoma-setup`
flag, which creates a custom theme for the website. This is optional.

```bash
juvix-mkdocs new my-juvix-project --anoma-setup
```

Checkout all the options with:

```bash
juvix-mkdocs new --help
```

Or all the subcommands with:

```bash
juvix-mkdocs --help
```


So, we'll assume that you have already installed `juvix` and `mkdocs` on your
system. If you haven't installed them yet, please follow the installation
instructions on the official [Juvix](https://docs.juvix.org) and
[MkDocs](https://www.mkdocs.org) websites.

## What is a Juvix Markdown File?

A Juvix Markdown file is a special type of Markdown file with the extension
`.juvix.md`. These files are preprocessed by the Juvix compiler to generate the
final Markdown output, allowing you to seamlessly integrate Juvix code into your
documentation. Easy.

## Key Features of Juvix Markdown

For Juvix code blocks:

1. Start with a module declaration matching the file name.
2. Include well-defined expressions in each block.
3. Use `hide` attribute to exclude blocks from output.
4. Apply `extract-module-statements` to show specific code parts.


## Example: Module Declaration

Here's how you declare a module in a Juvix Markdown file named `index` (notice
this file is located in the `docs` folder, same folder where `Package.juvix` is located):

```juvix
module index;
-- Your Juvix code here
```

Refer to the test file
[`test.juvix.md`](./test.juvix.md) located in the `docs` folder to see another
example.

## Hide Juvix code blocks

Juvix code blocks come with a few extra features, such as the ability to hide
the code block from the final output. This is done by adding the `hide`
attribute to the code block.

## Extract inner module statements

Another feature is the ability to extract inner module statements from the code
block. This is done by adding the `extract-module-statements` attribute to the
code block. This option can be accompanied by a number to indicate the number of
statements to extract. For example, the following would only display the content
inside the module `B`, that is, the module `C`.


## Citing

This is a citation [@thebook].