
with open('newsroom/tests/test_webapp.py', 'r', encoding='utf-8') as f: text = f.read()
text = text.replace('score=95, reasons=[]', 'score=95, reasons=["mock"]')
with open('newsroom/tests/test_webapp.py', 'w', encoding='utf-8') as f: f.write(text)
