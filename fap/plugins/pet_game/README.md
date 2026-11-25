# pet_game — 群内养成游戏

框架原生插件，用来验证「不依赖 DSH 也能纯靠框架跑起来」。

## 玩法

| 命令 | 说明 |
|---|---|
| `/领养 <名字>` | 每个会话每人一只 |
| `/宠物` | 看面板（等级/经验/金币/饥饿/心情） |
| `/喂食` | 花 5 金币：饥饿 −35、心情 +6、经验 +8（30s 冷却） |
| `/摸摸` | 心情 +10、经验 +3（20s 冷却） |
| `/改名 <新名字>` | 改名 |
| `/排行` | 本会话等级前 5 |

## 成长规则

- 每发一条**非命令**消息：金币 +1、经验 +1（60s 冷却）
- 每小时结算：饥饿 +5、心情 −3
- 等级 = 1 + 经验 // 50

## 配置（config.json → plugins.pet_game）

```json
{
  "feed_cooldown_s": 30,
  "pat_cooldown_s": 20,
  "chat_coins_cooldown_s": 60,
  "decay_interval_s": 3600,
  "hunger_per_hour": 5,
  "mood_per_hour": 3,
  "exp_per_level": 50,
  "max_name_len": 12
}
```

## 数据

`session/state/pet_game/pets.json`：`{conv: {openid: pet}}`，原子写，重启不丢。
GUI 版本自动出现「养成游戏」页面（`/api/pages/pets`）。
