"""Parser del mini-lenguaje ``--source <descriptor>`` (023).

Dos esquemas llevan informacion suficiente en los args del CLI como
para construir un `S0Strategy` de punta a punta:

* ``csv:<path>``: path a un CSV de triggers.
* ``single_doc:<shortname>,<system_id>[,<cif>]``: trigger one-off.

Los otros esquemas (``rvabrep:``, ``as400:``, ``local_scan:``)
necesitan mas config de la que pueden cargar los args del CLI;
rechazamos con un hint claro que apunta a los operadores al
``trigger.kind`` del YAML.
"""

from __future__ import annotations

__all__ = ["ParsedDescriptor", "parse_source_descriptor"]

from dataclasses import dataclass
from pathlib import Path

from cmcourier.domain.exceptions import ConfigurationError

_NEEDS_YAML: frozenset[str] = frozenset({"rvabrep", "as400", "local_scan"})


@dataclass(frozen=True, slots=True)
class ParsedDescriptor:
    """Resultado de parsear un string ``--source <value>``."""

    scheme: str
    path: Path | None = None
    shortname: str = ""
    system_id: str = ""
    cif: str | None = None


def parse_source_descriptor(value: str) -> ParsedDescriptor:
    """Parsea un descriptor ``scheme:body``.

    Levanta ``ConfigurationError`` para esquemas desconocidos /
    no soportados, con guia legible para el operador.
    """
    if ":" not in value:
        raise ConfigurationError(
            "expected '<scheme>:<body>' (e.g. 'csv:./t.csv' or 'single_doc:SHORT,SYS[,CIF]')",
            descriptor=value,
        )
    scheme, body = value.split(":", 1)
    scheme = scheme.lower()
    if scheme == "csv":
        if not body:
            raise ConfigurationError(
                "csv scheme requires a path body",
                descriptor=value,
            )
        return ParsedDescriptor(scheme="csv", path=Path(body).expanduser())
    if scheme == "single_doc":
        parts = body.split(",", 2)
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise ConfigurationError(
                "single_doc scheme requires 'SHORTNAME,SYSTEM_ID[,CIF]'",
                descriptor=value,
            )
        return ParsedDescriptor(
            scheme="single_doc",
            shortname=parts[0],
            system_id=parts[1],
            cif=parts[2] if len(parts) == 3 and parts[2] else None,
        )
    if scheme in _NEEDS_YAML:
        raise ConfigurationError(
            f"scheme {scheme!r} cannot be specified via --source — use the "
            f"YAML's trigger.kind and invoke `cmcourier inspect trigger` "
            f"without --source",
            descriptor=value,
        )
    raise ConfigurationError(
        f"unknown source scheme {scheme!r}; accepted: 'csv', 'single_doc'",
        descriptor=value,
    )
