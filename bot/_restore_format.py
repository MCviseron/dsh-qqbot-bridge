import pathlib
p = pathlib.Path(r'D:\Program\QQ-Bot-Class\dsh-bot\bot\main.py')
lines = p.read_text(encoding='utf-8').splitlines()

start = next(i for i, line in enumerate(lines) if line.strip() == 'prompt = chr(10).join(')
end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == ')')

block = [
    '        prompt = chr(10).join(',
    '            [',
    '                "【群聊插话判断】",',
    '                situation,',
    '                audience,',
    '                "",',
    '                "这之后群里在聊：",',
    '                *lines,',
    '                "",',
    '                "像群里的一员那样判断：",',
    '                f"- 如果有人叫你的名字/别名（{self._alias_list()}）或者明显在问你，就正常回答；",',
    '                "- 如果他们在接着你的话、或者问到你了，就顺着聊 1~2 句口语；",',
    '                "- 如果别人在互相聊，别把他们的话当成对你的邀请，想插话就轻一点，不想说就只回 [NO_REPLY]；",',
    '                "- 如果你刚说过类似的话、或者插不上嘴，也可以只回 [NO_REPLY]；",',
    '                "- 不要重复自己说过的内容，不要总结/复述别人的聊天，不要客套，不要写成报告。",',
    '            ]',
    '        )',
]
lines[start:end + 1] = block

text = chr(10).join(lines)

# 闲聊前缀恢复原样
i = text.index('            text = (')
j = text.index('            ) + text', i)
text = text[:i] + '            text = "【闲聊模式】简短口语回 1~3 句，不要调用工具、不要复述过程。" + chr(10) + text' + text[j + len('            ) + text'):]

p.write_text(text, encoding='utf-8')
print('format restored')
