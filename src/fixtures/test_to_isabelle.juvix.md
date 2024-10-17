---
isabelle: true
---

```juvix
module test_to_isabelle;

axiom A : Type;
axiom B : Type;
C : Type := A -> B;
axiom fun : C;

f : A -> B := fun;
```

