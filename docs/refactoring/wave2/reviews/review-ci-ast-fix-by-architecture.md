# Independent review: frozen AST serialization compatibility

Decision: **APPROVED; no blocking findings.** Reviewed exact verification commit `d593ae82e0c93ecccae3e110fb1a387ad5f0220d` in the restored scoring worktree.

The three-file delta changes only shared inventory serialization, the before-source freezer callers, and the corresponding ownership assertion. Git comparison confirms no production package or immutable fixture change. All three freezer AST serialization sites and the ownership assertion use the same helper, so capture and replay retain one explicit Python 3.12 evidence format.

On Python 3.13 the helper requests `show_empty=True`; feature detection preserves Python 3.12 invocation behavior. On Python 3.11 it deep-copies the tree and appends empty `type_params` fields only to function, async-function and class node instances. It does not alter application ASTs, input AST instances, or global AST class schemas. This reconstructs the empty fields present in the original Python 3.12 evidence without changing the observed computation.

Independent bounded execution used actual isolated `-I -S` interpreters: **3.11.15, 3.12.14 and 3.13.5**. A separate stdlib review script parsed each canonical owner, checked all **84 frozen full-definition hashes** on each interpreter, and asserted the complete input AST dumps/instance field schemas and global class schemas remained unchanged. All three runs passed. A changed return literal produced a different canonical dump, confirming the helper retains semantic fields. The four typed delegates remain outside the full original-body hash comparison under the existing explicit delegation contract.

No broad suite, fixture regeneration, source runtime import or policy change was performed for this review. The owner's seven focused contract tests and Ruff result remain separate evidence.
