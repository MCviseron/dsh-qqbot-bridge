import pathlib
base = pathlib.Path(r'D:\Program\QQ-Bot-Class\dsh-bot')

rc = base / 'bot' / 'runtime_config.py'
t = rc.read_text(encoding='utf-8')
anchor = '''    # 群聊主动消息策略'''
assert anchor in t
t = t.replace(anchor, '''    # 「还在处理，请稍等…」这种占位提示：默认关闭（会打断流式、影响观感）
    "ack_enabled": False,
''' + anchor, 1)
rc.write_text(t, encoding='utf-8')

p = base / 'bot' / 'main.py'
m = p.read_text(encoding='utf-8')
old = '''    def _arm_ack(self, conv_key: str) -> None:'''
assert old in m
i = m.index(old)
# 在 _arm_ack 函数体开头插入开关判断
body_start = m.index(chr(10), m.index('"""', i)) + 1
guard = '        if not self.rt_bool("ack_enabled", False):' + chr(10) + '            return' + chr(10)
m = m[:body_start] + guard + m[body_start:]
p.write_text(m, encoding='utf-8')

html = base / 'bot' / 'panel.html'
h = html.read_text(encoding='utf-8')
row = '<div class="row"><label>群聊主动消息模式'
assert row in h
h = h.replace(row, '<div class="row"><label>“还在处理”占位提示<div class="hint">会打断流式输出，默认关闭</div></label><div class="sw" data-key="ack_enabled"></div></div>' + chr(10) + row, 1)
html.write_text(h, encoding='utf-8')
print('ack disabled by default')
