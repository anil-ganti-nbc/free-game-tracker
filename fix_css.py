import re

with open('newsroom/webapp.py', 'r', encoding='utf-8') as f:
    text = f.read()

css_replacement = '''</style>
<style>
  input[type=range] {
    -webkit-appearance: none;
    appearance: none;
    width: 120px;
    background: transparent;
    vertical-align: middle;
    margin: 0 8px;
  }
  input[type=range]:focus {
    outline: none;
  }
  input[type=range]::-webkit-slider-runnable-track {
    width: 100%;
    height: 4px;
    cursor: pointer;
    background: var(--line);
    border-radius: 2px;
  }
  input[type=range]::-webkit-slider-thumb {
    height: 16px;
    width: 16px;
    border-radius: 50%;
    background: var(--accent);
    cursor: pointer;
    -webkit-appearance: none;
    margin-top: -6px;
  }
  input[type=range]::-moz-range-track {
    width: 100%;
    height: 4px;
    cursor: pointer;
    background: var(--line);
    border-radius: 2px;
  }
  input[type=range]::-moz-range-thumb {
    height: 16px;
    width: 16px;
    border-radius: 50%;
    background: var(--accent);
    cursor: pointer;
    border: none;
  }
</style>'''

text = text.replace('</style>', css_replacement)

with open('newsroom/webapp.py', 'w', encoding='utf-8') as f:
    f.write(text)
