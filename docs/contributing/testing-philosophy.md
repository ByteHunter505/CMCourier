# Filosofía de testing

> [← Volver al índice](../INDEX.md) · [Contributing](README.md)

CMCourier corre TDD estricto. No es estética — es porque el original `RVIMigration` era impossible-to-test y eso lo mató. La testabilidad acá es un proxy de la salud arquitectónica.

---

## Tres capas de tests

```
tests/
├── unit/         ← rápido, mockea ports, < 1 s cada uno
├── integration/  ← real adapters (SQLite, CSV, files), 1–10 s
└── e2e/          ← live Alfresco/AS400 (limitado, opt-in)
```

| Capa | Marker | Qué mockea | Qué NO mockea | Cuándo |
|------|--------|-----------|---------------|--------|
| Unit | `@pytest.mark.unit` | Ports (interfaces) | Lógica de negocio | Cada función pura, cada service |
| Integration | `@pytest.mark.integration` | Nada relevante | SQLite real, CSV real, Alfresco en Docker | Adapters, CLI, TUI |
| E2E | (a definir) | Nada | Stack completo | Sanity de release |

---

## La regla de oro: AS400 NUNCA se mockea

Constitution Principio VI. El driver ODBC de iSeries Access no es portable, no se ejecuta en Linux dev, no es thread-safe en algunas versiones. **Mockearlo en tests es mentirte.**

Para cubrir el caso AS400 sin un AS400, usá `CSVDataSource` (`adapters/sources/tabular.py`). Es el mismo port `IDataSource`, distinto adapter, datos en CSV deterministicos. Si tu test pasa con CSV pero falla con AS400, el problema está en el adapter AS400 — no en tu lógica.

```python
# Mal
@patch("cmcourier.adapters.sources.as400.pyodbc.connect")
def test_indexing_with_as400(mock_connect):
    ...

# Bien
def test_indexing_logic(tmp_path):
    csv_path = tmp_path / "rvabrep.csv"
    csv_path.write_text("...")
    source = CsvDataSource(csv_path)  # implementa IDataSource
    service = IndexingService(source=source)
    ...
```

---

## Mockear ports, no adapters

```python
# Bien — mockeás la interfaz
from cmcourier.domain.ports import IUploader

class FakeUploader(IUploader):
    def upload_one(self, doc, metadata, source_root, batch_id):
        return f"fake-cm-id-{doc.txn_num}"
    def close(self):
        pass

def test_streaming_with_fake_upload():
    orchestrator = StreamingOrchestrator(uploader=FakeUploader(), ...)
    ...
```

```python
# Mal — mockeás el adapter concreto
@patch("cmcourier.adapters.upload.cmis_uploader.httpx.Client")
def test_streaming(mock_client):
    ...
```

Cuando mockeás el adapter concreto, atás el test al **cómo** del adapter. Cualquier refactor del adapter rompe tu test sin que la lógica de negocio cambie. Mockear el port te ata solo al contrato, que es lo que querés testear.

---

## Strict TDD: Red → Green → Refactor

1. **Red**: escribís el test, corrés, falla con la excepción esperada (no por syntax error). El fail demuestra que el test sabe distinguir el estado correcto del incorrecto.
2. **Green**: el mínimo código posible para que pase. Hardcodear el retorno es válido en este paso.
3. **Refactor**: limpiar el código y/o el test sin romper la verde. Los tests son tu red de seguridad acá.

Repetí. No hay "voy a escribir el test después" — el test va primero o el código no se merge-a.

---

## Pyramid de tests

| % aprox | Capa |
|---------|------|
| 70% | unit |
| 25% | integration |
| 5% | e2e |

Si tu pyramid está invertida (más integration que unit), la culpa es del diseño — algo es difícil de testear unitariamente porque está demasiado acoplado.

---

## Coverage gate

`pyproject.toml`:

```toml
[tool.coverage.report]
fail_under = 80
```

Coverage < 80% **rompe el build**. No es un objetivo, es un piso. La meta debería ser cerca de 90% en `services/` y `domain/` (puro lógica) y dejar adapters un poco más abajo si dependen de I/O.

---

## Cómo correr

```bash
pytest                              # todo
pytest -m unit                      # solo unit
pytest -m integration               # solo integration
pytest -m "not slow"                # excluye los lentos
pytest tests/unit/services/         # un subdirectorio
pytest -k "streaming"               # tests cuyo nombre matchea
pytest --cov src/cmcourier --cov-report=html  # coverage HTML
pytest -v --tb=short                # verbose con traceback corto
```

---

## Fixtures clave

Mirá `tests/conftest.py` y los `conftest.py` de cada subdirectorio:

- Fixtures de paths (`tmp_path` standard de pytest).
- Fixtures de config Pydantic builders (factories que dan configs válidas con overrides).
- Generadores de CSVs (RVABREP, Modelo Documental, MetadatosCM).
- Fixture de SQLite tracking en memoria (`:memory:`) para tests rápidos.

No reinventes — preguntá o leé `conftest.py` antes de armar tu propio scaffold.

---

## El error más común: tests acoplados al implementation

```python
# Mal — testea que se llamó .upload_one con kwargs específicos
def test_orchestrator_calls_upload():
    mock_uploader = MagicMock()
    orchestrator = StreamingOrchestrator(uploader=mock_uploader, ...)
    orchestrator.run()
    mock_uploader.upload_one.assert_called_once_with(doc=ANY, metadata=ANY, ...)

# Bien — testea el outcome observable
def test_orchestrator_uploads_all_docs():
    captured = []
    class CaptureUploader(IUploader):
        def upload_one(self, doc, *a, **kw): captured.append(doc.txn_num); return f"cm-{doc.txn_num}"
        def close(self): pass
    orchestrator = StreamingOrchestrator(uploader=CaptureUploader(), ...)
    orchestrator.run()
    assert captured == ["doc-1", "doc-2", "doc-3"]
```

El primer test rompe si renombrás un kwarg. El segundo rompe solo si el comportamiento observable cambia.

---

## Tests para bugs específicos

Cuando fix-eás un bug, escribís el test **antes** del fix:

1. Reproducir el bug → test rojo.
2. Aplicar fix → test verde.
3. El test queda en la suite como guardrail.

Convención: nombrá el test con referencia al spec/issue. `test_lane_controller_property_returns_pipeline_controller` (spec 070).

---

## Ver también

- [code-style.md](code-style.md) — convenciones de código
- [spec-driven-flow.md](spec-driven-flow.md) — TDD dentro del workflow SDD
- [how-to/developer/run-the-test-suite.md](../how-to/developer/run-the-test-suite.md)
- [Constitution Principio VI](../../.specify/memory/constitution.md)
