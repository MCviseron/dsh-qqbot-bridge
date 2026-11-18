import asyncio, json, os
from viseron_qqbotpy import BotAPI, HTTPClient, TokenManager, load_env

load_env(".env")

async def main():
    token = TokenManager(os.environ["APPID"], os.environ["APPSECRET"])
    http = HTTPClient(token)
    api = BotAPI(http)
    try:
        link = await api.create_url_link("qqbridge")
        print("SHARE_LINK:", json.dumps(link, ensure_ascii=False))
    except Exception as e:
        print("create_url_link failed:", type(e).__name__, e)
    for gid in ["CCE96DDF6F462E1010E5721BBA1B6CBB"]:
        try:
            state = await api.get_group_bot_state(gid)
            print("BOT_STATE:", json.dumps(state, ensure_ascii=False))
        except Exception as e:
            print("bot_state failed:", type(e).__name__, e)
    await http.close()
    await token.close()

asyncio.run(main())
