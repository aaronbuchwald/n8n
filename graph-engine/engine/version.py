"""Single source of the schema/contract version.

Kept in its own module so both :mod:`engine.graph` and :mod:`engine.schema`
depend on it without a cycle.

Versioning policy (informal for now — see docs/adr/0001-*.md):
* additive changes (new optional fields) bump the MINOR version;
* validators are lenient — unknown fields are ignored, so a newer document
  still validates against an older reader. Formal migration machinery is
  deferred until backwards-compatibility first matters.
"""

SCHEMA_VERSION = "0.2.0"
