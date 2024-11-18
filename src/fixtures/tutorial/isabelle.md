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
  isabelle_at_bottom: true
---
```

## Including Generated Files

Include the generated Isabelle theory as a snippet using the `!thy` suffix:

```markdown
;--8<-- "docs/isabelle.juvix.md!thy:isabelle-add-def"
```


This provides the following output:

```isabelle title="isabelle.thy from isabelle.juvix.md"
--8<-- "docs/isabelle.juvix.md!thy:isabelle-add-def"
```