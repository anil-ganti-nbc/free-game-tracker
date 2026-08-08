with open('newsroom/webapp.py', 'r', encoding='utf-8') as f: lines = f.readlines()
lines[66] = '    d = {\n'
with open('newsroom/webapp.py', 'w', encoding='utf-8') as f: f.writelines(lines)
