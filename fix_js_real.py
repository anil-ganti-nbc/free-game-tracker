with open('newsroom/webapp.py', 'r', encoding='utf-8') as f:
    text = f.read()

import re

# We will completely rip out the `$("giveaways").innerHTML` block and replace it.
# We will use Regex to match the block until `renderBreakouts();`

new_js = """
  const isOk = g => g.bucket !== "expired";
  const legacy = s.giveaways.filter(g => !g.is_subscription && isOk(g));
  const subs = s.giveaways.filter(g => g.is_subscription && isOk(g));
  const history = s.giveaways.filter(g => !isOk(g));

  $("giveaways").innerHTML = legacy.length ? `<table>
    <tr><th>Store</th><th>Game</th><th>Label</th><th>Ends</th></tr>` +
    legacy.map(g => `<tr>
      <td>${esc(g.source)}</td>
      <td><a href="${esc(g.url)}" target="_blank" rel="noopener">${esc(g.title)}</a></td>
      <td><span class="pill ok">${esc(g.label)}</span></td>
      <td>${g.display_end ? esc(g.display_end.slice(0,10)) : "—"}</td>
    </tr>`).join("") + `</table>`
    : `<p class="muted">No active giveaways.</p>`;

  if($("subscriptions")){
      $("subscriptions").innerHTML = subs.length ? `<table>
        <tr><th>Store</th><th>Game</th><th>Timeline</th><th>Type</th></tr>` +
        subs.map(g => `<tr>
          <td>${esc(g.source)}</td>
          <td><a href="${esc(g.url)}" target="_blank" rel="noopener">${esc(g.title)}</a></td>
          <td>${g.display_start ? esc(g.display_start.slice(0,10)) : "—"} to ${g.display_end ? esc(g.display_end.slice(0,10)) : "—"}</td>
          <td><span class="pill ok">${esc(g.label)}</span></td>
        </tr>`).join("") + `</table>`
        : `<p class="muted">No subscription events.</p>`;
  }
"""

text = re.sub(r'\$\("giveaways"\)\.innerHTML =[\s\S]*?(?=renderBreakouts\(\);)', new_js + '\n  ', text)

with open('newsroom/webapp.py', 'w', encoding='utf-8') as f:
    f.write(text)

