# Isabelle Theory Generation

## Configuration

Enable Isabelle theory generation in front-matter:

```yaml
---
preprocess:
  isabelle: true
---
```

To include theories at page bottom:

```yaml
---
preprocess:
  isabelle: true
  include_at_bottom: true
---
```

## Including Generated Files

Include Isabelle theory files using the `!thy` suffix:

```markdown
;--8<-- "docs/isabelle.juvix.md!thy:isabelle-add-def"
```


This provides the following output:

```isabelle title="isabelle.thy from isabelle.juvix.md"
--8<-- "docs/isabelle.juvix.md!thy:isabelle-add-def"
```

Enable in `mkdocs.yml`:
```yaml
plugins:
  - juvix
  - snippets
```

!!! info
    With `wikilinks` enabled, `snippets` is automatically included.