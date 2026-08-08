import re

with open('newsroom/webapp.py', 'r', encoding='utf-8') as f:
    text = f.read()

python_target = '''def _display_props(event: NewsEvent) -> dict[str, Any]:
    from newsroom.models import Category
    is_sub = event.category == Category.SUBSCRIPTION
    
    if is_sub:
        start = event.available_from
        end = event.available_until or event.claim_deadline
        service_name = event.service or "Subscription"
        ev_type = event.event_type.value.replace("_", " ") if event.event_type else ""
        label = f"{service_name} {ev_type}".strip()
    else:
        start = event.promotion_start
        end = event.promotion_end
        label = "Giveaway"
        
    return {
        "display_start": start.isoformat() if start else "",
        "display_end": end.isoformat() if end else "",
        "bucket": "expired" if event.is_expired() else "current",
        "label": label,
        "is_subscription": is_sub,
        "category": event.category.value
    }'''

python_replacement = '''def _display_props(event: NewsEvent) -> dict[str, Any]:
    from newsroom.models import Category, Source, PromotionType, AccessModel

    is_sub = event.category == Category.SUBSCRIPTION

    if event.source == Source.GEFORCE_NOW:
        label = "Streaming Support"
    elif event.promotion_type == PromotionType.WEEKEND_TRIAL:
        label = "Free Weekend"
    elif is_sub:
        if event.access_model == AccessModel.CLAIMABLE:
            label = "Claimable"
        else:
            label = "Subscription"
    else:
        label = "Free to Keep"

    if is_sub:
        start = event.available_from
        end = event.available_until or event.claim_deadline
    else:
        start = event.promotion_start
        end = event.promotion_end

    return {
        "display_start": start.isoformat() if start else "",
        "display_end": end.isoformat() if end else "",
        "bucket": "expired" if event.is_expired() else "current",
        "label": label,
        "is_subscription": is_sub,
        "category": event.category.value,
    }'''

text = text.replace(python_target, python_replacement)

js_target = """  $("giveaways").innerHTML = legacy.length ? `<table>
    <tr><th>Game</th><th>Price</th><th>Ends</th></tr>` +
    legacy.map(g => `<tr>
      <td><a href="${esc(g.url)}" target="_blank" rel="noopener">${esc(g.title)}</a></td>
      <td>${money(g.original_price)} → Free</td>
      <td>${g.display_end ? esc(g.display_end.slice(0,10)) : "—"}</td>
    </tr>`).join("") + `</table>`"""

js_replacement = """  $("giveaways").innerHTML = legacy.length ? `<table>
    <tr><th>Game</th><th>Label</th><th>Ends</th></tr>` +
    legacy.map(g => `<tr>
      <td><a href="${esc(g.url)}" target="_blank" rel="noopener">${esc(g.title)}</a></td>
      <td><span class="pill ok">${esc(g.label)}</span></td>
      <td>${g.display_end ? esc(g.display_end.slice(0,10)) : "—"}</td>
    </tr>`).join("") + `</table>`"""

text = text.replace(js_target, js_replacement)

with open('newsroom/webapp.py', 'w', encoding='utf-8') as f:
    f.write(text)
