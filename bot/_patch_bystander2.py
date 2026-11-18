import pathlib
p = pathlib.Path(r'D:\Program\QQ-Bot-Class\dsh-bot\bot\main.py')
lines = p.read_text(encoding='utf-8').splitlines()

start = next(i for i, line in enumerate(lines) if line.strip() == 'prompt = chr(10).join(' or line.strip() == 'prompt = "\\n".join(')
end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == ')')

new_block = [
    '        speakers = [line.split(": ", 1)[0] for line in lines if ": " in line]',
    '        last_speaker = speakers[-1] if speakers else "群友"',
    '        prev_speaker = speakers[-2] if len(speakers) > 1 else ""',
    '        last_text = lines[-1].split(": ", 1)[-1] if lines else ""',
    '        called = self.addresses_bot(last_text)',
    '        if called:',
    '            audience = f"最后一句来自 {last_speaker}，里面叫了你的名字（别名：{self._alias_list()}），是在跟你说话。"',
    '        elif prev_speaker and prev_speaker != last_speaker:',
    '            audience = (',
    '                f"最后一句来自 {last_speaker}，上一句来自 {prev_speaker} —— 看起来是"',
    '                f"{prev_speaker} 和 {last_speaker} 在他们之间对话，你只是旁观者。"',
    '            )',
    '        else:',
    '            audience = f"最后一句来自 {last_speaker}，没有点名你，也没看出是在问你。"',
    '',
    '        prompt = chr(10).join(',
    '            [',
    '                "【群聊插话判断】",',
    '                situation,',
    '                audience,',
    '                "",',
    '                "这之后群里在聊：",',
    '                *lines,',
    '                "",',
    '                "先判断说话对象，再决定要不要说话：",',
    '                f"- 有人叫你的名字/别名（{self._alias_list()}）或明显在问你：必须回答，不许回 [NO_REPLY]；",',
    '                "- 如果是两个群友在互相说话：不要把自己当成被邀请或被回答的人，不要替他们接话"',
    '                "（反例：A 说“我们去玩游戏吧”，你回“好呀好呀我们玩什么”就是错的）；"',
    '                "  想参与就只做一句旁观式调侃/补刀，不需要回应具体某个人，觉得没意思就 [NO_REPLY]；",',
    '                "- 如果他们在接着你的话：顺着聊 1~2 句口语；",',
    '                "- 不要重复自己说过的内容，不要总结/复述别人的聊天，不要客套，不要写成报告。",',
    '            ]',
    '        )',
]

lines[start:end + 1] = new_block
p.write_text(chr(10).join(lines) + chr(10), encoding='utf-8')
print('bystander block replaced')
