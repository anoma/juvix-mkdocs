# Juvix MkDocs

```yaml
# mkdocs.yaml
plugins:
  - juvix-mkdocs

markdow_extensions:
  pymdownx.superfences:
      custom_fences:
        - name: juvix
          class: juvix
          format: !!python/name:juvix-mkdocs.render.render
```
