with open('newsroom/webapp.py', 'r', encoding='utf-8') as f:
    text = f.read()
    if 'id="subscriptions"' in text:
        print('Yes, ID exists in HTML')
    else:
        print('NO.')
