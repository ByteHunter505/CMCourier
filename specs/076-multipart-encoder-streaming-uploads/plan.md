# 076 — Plan

## Cambio en `cmis_uploader.py`

### Imports

Agregar al top:

```python
from requests_toolbelt import MultipartEncoder
```

### `_post_with_retries`

Reemplazar el bloque `httpx.Client.post(...)` por encoder
streaming, reconstruyendo el encoder en cada attempt.

```python
# antes (línea 790-795)
resp = self._client.post(
    url,
    data=data_fields,
    files={"content": file_field},
    timeout=self._timeout_s,
)

# después
encoder = MultipartEncoder(fields={**data_fields, "content": file_field})
resp = self._client.post(
    url,
    content=encoder,
    headers={"Content-Type": encoder.content_type},
    timeout=self._timeout_s,
)
```

### Compatibilidad con `httpx`

`httpx.Client.post(content=X)` acepta varios tipos de X. Con
`MultipartEncoder`, httpx llama `.read(size)` sobre el encoder —
exactamente lo que el encoder soporta. Resultado: httpx lee chunks
del encoder, el encoder lee chunks del archivo, todo va al socket
streaming. Sin buffer intermedio.

httpx también puede iterar via `__iter__`; `MultipartEncoder` lo
tiene. Ambos paths funcionan.

### `pyproject.toml`

Agregar a `[project] dependencies`:

```toml
"requests-toolbelt>=1.0,<2.0",
```

Versión 1.0+ porque es la API estable de `MultipartEncoder` con
soporte de Python 3.11+. No traemos `requests` — `requests-toolbelt`
sí lo trae como dep transitivo (ya estaba antes igual, vía
spec 045 / pre-060). Aceptable.

## Tests

### Test 1 — encoder se usa con los fields correctos

```python
def test_post_uses_multipart_encoder_with_streaming_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured_kwargs: dict[str, Any] = {}

    def fake_post(self, url, **kwargs):
        captured_kwargs.update(kwargs)
        return _fake_201_response()

    monkeypatch.setattr("httpx.Client.post", fake_post)
    # ... build uploader, call upload() ...

    # El POST se hace con content= (no data=/files=)
    assert "content" in captured_kwargs
    assert "files" not in captured_kwargs
    assert "data" not in captured_kwargs

    # Content-Type viene del encoder
    headers = captured_kwargs.get("headers", {})
    assert headers["Content-Type"].startswith("multipart/form-data; boundary=")

    # El content es un MultipartEncoder
    from requests_toolbelt import MultipartEncoder
    assert isinstance(captured_kwargs["content"], MultipartEncoder)
```

### Test 2 — fields incluyen los campos CMIS esperados

```python
def test_encoder_contains_all_cmis_fields(...) -> None:
    # capturar encoder, verificar que fields tiene:
    # cmisaction, propertyId[0..N], propertyValue[0..N], content
```

### Test 3 — retry reconstruye el encoder

Verificar que en el retry path, el encoder se construye de nuevo
(no se reusa uno consumido).

### Adaptación de tests existentes

`tests/integration/adapters/test_cmis_uploader.py` usa `respx`
para mockear httpx. Como ahora el body llega como blob multipart
(no campos separados), los asserts que miraban
`request.url.params` o cosas similares siguen OK. Lo que cambia es
el `request.content` — antes era multipart auto-armado por httpx,
ahora es multipart armado por el encoder. **El blob multipart sigue
siendo válido HTTP** y respx no le va a hacer drama. Verificamos
después.

## Phased commits

1. `feat: add 076 spec, plan, tasks — MultipartEncoder streaming`
2. `fix(upload): use MultipartEncoder for true streaming uploads to CMIS (076)`
3. `test: cover MultipartEncoder body assembly (076)`
4. `docs(076): CHANGELOG 0.78.0 + version bump`

## Verificación

```bash
pytest -m unit                                                # smoke completo
pytest tests/unit/adapters/upload/                            # tests específicos del adapter
cmcourier --version                                           # 0.78.0
```

Y desde el cliente productivo (Windows):

```powershell
git pull
pip install -e . --no-deps
pip install requests-toolbelt                                 # nueva dep runtime
cmcourier rvabrep-pipeline run `
  --config sample\config-prod-as400.yaml `
  --batch-id 076-throughput-test `
  --total 50
```

**Métrica de éxito**: en el TUI tab UPLOAD, `peak_mbps` >>> 7,
`current_mbps` sostenido por encima de 10. Idealmente acercándose
a los 45 MB/s del legacy.
