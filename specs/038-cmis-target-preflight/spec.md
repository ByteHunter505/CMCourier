# 038 — Pre-flight de target CMIS + trazado del payload de subida

## Por qué

Hoy CMCourier descubre problemas con el target CMIS **a mitad de
corrida**: una carpeta faltante, un typo en un nombre de propiedad,
un CMISType que el operador olvidó completar — todo eso aparece
como errores 4xx en el intento N de S5 de miles. El operador se
entera horas adentro del `batch`, la DB de tracking se llena con
`S5_FAILED`, y la postmortem es un grep entre respuestas HTTP sin
contexto sobre qué fue enviado.

Dos modos de falla impulsaron este cambio:

1. **La jerarquía de carpetas la gobierna el banco, no CMCourier.**
   El actual `CmisUploader.ensure_folder` crea carpetas a demanda
   (itera los segmentos del path y hace POST con
   `cmisaction=createFolder` por cada segmento faltante). Esto fue
   heredado del uploader legado y es incorrecto para nuestro modelo
   operativo: en producción el árbol de carpetas pertenece a los
   administradores CMIS del banco; nosotros solo depositamos
   documentos. Una llamada `ensure_folder` que tiene éxito de manera
   silenciosa puede enmascarar un bug de configuración (typo en un
   CSV) creando una carpeta en el lugar equivocado. Necesitamos
   semánticas de verificación únicamente.

2. **El alineamiento de tipos de pre-flight existe pero es
   incompleto.** El chequeo existente `cm_type_alignment` (013)
   solo valida que el CMISType resuelva en el servidor CM. No
   verifica que los **destinos de carpeta** existan, ni que los
   **IDs de propiedad CMIS por campo** (ahora configurables vía
   `MetadatosCM`) estén declarados en esos tipos. El operador puede
   pasar `doctor` con salida en verde y aun así pegarse contra
   100% de tasa de falla en S5 porque la carpeta destino no
   existe.

3. **Sin visibilidad a nivel de cable en el camino de falla.**
   Cuando S5 hace POST de un `multipart` y el servidor responde
   400, el log de error existente registra el código HTTP y un
   cuerpo truncado. No registra el bag de propiedades que enviamos
   — así que el operador no puede saber si el problema es un valor
   malo, un ID de propiedad malo, un ID de tipo malo, o un problema
   de orden. La disciplina de PII (Principio VIII) más
   `metrics.jsonl` estructurado nos dan las herramientas para
   arreglar esto sin filtrar datos de clientes a los logs.

Este cambio cierra los tres huecos bajo un único paraguas de
pre-flight cm-targets y agrega un evento de payload de subida a
`metrics.jsonl` para que las postmortems sean deterministas.

## Qué

### 1. Nueva columna `MapeoRVI_CM.CMISFolder`

`MappingConfig` (`config/schema.py`):

```python
rvi_cm_cmis_folder_column: str = "CMISFolder"
```

`CMMapping` (`domain/models.py`) gana:

```python
cmis_folder: str | None  # None when the CSV cell is empty / column missing
```

`MappingService` puebla `cmis_folder` desde la columna configurada.
Cuando la columna está ausente (compat hacia atrás del modo
consolidado `ClaseDocumentalCM.csv`), el campo siempre es `None`.

El S5 del `pipeline` usa `cmis_folder` para construir la URL de
subida:
- `cmis_folder` definido → POST a `{base}/{repo}/root/{cmis_folder}`
- `cmis_folder` en `None` → POST a `{base}/{repo}/root`
  (comportamiento de raíz plana existente, usado por el modo de
  mapeo consolidado y por los tests).

### 2. Nueva columna `MetadatosCM.CMISPropertyId`

`MappingConfig`:

```python
metadatos_cmis_property_id_column: str = "CMISPropertyId"
```

`MetadataService.resolve_properties()` devuelve el ID de propiedad
CMIS por campo en lugar del nombre amigable cuando la columna está
poblada:

```
friendly Metadato           "CIF"
CMISPropertyId (if set)     "clbNonGroup.BAC_CIF"      ← wire
                            (or "cmcourier:BAC_CIF" in staging)
```

Cuando `CMISPropertyId` está vacío para un campo, el servicio cae
al nombre amigable tal cual (preserva el comportamiento actual).
Cuando la columna está ausente del archivo, todos los campos caen
al fallback. Es totalmente aditivo — las configuraciones existentes
no necesitan actualizarse.

### 3. `IUploader.ensure_folder` → `IUploader.verify_folder_exists`

Renombrado de puerto (`domain/ports.py`):

```python
def verify_folder_exists(self, folder_path: str) -> bool: ...
```

Devuelve `True` si la carpeta existe en el repositorio CMIS y es un
tipo base `cmis:folder`. Devuelve `False` en 404 o en una respuesta
200 cuyo `cmis:baseTypeId` no sea `cmis:folder`. Lanza excepción
solo en fallas de conectividad / `auth`.

Implementación (`adapters/upload/cmis_uploader.py`):
- Usa `GET ?cmisselector=object&objectId=workspace://SpacesStore/<folder>`
  o el equivalente basado en path que exponga la API REST de CM.
  Sin POST.
- El helper privado `_create_folder_segment` se elimina.

Pipeline (`orchestrators/staged.py`, S5):
- La llamada actual `uploader.ensure_folder(...)` dentro de S5 se
  **elimina**. El constructor de URL de S5 simplemente consume
  `cmis_folder` del `CMMapping` si está definido.
- La verificación se delega por completo a los checks del doctor
  definidos en §4. Si el operador se saltea el doctor y la carpeta
  falta, el primer intento de S5 falla con un 4xx cuyo trazado de
  payload (evento de §5) hace obvio el diagnóstico.

### 4. Dos nuevos checks del doctor + grupo `cm-targets`

`cli/doctor.py`:

```python
_CHECK_GROUPS["cm-targets"] = frozenset({
    "cm_type_alignment",        # existing — kept
    "cmis_folders_exist",       # new
    "cmis_properties_alignment", # new
})
```

El grupo `cm-types` existente se mantiene (aliaseado al único check
`cm_type_alignment`) por compat hacia atrás con cualquier script
del operador; `cm-targets` es el nuevo paraguas.

#### `_check_cmis_folders_exist`

- Itera los valores únicos no vacíos de `cmis_folder` a lo largo
  de las filas del mapeo.
- Llama a `IUploader.verify_folder_exists` por cada uno.
- PASS cuando todos devuelven `True`.
- FAIL listando los paths faltantes con la instrucción
  "crear estas carpetas en CMIS antes de correr el pipeline".
- SKIP cuando ninguna fila tiene `cmis_folder` poblado (manejo
  amable para el modo de mapeo consolidado donde las carpetas
  todavía no se declaran).

#### `_check_cmis_properties_alignment`

Para cada par único `(cm_object_type, cmis_property_id)` derivado
al unir `MapeoRVI` y `MetadatosCM` por `IDCM`:
- Llama a `IUploader.get_type_definition(cm_object_type)`.
- Verifica que `cmis_property_id` esté presente en
  `propertyDefinitions` de ese tipo.
- FAIL agrupa los pares faltantes por tipo:
  `BAC_01_01_02_04_01_15 missing 2: clbNonGroup.Fvenc_Inicio, clbNonGroup.Fvenc_Fin`.
- SKIP cuando ninguna fila tiene `cmis_property_id` poblado.

Ambos checks honran `cmis.test_connection_timeout_seconds` de la
config existente (sin perillas nuevas).

### 5. Eventos de trazado del payload de subida

`adapters/upload/cmis_uploader.py` emite dos eventos estructurados a
través del canal existente de `observability` hacia `metrics.jsonl`.

#### `s5_upload_attempt` — cada intento de POST

```jsonc
{
  "event": "s5_upload_attempt",
  "ts": "2026-05-13T03:42:11.812Z",
  "batch_id": "B-20260513-0001",
  "txn_num": "FB01.0001234",
  "attempt": 1,
  "url": "http://.../root/$type/BAC_01_01_02_04_01_15",
  "object_type_id": "$t!-2_BAC_01_01_02_04_01_15v-1",
  "properties": {
    "cmis:name": "0AAAUPUP.pdf",
    "cmis:contentStreamMimeType": "application/pdf",
    "clbNonGroup.BAC_CIF":         "00****56",
    "clbNonGroup.Nombre_Cliente":  "J***** P**********",
    "clbNonGroup.NUM_CUENTA":      "4111-****-****-1234"
  },
  "content_bytes": 2456712,
  "mime_type": "application/pdf"
}
```

#### `s5_upload_failed` — solo en respuestas no-201

Superconjunto de `s5_upload_attempt` con tres campos extra:

```jsonc
{
  "event": "s5_upload_failed",
  ...all of s5_upload_attempt...,
  "status_code": 400,
  "response_body": "{\"exception\":\"constraint\",\"message\":\"Property cm:foo unknown\"}",
  "curl_equivalent": "curl -u admin:*** -F 'cmisaction=createDocument' -F 'propertyId[0]=cmis:objectTypeId' ... '-F content=@<path>' 'http://.../'"
}
```

#### Enmascarado de PII

`observability/pii.py` ya existe. Ambos eventos enrutan cada valor
de propiedad a través de `pii.mask_value(field_name, value)` antes
de emitir. El mapa nombre-amigable → regla-de-enmascarado vive en
`observability/pii.py` (existente); los campos que no están en el
mapa se emiten verbatim.

#### Configuración

`ObservabilityConfig` (`config/schema.py`) gana:

```python
unmask_pii: bool = Field(default=False)
```

Cuando es `true`, ambos eventos emiten valores sin enmascarar. Se
expone únicamente vía archivo de config (sin flag CLI) para evitar
habilitaciones accidentales en `batches` PRD. Se emite un WARNING
del doctor al arranque cuando se detecta `unmask_pii=true`,
recordándoselo al operador.

## Fuera de alcance

- **Aprovisionamiento automático de carpetas CMIS.** No-objetivo
  explícito — el equipo del banco es dueño del árbol de carpetas.
- **Generar `MetadatosCM.CMISPropertyId` desde reflexión de
  `typeDefinition` CMIS.** El operador completa la columna a mano
  con el ID de propiedad a nivel de cable por entorno
  (`cmcourier:*` en staging, `clbNonGroup.*` en PRD). Una spec
  futura podría automatizar esto.
- **Volcado de equivalente curl en el camino de éxito.** Solo el
  camino de falla lo emite; los eventos de éxito ya tienen
  suficiente contexto.
- **Cambios a las reglas de enmascarado de `observability/pii.py`.**
  Se reutilizan tal cual.
- **Backport de las semánticas de `verify_folder_exists` a tests de
  integración de staging existentes que dependían de la auto-
  creación.** Esos tests se reescriben para pre-crear la carpeta
  vía el contenedor Alfresco de staging directamente (o vía el
  sample CMM upload que ya tenemos).

## Criterios de aceptación

- Los 9 checks de doctor existentes siguen en PASS contra un
  Alfresco de staging saludable.
- `doctor --check cm-targets` tras `register-model.sh` más
  pre-crear `/cmcourier-staging/CN01` reporta **3 PASS**
  (`cm_type_alignment`, `cmis_folders_exist`,
  `cmis_properties_alignment`).
- Borrar la carpeta hace que `cmis_folders_exist` FAIL y el
  `doctor` del `pipeline` salga con código no-cero.
- Definir un `CMISPropertyId` en `CN01.CIF` que no existe en
  `D:cmcourier:bacDoc` hace que `cmis_properties_alignment` FAIL
  con la propiedad faltante listada.
- Correr `cmcourier csv-trigger-pipeline run --total 10` sobre el
  stack de staging escribe 10 eventos `s5_upload_attempt` en
  `logs/<batch_id>/metrics.jsonl`.
- Inyectar un nombre de propiedad malo en `MetadatosCM` y re-
  correr produce al menos un evento `s5_upload_failed` con status
  `400`, un `response_body` truncado, y un `curl_equivalent` cuyos
  valores de propiedad están enmascarados por PII.
- Definir `observability.unmask_pii: true` y re-correr produce los
  mismos eventos con valores crudos, y el arranque del `doctor`
  emite un WARNING sobre el modo `unmask_pii`.
- `CmisUploader._create_folder_segment` se elimina y ningún test
  lo referencia. El S5 del `pipeline` hace cero requests de
  creación de carpeta en una corrida completa.
- Los tests existentes pasan sin modificación excepto los que
  dependen explícitamente de la auto-creación de carpetas (esos se
  reescriben para pre-crear).
- `mypy --strict` limpio en `domain/`, `services/`, `orchestrators/`.
- Ruff limpio.
- Entrada de CHANGELOG `[0.41.0]`, roadmap POST-MVP sin cambios
  (esto no es un ítem POST-MVP — es un cambio de
  endurecimiento / operabilidad).
