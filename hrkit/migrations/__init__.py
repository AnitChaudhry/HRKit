"""Migrations package for hrkit HR schema.

Holds versioned ``.sql`` files (named ``NNN_<description>.sql``) that are
applied in lexicographic order by ``hrkit.migration_runner.apply_all``.
This package intentionally contains no Python logic — the SQL files ship as
package data so the migration runner can read them via ``pkgutil.get_data``.
"""

from __future__ import annotations
