import pathlib
p = pathlib.Path(r'D:\Program\QQ-Bot-Class\dsh-bot\bot\main.py')
text = p.read_text(encoding='utf-8')

# 1) 判断规则：从"下命令"改成"给事实 + 交给模型"
old_start = text.index('                "先判断说话对象，再决定要不要说话：",')
old_end = text.index('            ]\n        )\n        log.info("judging', old_start)
new_rules = '''                "判断你自己要不要插一句，怎么插由你定：",
                f"- 上面已经给出说话对象；如果是在跟你说话（叫了 {self._alias_list()} 或明显问你），正常回答即可；",
                "- 如果别人在互相聊，注意别把他们的对话当成对你的邀请（A 说“我们去玩吧”，你回“好呀好呀玩什么”就很怪）；",
                "- 想说话就自然地说，接话、调侃、补刀、提问都行，不必套固定风格；不想说就只回 [NO_REPLY]；",
                "- 别复述别人的话，别写成报告，别重复自己刚说过的内容。",
'''
text = text[:old_start] + new_rules + text[old_end:]

# 2) 闲聊提示词也放宽：不再限制必须短/不许用工具
old_chat = '''            text = "【闲聊模式】简短口语回 1~3 句，不要调用工具、不要复述过程。\n" + text'''
new_chat = '''            text = (
                "【群聊插话】这是群里的闲聊，你只是其中一员；说多长、要不要用工具都由你判断，"
                "只要别复述工具过程、别把聊天当任务汇报。\n"
            ) + text'''
assert old_chat in text or '【闲聊模式】' in text
if old_chat in text:
    text = text.replace(old_chat, new_chat, 1)
else:
    i = text.index('【闲聊模式】')
    line_start = text.rindex('            text = ', 0, i)
    line_end = text.index('\n', i)
    text = text[:line_start] + new_chat + text[line_end:]

p.write_text(text, encoding='utf-8')
print('judge prompt relaxed')
