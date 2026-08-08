with open('newsroom/tests/test_playstation_plus.py', 'r', encoding='utf-8') as f:
    text = f.read()
text = text.replace('"Game A " in titles', '"Game A" in titles')
text = text.replace('"Game B " in titles', '"Game B" in titles')
text = text.replace('"Game C " in titles', '"Game C" in titles')
text = text.replace('"Game D " not in titles', '"Game D" not in titles')
text = text.replace('"Game E " not in titles', '"Game E" not in titles')
with open('newsroom/tests/test_playstation_plus.py', 'w', encoding='utf-8') as f:
    f.write(text)
