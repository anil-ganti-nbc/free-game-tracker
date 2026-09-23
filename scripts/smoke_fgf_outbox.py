"""Isolated installed-image rehearsal of FGF outbox, without external HTTP."""

from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import select

from newsroom import database as db
from newsroom import discovery_delivery as leads
from newsroom.config import settings
from newsroom.discovery import collect


def listing(*ids: str) -> str:
    entries = "".join(
        f"<entry><id>t3_{item}</id><title>[Steam] (Game) {item}</title>"
        f'<link href="https://www.reddit.com/r/FreeGameFindings/comments/{item}/story/"/>'
        "<published>2026-09-23T00:00:00Z</published></entry>"
        for item in ids
    )
    return '<feed xmlns="http://www.w3.org/2005/Atom">' + entries + "</feed>"


with TemporaryDirectory() as directory:
    settings.database_path = Path(directory) / "smoke.db"
    settings.enable_reddit_fgf_delivery = True
    db.reset_engine()
    db.init_db()
    collect(leads.FGF_SOURCE, get=lambda _: (200, listing("baseline")))
    assert leads.drain_leads(webhook_url="")["reddit_leads_pending"] == 0
    collect(leads.FGF_SOURCE, get=lambda _: (200, listing("new", "baseline")))
    sent = []

    def accept(_url: str, payload: dict[str, object]) -> bool:
        sent.append(payload)
        return True

    outcome = leads.drain_leads(send=accept, webhook_url="https://discord.invalid/test")
    assert outcome["reddit_leads_posted"] == 1
    db.reset_engine()
    assert (
        leads.drain_leads(send=accept, webhook_url="https://discord.invalid/test")[
            "reddit_leads_posted"
        ]
        == 0
    )
    with db.session_scope() as session:
        rows = list(session.scalars(select(db.DiscoveryDeliveryRow)))
    assert len(rows) == 1 and rows[0].status == "delivered" and len(sent) == 1
    assert sent[0]["content"] == leads.LEAD_LABEL
    print("FGF isolated outbox smoke: baseline=0, new=1, posted=1, replay=0")
    db.reset_engine()
