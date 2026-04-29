import logging
from discord.ext import commands

logger = logging.getLogger(__name__)

class MonitorActivity(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self.ensure_activity_table()
        await super().cog_load()
    
    async def ensure_activity_table(self):
        async with self.bot.db.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_activity (
                    guild_id BIGINT,
                    user_id BIGINT,
                    last_active TIMESTAMP,
                    activity_type TEXT,
                    is_kicked BOOLEAN DEFAULT FALSE,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
    
    async def update_user_activity(self, guild_id: int, user_id: int, activity_type: str):
        async with self.bot.db.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_activity (guild_id, user_id, last_active, activity_type, is_kicked)
                VALUES ($1, $2, NOW() AT TIME ZONE 'UTC', $3, FALSE)
                ON CONFLICT (guild_id, user_id)
                DO UPDATE SET last_active = NOW() AT TIME ZONE 'UTC', activity_type = EXCLUDED.activity_type, is_kicked = FALSE
            """, guild_id, user_id, activity_type)
    
    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot:
            return
        await self.update_user_activity(member.guild.id, member.id, "join")
    
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None:
            return
        await self.update_user_activity(message.guild.id, message.author.id, "message")
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        if before.channel is None and after.channel is not None:
            await self.update_user_activity(member.guild.id, member.id, "VC_join")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.guild_id is None: #DMのリアクションは無視
            return
        if payload.user_id == self.bot.user.id:
            return
        await self.update_user_activity(payload.guild_id, payload.user_id, "reaction_add")

async def setup(bot):
    await bot.add_cog(MonitorActivity(bot))
    logger.info("MonitorActivity cogを読み込みました。")