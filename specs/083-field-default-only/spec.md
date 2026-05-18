# 083 — `field_sources` con solo `default_value` (sin sources)

## Por qué

Descubierto en producción configurando metadata para `MetadatosCM.csv`.
Algunas propiedades CMIS son **constantes hardcodeadas por
operador** — banco emisor (`BAC`), tipo de canal (`MIGRATION`),
versión del Modelo Documental (`v2.1`). El operador no quiere
resolverlas desde ningún source — quiere ponerlas como literal en
el YAML.

Pre-083, `FieldConfig.sources` exigía `min_length=1`:

```python
sources: list[FieldSourceItem] = Field(min_length=1)
```

El operador se veía forzado a inventar un source dummy que falla
garantizado (`source_type: trigger`, `lookup_value_column:
__inexistente__`) solo para que el motor cayera al `default_value`.
Feo, confuso, y le mentía al lector sobre las fuentes reales.

El **motor** (`MetadataService._resolve_one`) ya soportaba el caso —
el `for sc in fsc.sources` no itera con sources vacíos y cae al
check del default. El **schema** era el único bloqueador.

## Qué

### Cambios

1. **`FieldConfig.sources`**: `Field(min_length=1)` → `Field(default_factory=list)`.
   Ahora puede omitirse o ser `[]`.
2. **Nuevo `@model_validator`**: exige que al menos UNO de
   `sources` (non-empty) o `default_value` (no `None`) esté presente.
   Un field completamente vacío sigue siendo error — el motor no
   tendría cómo resolverlo.

### Uso

```yaml
metadata:
  field_sources:
    # Constante hardcodeada — sin sources.
    BAC_BANCO:
      default_value: "BAC"

    # Mismo, forma explícita.
    BAC_CANAL:
      sources: []
      default_value: "MIGRATION"

    # Forma legacy con sources + default — sigue funcionando.
    BAC_CIF:
      sources:
        - source_type: rvabrep
          lookup_value_column: index2
      default_value: "000000"
```

### Tests

* `tests/unit/config/test_field_config_default_only.py` (4 acepta + 2 rechaza).
* `tests/unit/services/test_metadata_default_only.py` (4 motor + 1 validación de default).

## Criterios de aceptación

1. `FieldConfig(default_value="X")` (sin `sources`) → válido.
2. `FieldConfig(sources=[], default_value="X")` → válido.
3. `FieldConfig()` → `ValidationError` con "at least one".
4. `MetadataService.resolve()` devuelve `"X"` para un field con
   `sources=()` y `default_value="X"`.
5. `pytest -m unit` pasa.

## Riesgos

* **Backward-compat: cero**. Configs pre-083 con `sources: [...]` no
  vacío siguen validando idénticamente. El cambio es **strictly more
  permissive**.
* El validador de fields totalmente vacíos previene la regresión
  "field huérfano que el motor no puede resolver".

## Notas

Pareja con spec 084 (AS400 metadata source). 083 cubre constantes
literales; 084 cubre lookup dinámico contra AS400. Las dos juntas
le dan al operador todo el espectro de resolución de metadata sin
hacks.
