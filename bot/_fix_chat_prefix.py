import pathlib
p = pathlib.Path(r'D:\Program\QQ-Bot-Class\dsh-bot\bot\main.py')
lines = p.read_text(encoding='utf-8').splitlines()
out = []
i = 0
fixed = 0
while i < len(lines):
    line = lines[i]
    if line.strip().startswith('"只要别复述工具过程、别把聊天当任务汇报。'):
        indent = line[:len(line) - len(line.lstrip())]
        out.append(indent + '"只要别复述工具过程、别把聊天当任务汇报。" + chr(10)')
        # 后面的 broken 行（只剩引号）要吞掉
        j = i + 1
        while j < len(lines) and lines[j].strip() in ('"', '""'):
            j += 1
        i = j
        fixed += 1
        continue
    out.append(line)
    i += 1
p.write_text(chr(10).join(out) + chr(10), encoding='utf-8')
print('fixed', fixed)
