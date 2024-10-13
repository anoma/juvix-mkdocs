# Welcome to Your Juvix Documentation Project

This is the landing page for your Juvix documentation project. Here you'll find
an overview of your project and how to use Juvix with Markdown files.

## Getting Started

Before you begin, make sure you have the latest version of
[Juvix](https://docs.juvix.org) installed on your system. If you haven't
installed it yet, please follow the installation instructions on the official
Juvix website.

## What is a Juvix Markdown File?

A Juvix Markdown file is a special type of Markdown file with the extension
`.juvix.md`. These files are preprocessed by the Juvix compiler to generate the
final Markdown output, allowing you to seamlessly integrate Juvix code into your
documentation. To render this file, you need to build the website using
`mkdocs-juvix-plugin`, a Python package that integrates Juvix with MkDocs.

## Key Features of Juvix Markdown

For Juvix code blocks:

1. Start with a module declaration matching the file name.
2. Include well-defined expressions in each block.
3. Use `hide` attribute to exclude blocks from output.
4. Apply `extract-module-statements` to show specific code parts.


## Example: Module Declaration

Here's how you declare a module in a Juvix Markdown file:

```juvix
module index;
-- Your Juvix code here
```

Refer to the test file
[`test.juvix.md`](test.md) located in the `docs` folder to see another
example.

## Hide Juvix code blocks

Juvix code blocks come with a few extra features, such as the ability to hide
the code block from the final output. This is done by adding the `hide`
attribute to the code block. For example:



## Extract inner module statements

Another feature is the ability to extract inner module statements from the code
block. This is done by adding the `extract-module-statements` attribute to the
code block. This option can be accompanied by a number to indicate the number of
statements to extract. For example, the following would only display the content
inside the module `B`, that is, the module `C`.

