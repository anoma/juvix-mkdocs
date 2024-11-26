# Diagrams using Kroki

Enable Kroki support in `mkdocs.yml`:

```yaml
plugins:
  - kroki:
      ServerURL: !ENV [KROKI_SERVER_URL, 'https://kroki.io']
      FileTypes:
        - png
        - svg
      FileTypeOverrides:
        mermaid: png
```

See the [[diagrams|Diagrams using Kroki]] page for examples.