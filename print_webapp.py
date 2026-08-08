with open('newsroom/webapp.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
    for i, line in enumerate(lines):
        if '$("giveaways").innerHTML' in line:
            for j in range(i, i+15):
                try: print(lines[j].strip())
                except: pass
            break
