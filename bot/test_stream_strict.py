import os as _os, tempfile as _tempfile
_os.environ.setdefault("DSH_QQBOT_STATE_DIR", _tempfile.mkdtemp(prefix="qqbot-test-"))
import asyncio, json, sys, pathlib, tempfile
sys.path.insert(0, '.')
import main


class FakeAPI:
    def __init__(self, fail_at=None, fail_msg="其它流式消息发送中"):
        self.calls = []
        self.fail_at = fail_at
        self.fail_msg = fail_msg

    async def post_c2c_stream_message(self, **kw):
        self.calls.append(kw)
        if self.fail_at is not None and len(self.calls) - 1 == self.fail_at:
            raise RuntimeError(self.fail_msg)
        return {'id': 'STREAM1'}


def make_bot(api):
    bot = main.DSHBot.__new__(main.DSHBot)
    bot._streams = {}
    bot._streamed_turns = {}
    bot._suppress_reply = set()
    bot._stream_locks = {}
    bot._stream_holdoff = {}
    bot._msg_seq = 0
    bot.targets = {'c2c:OWNER': type('T', (), {'openid': 'OWNER', 'last_msg_id': 'M1', 'kind': 'c2c', 'conv_key': 'c2c:OWNER'})()}
    bot.api = api
    bot.rt_bool = lambda k, d=False: True
    bot.rt_float = lambda k, d=0: d
    bot._persist_streams = lambda: None
    bot._spawn_files = lambda conv, text: None
    bot.sent = []
    async def send_text(conv, text, keyboard=None):
        bot.sent.append(text)
    bot.send_text = send_text
    return bot


async def case_index():
    api = FakeAPI()
    bot = make_bot(api)
    for chunk in ['你', '你好', '你好呀']:
        await bot._handle_stream({'convKey': 'c2c:OWNER', 'text': chunk, 'final': False, 'turnId': 't1'})
        bot._streams['c2c:OWNER']['last'] = 0  # bypass the interval throttle
    await bot._handle_stream({'convKey': 'c2c:OWNER', 'text': '。', 'final': True, 'turnId': 't1'})
    idx = [c['index'] for c in api.calls]
    states = [c['input_state'] for c in api.calls]
    print('index 序列:', idx, '严格递增:', all(b > a for a, b in zip(idx, idx[1:])))
    print('收尾帧数:', states.count(10), '| 最后一帧 index:', idx[-1])


async def case_fail_mid():
    api = FakeAPI(fail_at=1)
    bot = make_bot(api)
    await bot._handle_stream({'convKey': 'c2c:OWNER', 'text': '第一段', 'final': False, 'turnId': 't2'})
    bot._streams['c2c:OWNER']['last'] = 0
    await bot._handle_stream({'convKey': 'c2c:OWNER', 'text': '第二段', 'final': False, 'turnId': 't2'})
    print('中断后会话已丢弃:', 'c2c:OWNER' not in bot._streams, '| 已进入降级:', bot._stream_degraded('c2c:OWNER'))


async def case_degraded():
    api = FakeAPI()
    bot = make_bot(api)
    bot._hold_stream('c2c:OWNER', 'test')
    await bot._handle_stream({'convKey': 'c2c:OWNER', 'text': '整段回答', 'final': True, 'turnId': 't3'})
    print('降级时调用流式次数:', len(api.calls), '| 普通消息:', bot.sent)


async def case_seq():
    api = FakeAPI()
    bot = make_bot(api)
    await bot._handle_stream({'convKey': 'c2c:OWNER', 'text': 'a', 'final': False, 'turnId': 't4'})
    await bot._handle_stream({'convKey': 'c2c:OWNER', 'text': 'b', 'final': True, 'turnId': 't4'})
    await bot._handle_stream({'convKey': 'c2c:OWNER', 'text': 'c', 'final': False, 'turnId': 't5'})
    seq = sorted({c['msg_seq'] for c in api.calls})
    print('两次回合的 msg_seq:', seq, '| 互不相同:', len(seq) == 2)


for case in (case_index, case_fail_mid, case_degraded, case_seq):
    asyncio.run(case())