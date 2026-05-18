# 082 — Writer thread del SQLiteTrackingStore es resiliente

## Por qué

Bug productivo crítico descubierto durante pruebas: docs quedaban
en ``S4_DONE`` aunque el upload completaba exitosamente (eventos
``cmis_upload`` con status 2xx en los logs). Sin error visible.
Sin ``S5_DONE`` ni ``S5_FAILED`` en SQLite. El pipeline seguía
con el siguiente doc.

## Causa raíz

``SQLiteTrackingStore`` usa un **daemon thread** (``_writer_loop``)
que drena una queue de escrituras. Pre-082 el except del loop
era **solo** ``sqlite3.Error``:

```python
except sqlite3.Error:
    _log.exception("tracking writer: batch commit failed (size=%d)", len(batch))
```

Si **cualquier otra excepción** escapaba dentro del while
(``TypeError``, ``ValueError``, etc., desde un task malformed o
desde ``_drain_batch``), el thread moría silenciosamente. Daemon
threads no propagan excepciones al main — solo desaparecen.

Resultado: las escrituras siguientes a la queue se perdían sin
trace. Los uploads completaban del lado ``CmisUploader`` (vemos
``cmis_upload`` event), ``mark_stage_done`` encolaba el UPDATE,
pero **el writer ya estaba muerto** y nunca aplicaba.

## Fix

1. **Capturar ``Exception``** (no solo ``sqlite3.Error``) en el
   bloque interno del commit.
2. **Outer try/except** que envuelve toda la iteración del while
   — si algo escapa de ``_drain_batch`` o cualquier otro
   helper, el thread loguea y sigue.
3. **Test regression** que monkey-patchea ``_drain_batch`` para
   tirar ``RuntimeError`` (no sqlite3.Error) y verifica que el
   thread sigue ``is_alive()`` después.

## Criterios de aceptación

* Tras una exception arbitraria en el writer loop, el thread sigue
  vivo y procesa las siguientes escrituras OK.
* ``pytest -m unit`` pasa.
* 660+ tests existentes siguen pasando.
