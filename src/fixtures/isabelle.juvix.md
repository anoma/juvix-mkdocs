---
preprocess:
  isabelle: true
  isabelle_at_bottom: true
---

# Juvix can be used to generate Isabelle theories

For example, we can define the following Juvix module, assuming the file is
named `isabelle.juvix`:

<!-- --8<-- [start:isabelle-module] -->
```juvix
module isabelle;

type Nat : Type := zero | succ Nat;

-- --8<-- [start:isabelle-add-def]
add : Nat -> Nat -> Nat
  | zero n := n
  | (succ m) n := succ (add m n);
-- --8<-- [end:isabelle-add-def]
```
<!-- --8<-- [end:isabelle-module] -->

And then we can generate an Isabelle theory from it with the following command:

```bash
juvix isabelle isabelle.juvix
```

This will generate a file `isabelle.thy` in the current directory.

