# Juvix Markdown Structure

The Juvix Markdown processor can turn Juvix code blocks into HTML.
The syntax highlighted is semantic, not lexical. This brings a more clear
understanding of the code. However, at the moment, processing Juvix
Markdown takes two seconds per file, on average. Therefore it is disabled by
default.

To enable it, set the `PROCESS_JUVIX` environment variable to `true`.
So, next time you run `mkdocs build`, Juvix Markdown will be processed. For
example, you can run the command in the following way:

```bash
PROCESS_JUVIX=true poetry run mkdocs serve
```


## File Structure

A Juvix Markdown file (`.juvix.md`) must follow these rules:

- The first Juvix code block must declare a module matching the file name
- Code blocks must contain well-defined Juvix expressions
- Module names must follow folder structure

Example:
```juvix title="tutorial/basics.juvix.md"
module tutorial.basics;
-- ...
```

## Code Block Features

Enable Juvix code blocks in `mkdocs.yml`:
```yaml
plugins:
  - juvix
```

### Hiding Code Blocks

Hide code blocks using the `hide` attribute:

<pre><code>````juvix hide
module tutorial.basics;
-- ...
```</code></pre>

### Extracting Module Statements

Extract inner module statements:

<pre><code>````juvix extract-module-statements
module B;
module C;
-- ...
```</code></pre>

With a specific number of statements:

<pre><code>````juvix extract-module-statements 2
module B;
axiom a : Nat;
module C;
-- ...
```</code></pre>

## Disabling Processing

Disable Juvix processing per file:
```yaml
---
preprocess:
  juvix: false
---
```