"""Adapters layer - concrete implementations of domain ports.

The only place I/O lives. Each subpackage holds adapters by responsibility:
``sources/`` (data sources), ``tracking/`` (idempotency store),
``assembly/`` (PDF assembly), ``upload/`` (CMIS upload).
"""
