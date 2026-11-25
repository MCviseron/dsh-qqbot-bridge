"""pet_game：群内养成游戏（框架原生插件，完全不依赖 DSH）。

玩法（一个会话里每人一只）：
    /领养 名字      第一次领养（一个群/私聊里每人一只）
    /宠物           看自己的宠物面板
    /喂食           掉饥饿、加经验（有冷却）
    /摸摸           加心情（有冷却）
    /改名 新名字     改名
    /排行           本会话等级前 5

被动成长：每发一条消息 +1 金币（60 秒冷却）；定时任务每小时结算一次饥饿与心情。
数据落在 session/state/pet_game/pets.json，结构：{conv: {openid: pet}}。
"""

from __future__ import annotations

import random
import time
from typing import Any, Dict, List, Optional

from framework.plugin import Plugin, PluginContext

DEFAULTS = {
    "feed_cooldown_s": 30,
    "pat_cooldown_s": 20,
    "chat_coins_cooldown_s": 60,
    "decay_interval_s": 3600,
    "hunger_per_hour": 5,
    "mood_per_hour": 3,
    "exp_per_level": 50,
    "max_name_len": 12,
}

FEED_LINES = [
    "吃得很香，尾巴都摇起来了。",
    "一口就没了，还想要。",
    "嚼得嘎嘣响，看起来心情不错。",
]
PAT_LINES = [
    "被摸得眯起了眼睛。",
    "蹭了蹭你的手。",
    "翻了个身，露出肚皮。",
]
HUNGRY_LINES = [
    "肚子在叫了，要不要喂点东西？",
    "眼巴巴看着你。",
    "有点饿了，开始啃空气。",
]


class PetGamePlugin(Plugin):
    id = "pet_game"
    name = "群内养成游戏"
    version = "1.0.0"
    description = "领养 / 喂食 / 摸摸 / 排行：群里的养成小游戏"

    def __init__(self) -> None:
        super().__init__()
        self._store: Any = None

    # -- 配置 ---------------------------------------------------------------
    def cfg(self, key: str, default: Any = None) -> Any:
        section = dict(DEFAULTS)
        if self.ctx is not None:
            section.update(self.ctx.config())
        return section.get(key, default)

    # -- 数据 ---------------------------------------------------------------
    def pets(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        data = self._store.read()
        return {key: value for key, value in data.items() if isinstance(value, dict)}

    def my_pet(self, conv_key: str, openid: str) -> Optional[Dict[str, Any]]:
        return (self.pets().get(conv_key) or {}).get(openid)

    def save_pet(self, conv_key: str, openid: str, pet: Dict[str, Any]) -> None:
        def changer(data: Dict[str, Any]) -> None:
            bucket = data.setdefault(conv_key, {})
            bucket[openid] = pet

        self._store.update(changer)

    def new_pet(self, name: str, nickname: str = "") -> Dict[str, Any]:
        now = time.time()
        return {
            "name": name,
            "owner": nickname or "",
            "level": 1,
            "exp": 0,
            "hunger": 30,
            "mood": 70,
            "coins": 20,
            "born_at": now,
            "last_fed": 0.0,
            "last_pat": 0.0,
            "last_chat": 0.0,
            "feeds": 0,
            "pats": 0,
        }

    @staticmethod
    def level_of(exp: int, per_level: int = 50) -> int:
        return 1 + max(0, int(exp)) // max(1, per_level)

    def level_up(self, pet: Dict[str, Any]) -> bool:
        target = self.level_of(int(pet.get("exp", 0)), int(self.cfg("exp_per_level", 50)))
        if target > int(pet.get("level", 1)):
            pet["level"] = target
            return True
        return False

    # -- 生命周期 -----------------------------------------------------------
    async def setup(self, ctx: PluginContext) -> None:
        self._store = ctx.store("pets")
        self._register_commands(ctx)
        ctx.on("message", self.on_message, priority=300)
        ctx.every("decay", float(self.cfg("decay_interval_s", 3600)), self.decay, run_immediately=False)
        ctx.page("pets", "养成游戏", self.render_page)
        ctx.log.info("pet_game ready")

    # -- 命令 ---------------------------------------------------------------
    def _register_commands(self, ctx: PluginContext) -> None:
        @ctx.command("领养", aliases=("adopt",), summary="领养一只宠物", usage="<名字>", order=20)
        async def _adopt(context) -> None:
            name = context.raw_args.strip()[: int(self.cfg("max_name_len", 12))]
            if not name:
                context.fail("用法：/领养 <名字>，比如 /领养 小肥鱼")
            if self.my_pet(context.conv_key, context.sender.openid):
                context.fail("你已经养着一只了，用 /宠物 看看它，想改名用 /改名。")
            pet = self.new_pet(name, context.sender.display)
            self.save_pet(context.conv_key, context.sender.openid, pet)
            await context.say(
                "领养成功：" + name + " 出现了！\n用 /喂食 和 /摸摸 照顾它，聊天也会让它涨经验。"
            )

        @ctx.command("宠物", aliases=("pet", "我的宠物"), summary="查看自己的宠物面板", order=21)
        async def _pet(context) -> None:
            pet = self.my_pet(context.conv_key, context.sender.openid)
            if pet is None:
                context.fail("你还没有宠物，先 /领养 <名字>。")
            await context.say(self.render_pet(pet, context.sender.display))

        @ctx.command("喂食", aliases=("feed",), summary="喂一次（有冷却）", order=22)
        async def _feed(context) -> None:
            pet = self.my_pet(context.conv_key, context.sender.openid)
            if pet is None:
                context.fail("先 /领养 <名字>。")
            cooldown = float(self.cfg("feed_cooldown_s", 30))
            wait = cooldown - (time.time() - float(pet.get("last_fed", 0.0)))
            if wait > 0:
                context.fail("它刚吃过，" + str(int(wait) + 1) + " 秒后再喂。")
            if int(pet.get("coins", 0)) < 5:
                context.fail("金币不够（喂一次 5 金币，聊天能赚）。")
            pet["coins"] = int(pet.get("coins", 0)) - 5
            pet["hunger"] = max(0, int(pet.get("hunger", 0)) - 35)
            pet["mood"] = min(100, int(pet.get("mood", 0)) + 6)
            pet["exp"] = int(pet.get("exp", 0)) + 8
            pet["feeds"] = int(pet.get("feeds", 0)) + 1
            pet["last_fed"] = time.time()
            leveled = self.level_up(pet)
            self.save_pet(context.conv_key, context.sender.openid, pet)
            line = random.choice(FEED_LINES)
            extra = "\n升级了！现在是 Lv." + str(pet["level"]) + "。" if leveled else ""
            await context.say(pet["name"] + "：" + line + extra)

        @ctx.command("摸摸", aliases=("pat",), summary="摸摸宠物（有冷却）", order=23)
        async def _pat(context) -> None:
            pet = self.my_pet(context.conv_key, context.sender.openid)
            if pet is None:
                context.fail("先 /领养 <名字>。")
            cooldown = float(self.cfg("pat_cooldown_s", 20))
            wait = cooldown - (time.time() - float(pet.get("last_pat", 0.0)))
            if wait > 0:
                context.fail("它刚被摸过，" + str(int(wait) + 1) + " 秒后再来。")
            pet["mood"] = min(100, int(pet.get("mood", 0)) + 10)
            pet["exp"] = int(pet.get("exp", 0)) + 3
            pet["pats"] = int(pet.get("pats", 0)) + 1
            pet["last_pat"] = time.time()
            leveled = self.level_up(pet)
            self.save_pet(context.conv_key, context.sender.openid, pet)
            extra = "\n升级了！Lv." + str(pet["level"]) + "。" if leveled else ""
            await context.say(pet["name"] + "：" + random.choice(PAT_LINES) + extra)

        @ctx.command("改名", summary="给自己的宠物改名", usage="<新名字>", order=24)
        async def _rename(context) -> None:
            pet = self.my_pet(context.conv_key, context.sender.openid)
            if pet is None:
                context.fail("先 /领养 <名字>。")
            name = context.raw_args.strip()[: int(self.cfg("max_name_len", 12))]
            if not name:
                context.fail("用法：/改名 <新名字>")
            old = pet.get("name", "")
            pet["name"] = name
            self.save_pet(context.conv_key, context.sender.openid, pet)
            await context.say(old + " 改名为 " + name + " 了。")

        @ctx.command("排行", aliases=("rank",), summary="本会话等级排行", order=25)
        async def _rank(context) -> None:
            bucket = self.pets().get(context.conv_key) or {}
            if not bucket:
                context.fail("这个会话还没有人养宠物。")
            rows = sorted(
                bucket.values(),
                key=lambda item: (int(item.get("level", 1)), int(item.get("exp", 0))),
                reverse=True,
            )[:5]
            lines = ["**养成排行**"]
            for index, pet in enumerate(rows, 1):
                lines.append(
                    str(index)
                    + ". "
                    + str(pet.get("name") or "?")
                    + " Lv."
                    + str(pet.get("level", 1))
                    + "（exp "
                    + str(pet.get("exp", 0))
                    + "）"
                )
            await context.say("\n".join(lines))

    # -- 被动成长 -----------------------------------------------------------
    async def on_message(self, event: str = "", **payload: Any) -> None:
        message = payload.get("message")
        if message is None:
            return
        if str(message.text or "").startswith("/"):
            return
        pet = self.my_pet(message.conv_key, message.sender.openid)
        if pet is None:
            return
        cooldown = float(self.cfg("chat_coins_cooldown_s", 60))
        if time.time() - float(pet.get("last_chat", 0.0)) < cooldown:
            return
        pet["coins"] = int(pet.get("coins", 0)) + 1
        pet["exp"] = int(pet.get("exp", 0)) + 1
        pet["last_chat"] = time.time()
        self.level_up(pet)
        self.save_pet(message.conv_key, message.sender.openid, pet)

    # -- 定时结算 -----------------------------------------------------------
    async def decay(self) -> None:
        hunger = int(self.cfg("hunger_per_hour", 5))
        mood = int(self.cfg("mood_per_hour", 3))

        def changer(data: Dict[str, Any]) -> None:
            for bucket in data.values():
                if not isinstance(bucket, dict):
                    continue
                for pet in bucket.values():
                    if not isinstance(pet, dict):
                        continue
                    pet["hunger"] = min(100, int(pet.get("hunger", 0)) + hunger)
                    pet["mood"] = max(0, int(pet.get("mood", 0)) - mood)

        self._store.update(changer)

    # -- 展示 ---------------------------------------------------------------
    def render_pet(self, pet: Dict[str, Any], owner: str = "") -> str:
        hunger = int(pet.get("hunger", 0))
        mood = int(pet.get("mood", 0))
        note = random.choice(HUNGRY_LINES) if hunger >= 70 else "看起来很有精神。"
        return "\n".join(
            [
                "**" + str(pet.get("name") or "?") + "**  Lv." + str(pet.get("level", 1)),
                "经验 " + str(pet.get("exp", 0)) + " · 金币 " + str(pet.get("coins", 0)),
                "饥饿 " + str(hunger) + "/100 · 心情 " + str(mood) + "/100",
                note,
            ]
        )

    def render_page(self) -> Dict[str, Any]:
        data = self.pets()
        summary: List[Dict[str, Any]] = []
        for conv_key, bucket in data.items():
            pets = [
                {
                    "name": pet.get("name"),
                    "level": pet.get("level", 1),
                    "exp": pet.get("exp", 0),
                    "hunger": pet.get("hunger", 0),
                    "mood": pet.get("mood", 0),
                    "owner": pet.get("owner", ""),
                }
                for pet in bucket.values()
                if isinstance(pet, dict)
            ]
            pets.sort(key=lambda item: (item["level"], item["exp"]), reverse=True)
            summary.append({"conv": conv_key, "count": len(pets), "top": pets[:5]})
        return {"conversations": summary, "total": sum(item["count"] for item in summary)}
