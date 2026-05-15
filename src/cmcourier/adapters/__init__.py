"""Capa de adaptadores — implementaciones concretas de los puertos del dominio.

Es el único lugar donde vive el I/O. Cada subpaquete agrupa adaptadores por
responsabilidad: ``sources/`` (fuentes de datos), ``tracking/`` (almacén de
idempotencia), ``assembly/`` (ensamblado de PDF), ``upload/`` (subida `cmis`).
"""
