# Snippet Support

To incorporate the excerpt elsewhere, specify its path and tag:

```markdown
;--8<-- "path/to/file.ext:TAG"
```

### Snippets of Juvix code

You can also include **snippets of Juvix code** in your Markdown files. This is
done by adding the `--8<--` comment followed by the path to the file, and
optionally a snippet identifier.

The following example shows how to include a snippet of Juvix code from the
file `test.juvix.md` with the identifier `main`.

```markdown
;--8<-- "docs/test.juvix.md:main"
```

which provides the following output:

--8<-- "docs/test.juvix.md:main"

You can also include relative paths:

--8<-- "./hello.juvix.md:axiom"


!!! info

    If the path of the file ends with `!`, the raw content of the file
    will be included. Otherwise, for Juvix Markdown files, the content will be
    preprocessed by the Juvix compiler and then the generated HTML will be
    included.

So if we would like to include the raw content of `test.juvix.md`, we can do
this by specifying the path as `docs/test.juvix.md!:main`.

--8<-- "docs/test.juvix.md!:main"

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
