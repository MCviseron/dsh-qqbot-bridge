import pathlib
p = pathlib.Path(r'D:\Program\QQ-Bot-Class\dsh-bot\bot\main.py')
t = p.read_text(encoding='utf-8')


def sub(old, new):
    global t
    assert old in t, 'anchor missing: %r' % old[:70]
    t = t.replace(old, new, 1)


# 1) 根因：只在正文里叫了名字也算"点名"，不该走插话判断
sub('''            mentioned = await self._mentions_bot(message)
            commanded = text.startswith("/")
            if mentioned or commanded:''',
    '''            mentioned = await self._mentions_bot(message)
            named = self.addresses_bot(text)
            commanded = text.startswith("/")
            if mentioned or named or commanded:''')

sub('''                log.info("treat as addressed (mention=%s cmd=%s)", mentioned, commanded)''',
    '''                log.info("treat as addressed (mention=%s name=%s cmd=%s)", mentioned, named, commanded)''')

# 2) 插话判断里的兜底：缓冲里有人叫名字就直接答，不交给判断模型
sub('''        lines = list(entry.lines)
        entry.lines.clear()''',
    '''        lines = list(entry.lines)

        # Someone naming the bot inside plain chatter must get a real answer:
        # the judge prompt offers [NO_REPLY], and a called bot must not take it.
        if any(self.addresses_bot(line) for line in lines):
            self.chatter.pop(conv_key, None)
            joined = "\n".join(line.split(": ", 1)[-1] for line in lines)
            log.info("chatter named the bot; answering instead of judging (%d line(s))", len(lines))
            await self._submit(conv_key, joined, "群友", False, None, chat=False)
            return

        entry.lines.clear()''')

# 3) 判断提示词加硬规则
sub('''                "像群里的一员那样判断：",
                "- 如果他们在接着你的话、或者问到你了，就顺着聊 1~2 句口语；",''',
    '''                "像群里的一员那样判断：",
                f"- 如果有人叫你的名字/别名（{self._alias_list()}）或者明显在问你，**必须回答**，不许回 [NO_REPLY]；",
                "- 如果他们在接着你的话、或者问到你了，就顺着聊 1~2 句口语；",''')

# 4) 别名列表复用
sub('''    def addresses_bot(self, text: str) -> bool:
        """Whether the text names the bot without an explicit @ mention."""
        lowered = text.lower()
        raw = self.rt_str("bot_aliases", ",".join(self.config.bot_aliases))
        aliases = [part.strip() for part in raw.split(",") if part.strip()]
        return any(alias.lower() in lowered for alias in aliases)''',
    '''    def _alias_list(self):
        raw = self.rt_str("bot_aliases", ",".join(self.config.bot_aliases))
        return ", ".join(part.strip() for part in raw.split(",") if part.strip())

    def addresses_bot(self, text: str) -> bool:
        """Whether the text names the bot without an explicit @ mention."""
        lowered = text.lower()
        raw = self.rt_str("bot_aliases", ",".join(self.config.bot_aliases))
        aliases = [part.strip() for part in raw.split(",") if part.strip()]
        return any(alias.lower() in lowered for alias in aliases)''')

p.write_text(t, encoding='utf-8')
print('plan A fixed: alias addressing + judge safety net + prompt rule')
