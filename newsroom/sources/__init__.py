"""Source sensors.

Each module here (``epic``, ``steam``, ``gog``) fetches from one store and
returns a list of :class:`~newsroom.models.NewsEvent`. A source knows nothing
about the database, reporting, or other sources.

Milestone 1 ships this package empty on purpose. The first sensor (Epic) arrives
in Milestone 2, and a shared contract will be extracted only if and when the
second and third sensors show real duplication — not before.
"""
