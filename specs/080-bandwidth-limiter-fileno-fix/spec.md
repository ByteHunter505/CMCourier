# 080 — `BandwidthLimiter` necesita `fileno()` para no romper el encoder

## Por qué

**Bug productivo crítico** descubierto durante las pruebas de
throughput: con ``cmis.max_bandwidth_mbps > 0``, **100% de los
uploads fallaban** con:

```
TypeError: unsupported operand type(s) for +: 'int' and 'NoneType'
  File ".../requests_toolbelt/multipart/encoder.py", line 488
    self.len = len(self.headers) + total_len(self.body)
```

El error aparece DURANTE la construcción del ``MultipartEncoder``
(antes del POST), después de emitir ``cmis_upload_attempt`` —
exactamente lo que el operador reportó.

## La cadena del bug

1. ``cmcourier`` envuelve el file handle en ``BandwidthLimiter`` cuando
   ``cmis.max_bandwidth_mbps > 0`` (para throttling de upload).
2. El stream wrappeado se pasa como ``file_field`` del multipart al
   ``MultipartEncoder`` (introducido en 076).
3. ``MultipartEncoder.__init__`` calcula
   ``self.len = len(headers) + total_len(body)`` para reportar
   ``Content-Length``.
4. ``total_len(o)`` de ``requests_toolbelt`` prueba
   ``__len__`` → ``len`` (atributo) → ``fileno()`` → ``getvalue()`` y
   si ninguno funciona **devuelve ``None`` silenciosamente**.
5. ``BandwidthLimiter`` (definido en ``cmis_uploader.py``) expone
   ``read``, ``seek``, ``tell``, ``close``, ``name``, ``__enter__``,
   ``__exit__`` — **pero no ``fileno``**.
6. ``total_len()`` cae al ``return None`` implícito → ``int + None`` →
   ``TypeError``.

**Por qué no se notó antes de 076**: pre-076 el adapter usaba
``httpx.Client.post(files={...})`` que armaba el multipart
internamente con su propio path, sin pasar por ``MultipartEncoder``
ni por ``total_len``. El 076 hizo el switch al encoder para tener
streaming real, y ahí emergió este edge case.

**Por qué solo cuando ``max_bandwidth_mbps > 0``**: si el operador
no configura throttle, el stream pasa al encoder como file handle
nativo (``fh`` del ``open("rb")``), que sí tiene ``fileno()``. Ese
path funciona. Con throttle activado, ``BandwidthLimiter`` se
interpone y rompe la cadena.

## Qué

### Fix

Agregar el método ``fileno()`` al ``BandwidthLimiter`` que delegue al
stream subyacente. Cambio quirúrgico de 1 método.

```python
def fileno(self) -> int:
    return self._stream.fileno()
```

Con eso, ``total_len()`` lo invoca, obtiene el fd, hace
``os.fstat(fd).st_size - o.tell()``, devuelve el tamaño correcto, el
encoder calcula ``Content-Length`` bien y el upload procede.

### Tests

Tres tests nuevos en ``tests/unit/adapters/upload/test_bandwidth_limiter_fileno.py``:

1. ``BandwidthLimiter.fileno()`` delega al stream subyacente y
   devuelve el mismo descriptor.
2. ``MultipartEncoder`` calcula ``len`` correctamente cuando el file
   part es un ``BandwidthLimiter`` envolviendo un archivo real.
3. Regression test del bug: construir el encoder con un stream
   ``BandwidthLimiter`` previamente fallaba con TypeError; ahora
   sucede sin error.

## Criterios de aceptación

1. ``BandwidthLimiter.fileno()`` existe y delega.
2. ``MultipartEncoder(fields={"f": (name, BandwidthLimiter(fh, ...), mime)})``
   no tira ``TypeError`` y reporta ``encoder.len > 0``.
3. Test regression existe y pasa.
4. ``pytest -m unit`` pasa.
5. Pre-commit verde.

## Riesgos

* **Mínimo riesgo** — agregar un método que delega a una API estándar
  (``IO[bytes].fileno``) no rompe nada. Si el stream subyacente es un
  ``BytesIO`` o algo sin ``fileno``, propagamos su ``UnsupportedOperation``
  (lo cual ``total_len`` ya maneja con su ``except``).
* **Por qué no se cazó en tests pre-080**: los tests existentes del
  uploader usan ``respx`` para mockear httpx — no entran al path de
  ``MultipartEncoder.__init__`` con un ``BandwidthLimiter`` real. Spec
  080 cierra ese gap explícitamente.

## Notas operativas

Hasta deploy del fix, el operador puede **bypass-ear** el bug seteando
``cmis.max_bandwidth_mbps: 0.0`` en el YAML (sin throttle). Vuelve el
path donde el stream es el ``fh`` nativo.
