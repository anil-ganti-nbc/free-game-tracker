
def test_api_state_dateless_events():
    from unittest.mock import patch
    from newsroom.webapp import get_state
    from newsroom.models import NewsEvent, Source, EventType, Category, PromotionType, OwnershipModel, AccessModel
    
    e1 = NewsEvent(
        source=Source.PLAYSTATION_PLUS,
        category=Category.SUBSCRIPTION,
        promotion_type=PromotionType.GIVEAWAY,
        event_type=EventType.CLAIMABLE_GAME,
        access_model=AccessModel.CLAIMABLE,
        ownership_model=OwnershipModel.PERMANENT_WHILE_ACCOUNT_EXISTS,
        title="Dateless Event",
        url="http://a",
        available_from=None
    )
    
    with patch('newsroom.webapp.load_all_events', return_value=[e1]), \
         patch('newsroom.webapp.load_source_health', return_value=[]), \
         patch('newsroom.webapp.load_new_releases', return_value=[]), \
         patch('newsroom.webapp.load_deals', return_value=[]):
        
        state = get_state()
        assert len(state['giveaways']) == 1
        assert state['giveaways'][0]['title'] == 'Dateless Event'
