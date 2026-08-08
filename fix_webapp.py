import re
with open('newsroom/webapp.py', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Update _serialize_event to include display_props
helper_code = '''
def _display_props(event: NewsEvent) -> dict[str, Any]:
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
    }

def _serialize_event(event: NewsEvent) -> dict[str, Any]:
'''

text = text.replace('def _serialize_event(event: NewsEvent) -> dict[str, Any]:', helper_code)

update_code = '''
        "claim_deadline": event.claim_deadline.isoformat() if event.claim_deadline else None,
        "day_one": event.day_one,
    }
    d.update(_display_props(event))
    return d
'''
text = text.replace('''        "claim_deadline": event.claim_deadline.isoformat() if event.claim_deadline else None,
        "day_one": event.day_one,
    }''', update_code)

# 2. Add subscriptions section in _PAGE HTML
page_target = '''<div id="msg" class="msg muted"></div>
  <section><h2>Current free giveaways</h2><div id="giveaways"></div></section>
  <section>'''
page_replacement = '''<div id="msg" class="msg muted"></div>
  <section><h2>Current free giveaways</h2><div id="giveaways"></div></section>
  <section><h2>Subscription Catalog & Claims</h2><div id="subscriptions"></div></section>
  <section>'''
text = text.replace(page_target, page_replacement)

# 3. Update JS in _PAGE HTML
js_target = '''$("giveaways").innerHTML = s.giveaways.length ? `<table>
    <tr><th>Game</th><th>Price</th><th>Ends</th></tr>` +
    s.giveaways.map(g => `<tr>
      <td><a href="${esc(g.url)}" target="_blank" rel="noopener">${esc(g.title)}</a></td>
      <td>${money(g.original_price)} → Free</td>
      <td>${g.promotion_end ? esc(g.promotion_end.slice(0,10)) : "—"}</td>
    </tr>`).join("") + `</table>`
    : `<p class="muted">No active giveaways.</p>`;'''

js_replacement = '''
  const isOk = g => g.bucket !== "expired";
  const legacy = s.giveaways.filter(g => !g.is_subscription && isOk(g));
  const subs = s.giveaways.filter(g => g.is_subscription && isOk(g));
  const history = s.giveaways.filter(g => !isOk(g));
  
  $("giveaways").innerHTML = legacy.length ? `<table>
    <tr><th>Game</th><th>Price</th><th>Ends</th></tr>` +
    legacy.map(g => `<tr>
      <td><a href="${esc(g.url)}" target="_blank" rel="noopener">${esc(g.title)}</a></td>
      <td>${money(g.original_price)} → Free</td>
      <td>${g.display_end ? esc(g.display_end.slice(0,10)) : "—"}</td>
    </tr>`).join("") + `</table>`
    : `<p class="muted">No active giveaways.</p>`;
    
  if($("subscriptions")){
      $("subscriptions").innerHTML = subs.length ? `<table>
        <tr><th>Game</th><th>Timeline</th><th>Type</th></tr>` +
        subs.map(g => `<tr>
          <td><a href="${esc(g.url)}" target="_blank" rel="noopener">${esc(g.title)}</a></td>
          <td>${g.display_start ? esc(g.display_start.slice(0,10)) : "—"} to ${g.display_end ? esc(g.display_end.slice(0,10)) : "—"}</td>
          <td><span class="pill ok">${esc(g.label)}</span></td>
        </tr>`).join("") + `</table>`
        : `<p class="muted">No subscription events.</p>`;
  }
'''
text = text.replace(js_target, js_replacement)

with open('newsroom/webapp.py', 'w', encoding='utf-8') as f:
    f.write(text)
