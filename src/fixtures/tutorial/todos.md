# Todos Plugin

Enable the todos plugin in `mkdocs.yml`:

```yaml
plugins:
  - todos
```

## Usage

Create todos using:

```text
!!! todo

    Content of the todo
```

This renders as:

!!! todo

    Content of the todo

!!! info
    Todos are removed from online versions by default. Set `todos: True` in front-matter to keep them.