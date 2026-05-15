"""Filter de `mask` de `PII` (Principio VIII de la Constitución).

Basado en `denylist`: los campos cuyos nombres coinciden con un patrón de
`PII` conocido se redactan a :data:`MASK` antes de que cualquier handler
los formatee. El contrato para los callers es: pasar `PII` vía
``extra={"cif": "..."}`` — el filter lo atrapa. El `PII` embebido en el
string del mensaje mismo es bug del caller; no hacemos regex sobre el
cuerpo del mensaje en MVP.

El filter también emite un record de auditoría a nivel DEBUG nombrando los
campos redactados (NO sus valores) para que la disciplina de `PII` se
pueda verificar post-hoc sin filtrar contenido.
"""

from __future__ import annotations

__all__ = [
    "DENYLIST",
    "MASK",
    "PII_PREFIX",
    "PiiMaskingFilter",
    "is_pii_name",
    "mask_dict",
]

import logging
from collections.abc import Mapping

MASK: str = "***"
PII_PREFIX: str = "pii_"

# Nombres de campo cuyos VALORES son `PII`. Los nombres en sí son seguros
# para loguear (identifican qué se redactó, no a quién). Lowercased para
# matching case-insensitive.
#
# NOTA: ``name`` intencionalmente NO está acá aunque el nombre del cliente
# sea `PII` — colisiona con ``LogRecord.name`` (el nombre del logger), lo
# cual enmascararía la identidad del logger y dispara una recursión infinita
# en el audit-log. Usar ``customer_name`` / ``nombre`` para el campo de
# cliente del banco en su lugar.
DENYLIST: frozenset[str] = frozenset(
    {
        "cif",
        "customer_name",
        "account_number",
        "nombre",
        "phone",
        "email",
        "address",
        "dni",
    }
)


_audit = logging.getLogger("cmcourier.observability.pii")


class PiiMaskingFilter(logging.Filter):
    """Redacta valores `PII` de cada ``LogRecord`` in-place.

    Hace match de los nombres de campo de forma case-insensitive contra
    :data:`DENYLIST` O cualquier campo que arranque con :data:`PII_PREFIX`.
    Los nombres se conservan intactos; los valores se reemplazan con
    :data:`MASK`.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        masked: list[str] = []
        for key in list(record.__dict__):
            if self._is_pii(key) and record.__dict__[key] != MASK:
                record.__dict__[key] = MASK
                masked.append(key)
        if masked:
            _audit.debug(
                "pii_masked",
                extra={"fields": ",".join(sorted(masked))},
            )
        return True

    @staticmethod
    def _is_pii(field_name: str) -> bool:
        return is_pii_name(field_name)


def is_pii_name(field_name: str) -> bool:
    """Devuelve ``True`` cuando *field_name* nombra un campo que lleva `PII`.

    Hace match case-insensitive contra :data:`DENYLIST` O cualquier prefijo
    que arranque con :data:`PII_PREFIX`. Los ids de propiedad CMIS llevan
    su dominio en el sufijo después del último separador ``:`` o ``.``
    (por ejemplo ``clbNonGroup.BAC_CIF`` -> ``bac_cif``;
    ``cmcourier:Nombre_Cliente`` -> ``nombre_cliente``). El sufijo se
    chequea contra ``DENYLIST`` después de la misma normalización que usa
    el filter legacy, así los nombres de propiedad a nivel wire mapean al
    mismo set de redacción que ``extra={"cif": ...}``.
    """
    lower = field_name.lower()
    if lower in DENYLIST or lower.startswith(PII_PREFIX):
        return True
    suffix = lower
    for sep in (".", ":"):
        if sep in suffix:
            suffix = suffix.rsplit(sep, 1)[1]
    # Saca el prefijo de banco al inicio (por ejemplo ``bac_cif`` -> ``cif``)
    # para que los nombres amigables del `denylist` cubran las variantes
    # a nivel wire.
    bare = suffix.removeprefix("bac_")
    if suffix in DENYLIST or bare in DENYLIST:
        return True
    return any(token in DENYLIST for token in suffix.split("_") if token)


def mask_dict(properties: Mapping[str, str], *, unmask: bool = False) -> dict[str, str]:
    """Devuelve una copia de *properties* con los valores `PII` redactados a :data:`MASK`.

    Las claves se preservan verbatim — los nombres de campo en sí son
    seguros para loguear (identifican qué se redactó, no a quién). Los
    valores se redactan cuando la clave hace match con :func:`is_pii_name`.
    ``unmask=True`` devuelve el input verbatim (lo usa el `escape hatch`
    de debugging ``observability.unmask_pii``).
    """
    if unmask:
        return dict(properties)
    return {k: (MASK if is_pii_name(k) else v) for k, v in properties.items()}
