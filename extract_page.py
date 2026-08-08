import re
with open('newsroom/webapp.py', 'r', encoding='utf-8') as f:
    text = f.read()

s = text.find('_PAGE = """')
with open('page.txt', 'w', encoding='utf-8') as f:
    f.write(text[s:])
