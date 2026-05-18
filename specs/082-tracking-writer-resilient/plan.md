# 082 — Plan

Dos cambios mínimos en sqlite.py + 2 tests.

1. ``except sqlite3.Error:`` → ``except Exception:`` en el commit branch.
2. Outer ``try/except Exception`` envolviendo el while iteration.
3. Test ``test_unexpected_exception_in_drain_does_not_kill_writer``.
4. Test ``test_writer_still_alive_after_normal_operations``.

Bump a 0.84.0.
