import pathlib
p = pathlib.Path(r'D:\Program\QQ-Bot-Class\dsh-bot\bot\main.py')
lines = p.read_text(encoding='utf-8').splitlines()
out = []
i = 0
fixed = 0
while i < len(lines):
    if lines[i].strip() == 'joined = "' and i + 1 < len(lines) and lines[i + 1].startswith('".join('):
        indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
        out.append(indent + 'joined = chr(10).join(line.split(": ", 1)[-1] for line in lines)')
        i += 2
        fixed += 1
        continue
    out.append(lines[i])
    i += 1
p.write_text("\n".join(out) + "\n", encoding='utf-8')
print('fixed', fixed)
