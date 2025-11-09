"""Database routers.

Defines a router that prevents any migrations or write operations to the
'osm' database alias. Pair this with the connection option
`default_transaction_read_only=on` (configured in settings) to hard-fail
any attempted writes via .using('osm').
"""

from typing import Optional


class OSMReadOnlyRouter:
    alias = 'osm'

    def db_for_read(self, model, **hints) -> Optional[str]:
        """
        Don't route reads implicitly; callers should opt-in with .using('osm')
        when they actually want to read from OSM.
        """
        return None

    def db_for_write(self, model, **hints) -> Optional[str]:
        """
        Do not route writes to 'osm' implicitly. If code calls .using('osm')
        the router can't override that; write attempts will still be blocked
        by the connection-level read-only setting.
        """
        return None

    def allow_relation(self, obj1, obj2, **hints) -> Optional[bool]:
        """
        Allow relations within the same DB; disallow relations between 'osm' and others.
        """
        db1 = getattr(obj1._state, 'db', None)
        db2 = getattr(obj2._state, 'db', None)
        if db1 and db2:
            if db1 == db2:
                return True
            if self.alias in {db1, db2}:
                return False
        return None

    def allow_migrate(self, db: str, app_label: str, model_name: Optional[str] = None, **hints) -> Optional[bool]:
        """
        Never run migrations on the 'osm' database.
        """
        if db == self.alias:
            return False
        return None