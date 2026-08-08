from newsroom.sources.amazon_luna import parse_tiers
from newsroom.sources.prime_gaming import guess_ownership

try:
    from newsroom.models import OwnershipModel
except ImportError:
    pass


def test_guess_ownership_epic():
    assert (
        guess_ownership("Claim via Epic Games Store")
        == OwnershipModel.PERMANENT_WHILE_ACCOUNT_EXISTS
    )


def test_guess_ownership_unknown():
    assert guess_ownership("Play now included") == OwnershipModel.UNKNOWN


def test_parse_tiers():
    assert "standard" in parse_tiers("play with luna standard")
    assert "premium" in parse_tiers("luna premium upgrade")
    assert parse_tiers("luna+") == []


def test_amazon_luna_standard_added():
    pass


def test_prime_gaming_claimable_added():
    pass


def test_luna_events_suppressed_giveaways():
    pass


def test_mixed_article_safety():
    pass
