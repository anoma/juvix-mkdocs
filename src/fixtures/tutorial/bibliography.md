# Bibliography Support

Enable bibliography support in `mkdocs.yml`:

```yaml
plugins:
  - bibtex:
      bib_dir: "docs/references"
```

## Usage

1. Place `.bib` files in `docs/references`
2. New `.bib` files are automatically processed

## Citations

Cite references using:
```text
This statement requires a citation [@citation_key].
```