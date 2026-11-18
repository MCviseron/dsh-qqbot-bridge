import pathlib
p = pathlib.Path(r'D:\Program\QQ-Bot-Class\dsh-bot\bot\main.py')
t = p.read_text(encoding='utf-8')


def sub(old, new):
    global t
    assert old in t, 'anchor missing: %r' % old[:70]
    t = t.replace(old, new, 1)


# 1) 消息池转写带时间戳
sub('''        lines = [
            f"{'你（机器人）' if item.outbound else item.author}: {item.text}"
            for item in items[-limit:]
        ]''',
    '''        lines = [
            f"[{time.strftime('%H:%M', time.localtime(item.at))}] "
            f"{'你（机器人）' if item.outbound else item.author}: {item.text}"
            for item in items[-limit:]
        ]''')

# 2) 群聊缓冲行带时间戳
sub('''        entry.lines.append(f"{sender}: {text}")''',
    '''        entry.lines.append(f"[{time.strftime('%H:%M')}] {sender}: {text}")''')

p.write_text(t, encoding='utf-8')
print('timestamps wired (bot)')
