import pathlib
base = pathlib.Path(r'D:\Program\QQ-Bot-Class\dsh-bot')

# 1) 运行时可配置的消息池窗口
rc = base / 'bot' / 'runtime_config.py'
t = rc.read_text(encoding='utf-8')
anchor = '''    # 引用消息：识别开关、随提示词带给模型的原文上限、排查日志'''
assert anchor in t
t = t.replace(anchor, '''    # 消息池（引用解析 + /撤回 + 插话判断的上下文窗口）
    "pool_ttl_s": 1800,
    "pool_max": 100,
''' + anchor, 1)
rc.write_text(t, encoding='utf-8')

# 2) 用运行时值替换常量
p = base / 'bot' / 'main.py'
m = p.read_text(encoding='utf-8')


def sub(old, new, count=1):
    global m
    assert old in m, 'anchor missing: %r' % old[:60]
    m = m.replace(old, new, count)


sub('''    def _pool_add(self, item: PooledMessage) -> None:''',
    '''    def _pool_ttl(self) -> float:
        return max(60.0, self.rt_float("pool_ttl_s", MSG_POOL_TTL_S))

    def _pool_limit(self) -> int:
        return max(10, self.rt_int("pool_max", MSG_POOL_MAX))

    def _pool_add(self, item: PooledMessage) -> None:''')

sub('        cutoff = time.time() - MSG_POOL_TTL_S\n', '        cutoff = time.time() - self._pool_ttl()\n')
sub('''        while len(self.pool) > MSG_POOL_MAX:''', '''        while len(self.pool) > self._pool_limit():''')
sub('        cutoff = time.time() - MSG_POOL_TTL_S\n', '        cutoff = time.time() - self._pool_ttl()\n')
sub('if item is None or item.at < time.time() - MSG_POOL_TTL_S:', 'if item is None or item.at < time.time() - self._pool_ttl():')
sub('if item is not None and item.at >= time.time() - MSG_POOL_TTL_S:', 'if item is not None and item.at >= time.time() - self._pool_ttl():')
sub('if item is None or item.at < time.time() - MSG_POOL_TTL_S:', 'if item is None or item.at < time.time() - self._pool_ttl():')

# 3) 判断提示词里的"没说过话"改成按窗口描述
sub('''            situation = "你在这群里还一句话都没说过。"''',
    '''            situation = (
                f"在最近 {int(self._pool_ttl() // 60)} 分钟 / 最近 {self._pool_limit()} 条消息的记录里，"
                "没看到你在群里说过话（不代表你从没说过，只是这些记录里没有）。"
            )''')

sub('''            situation = f"你在群里最近说过（{max(0, int(since))} 秒前）：\\u201c{spoke_text[:160]}\\u201d"''',
    '''            situation = (
                f"你在群里最近说过（{max(0, int(since))} 秒前）：\\u201c{spoke_text[:160]}\\u201d"
                f"（可参考的记录：最近 {int(self._pool_ttl() // 60)} 分钟 / 最近 {self._pool_limit()} 条）"
            )''')

p.write_text(m, encoding='utf-8')
print('pool config + wording wired')
