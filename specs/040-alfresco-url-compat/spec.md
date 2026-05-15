# 040 — Compatibilidad de URL Alfresco (semánticas `repo_id=""`)

## Por qué

El CmisUploader (010) fue construido contra el endpoint Browser
Binding de IBM Content Manager, que espera que el id del repositorio
aparezca **dentro del path de la URL** entre la URL del servicio y
`/root/`:

```
http://ibm-cm:9080/.../cmis-browser/<repository_id>/root/<folder>
```

CMCourier emite exactamente esa forma:
`f"{base_url}/{repo_id}/root/..."`. El Browser Binding CMIS 1.1 de
Alfresco, por contraste, **no incluye el id del repositorio en el
path** cuando `base_url` ya termina en `.../browser`. El id del
repositorio se lee del JSON devuelto por `repositoryInfo`, nunca se
muestra en la URL:

```
http://alfresco:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser/root/<folder>
```

Hoy ninguna setting de config hace que el adaptador emita la forma
Alfresco. Definir `repo_id=""` NO funciona — el f-string emite una
barra duplicada (`.../browser//root/<folder>`) que Alfresco rechaza
con HTTP 405 "Unknown operation". Definir `repo_id="-default-"`
alcanza la URL `.../browser/-default-/root/<folder>` que Alfresco
también rechaza.

Por lo tanto, los operadores que corren el dry-run de staging
contra el contenedor Alfresco local enviado bajo `scripts/staging/`
no pueden ejercitar el `pipeline` contra él. El pre-flight
`cm-targets` del doctor FAILea en los checks de carpetas + tipos
incluso cuando los recursos subyacentes existen.

040 cierra esa brecha con un cambio aditivo mínimo: cuando
`repo_id` está vacío, el adaptador omite tanto la barra como el
segmento, emitiendo `.../browser/root/<folder>` directamente. El
comportamiento de IBM CM se preserva verbatim cuando `repo_id` está
definido (el default histórico).

## Qué

### Cambio en el adaptador

Agregar un único helper
`CmisUploader._service_url(suffix: str = "") -> str` que construye
URLs respetando `repo_id=""`:

```python
def _service_url(self, suffix: str = "") -> str:
    if self._cfg.repo_id:
        url = f"{self._cfg.base_url}/{self._cfg.repo_id}"
    else:
        url = self._cfg.base_url
    return f"{url}/{suffix}" if suffix else url
```

Reemplazar cada construcción de URL con f-string existente en
`CmisUploader` que hardcodee `f"{base}/{repo_id}"` o
`f"{base}/{repo_id}/root/..."` con una llamada a
`self._service_url(...)`. Los seis puntos de llamada son:

- `_warmup_session`: `self._service_url()`
- `get_type_definition`: `self._service_url()`
- `verify_folder_exists`: `self._service_url(f"root/{normalized}")`
- `upload`: `self._service_url(f"root/{normalized}")`
- `test_connection`: igual a `_warmup_session`
- (cualquier futuro helper `_check_*` agregado por 038): mismo
  patrón

Sin cambio de API pública. Sin cambio de puerto. `CmisConfig.repo_id`
ya acepta cualquier string, incluyendo `""`.

### Esquema de config

`CmisConfig.repo_id` queda formalmente documentado como "dejar vacío
para apuntar a una URL de servicio Browser-Binding que ya codifica
el id del repositorio (Alfresco). Definir al identificador del
repositorio de IBM CM (`$x!icmnlsdb_cmis` típicamente) para IBM
CM."

`scripts/staging/config-staging.yaml.template` se actualiza para
mostrar ambas formas con un bloque de comentarios explicando la
distinción Alfresco vs IBM CM.

### Comportamiento por defecto

- `repo_id` definido (cualquier string no vacío) → forma de URL
  idéntica al comportamiento pre-040. Los consumidores de IBM CM
  no ven cambio alguno.
- `repo_id=""` → las URLs pierden el segmento `/<repo_id>`
  completo. El adaptador sigue funcionando para warmup, definición
  de tipo, verificación de carpeta, y subida — todo contra la
  convención de URL de Alfresco.

## Fuera de alcance

- Cambiar las semánticas del método HTTP del adaptador (Alfresco
  acepta la misma forma `multipart createDocument`; solo cambian
  las URLs).
- Reescritura del adaptador para cualquier otra rareza CMIS
  (`cmisselector=object` funciona en Alfresco contra paths de
  carpeta, `=repositoryInfo` funciona en la URL del servicio, etc.).
- Auto-detección de "¿esto es Alfresco o IBM CM?" — fuera de
  alcance para siempre; la config del operador es la única fuente
  de verdad.

## Criterios de aceptación

- `_service_url()` existe, devuelve la forma correcta tanto para
  `repo_id=""` como para `repo_id="something"`.
- Los seis puntos de construcción de URL en `CmisUploader` usan el
  helper.
- Tests unitarios para `_service_url` (4 casos: vacío / definido /
  con sufijo / sin sufijo).
- Test de integración contra un endpoint estilo Alfresco falso
  (lib `responses`, `repo_id=""`) verifica que las URLs emitidas
  contengan `/browser/root/...` no `/browser//root/...`.
- Los tests de integración existentes con `repo_id` definido siguen
  pasando.
- `cmcourier doctor --check cm-targets` contra el Alfresco de
  staging en vivo en `testserver:8080` PASSes
  (`cm_type_alignment`, `cmis_folders_exist`,
  `cmis_properties_alignment`) con `repo_id: ""` en la config.
- `mypy` + `ruff` limpios.
- Entrada `[0.43.0]` del CHANGELOG.

## Notas

Esta es una corrección de compatibilidad pequeña y focalizada —
único helper, seis ediciones, ~1h en total incluyendo la spec. Vale
la pena ser una spec formal (040) en lugar de un commit `chore`
porque:

1. Cambia el contrato de `CmisConfig.repo_id` (vacío antes no
   tenía significado — ahora tiene semánticas explícitas).
2. El CHANGELOG necesita anunciar el nuevo soporte de Alfresco para
   que los operadores sepan que pueden pivotar la config de
   staging.
3. Los tests demandan que la convención quede fijada — sin
   cobertura, el próximo refactor del adaptador podría romper
   Alfresco silenciosamente.
