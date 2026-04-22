import os, discord, asyncpg
import pathlib
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

class SayGoBot(commands.Bot):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.db = None
    
    async def setup_hook(self): #Botが起動する際に一度だけ呼び出されるメソッド
        await super().setup_hook()
        # データベースの接続を確立
        self.db = await asyncpg.create_pool(
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT", 5432)),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME")
        )

        #拡張機能（cogs）をロード
        cogs_dir = pathlib.Path(__file__).parent / "cogs"
        for filename in os.listdir(cogs_dir):
            if filename.endswith(".py"):
                await self.load_extension(f"cogs.{filename[:-3]}")
        
        #コマンドツリーを同期
        await self.tree.sync()

    async def close(self): #Botがシャットダウンする際に呼び出されるメソッド
        if self.db:
            await self.db.close() #データベース接続を閉じる
        await super().close()

# intentsの設定
intents = discord.Intents.default()
intents.members = True
intents.messages = True
intents.message_content = True

#Botのインスタンス化
bot = SayGoBot(
    command_prefix='!',
    intents=intents
)

@bot.event
async def on_ready():
    print(f"{bot.user}としてログインしました")
    print("参加中のサーバー：")
    for guild in bot.guilds:
        print(guild.name)

bot.run(TOKEN)
