import discord, logging
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

async def ensure_config_table(db_pool):
    async with db_pool.acquire() as connection:
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS configs (
                guild_id BIGINT PRIMARY KEY,
                prefix TEXT NOT NULL DEFAULT '!',
                management_channel_id BIGINT,
                message_channel_id BIGINT,
                warning_grace_period INTEGER NOT NULL DEFAULT 30,
                kick_grace_period INTEGER NOT NULL DEFAULT 10
            )
        """)

class Config(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await ensure_config_table(self.bot.db)
        return await super().cog_load()
    
    async def set_manage_channel(self, guild_id: int, channel_id: int):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO configs (guild_id, management_channel_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id)
                DO UPDATE SET management_channel_id = EXCLUDED.management_channel_id
                """,
                guild_id,
                channel_id,
            )
            logger.info(f"管理用チャンネルを設定しました: ギルドID {guild_id}, チャンネルID {channel_id}")

    async def set_message_channel(self, guild_id: int, channel_id: int):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO configs (guild_id, message_channel_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id)
                DO UPDATE SET message_channel_id = EXCLUDED.message_channel_id
                """,
                guild_id,
                channel_id,
            )
            logger.info(f"メッセージ送信チャンネルを設定しました: ギルドID {guild_id}, チャンネルID {channel_id}")

    async def set_warning_grace_period(self, guild_id: int, warning_grace_period: int):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO configs (guild_id, warning_grace_period)
                VALUES ($1, $2)
                ON CONFLICT (guild_id)
                DO UPDATE SET warning_grace_period = EXCLUDED.warning_grace_period
                """,
                guild_id,
                warning_grace_period,
            )
            logger.info(f"警告までの日数を設定しました: ギルドID {guild_id}, 日数 {warning_grace_period}")

    async def set_kick_grace_period(self, guild_id: int, kick_grace_period: int):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO configs (guild_id, kick_grace_period)
                VALUES ($1, $2)
                ON CONFLICT (guild_id)
                DO UPDATE SET kick_grace_period = EXCLUDED.kick_grace_period
                """,
                guild_id,
                kick_grace_period,
            )
            logger.info(f"警告からキックまでの日数を設定しました: ギルドID {guild_id}, 日数 {kick_grace_period}")

    @app_commands.command(name="set_manage_ch", description="管理用チャンネルを設定します")
    @app_commands.describe(channel="管理用テキストチャンネル")
    @app_commands.checks.has_permissions(administrator=True)
    async def manage_ch(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await self.set_manage_channel(interaction.guild_id, channel.id)
        await interaction.response.send_message(f"管理用チャンネルを{channel.mention}に設定しました。", ephemeral=True)
    
    @manage_ch.error
    async def manage_ch_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("このコマンドは管理者のみ使用できます。", ephemeral=True)

    @app_commands.command(name="set_message_ch", description="メッセージ送信チャンネルを設定します")
    @app_commands.describe(channel="メッセージ送信テキストチャンネル")
    @app_commands.checks.has_permissions(administrator=True)
    async def message_ch(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await self.set_message_channel(interaction.guild_id, channel.id)
        await interaction.response.send_message(f"メッセージ送信チャンネルを{channel.mention}に設定しました。", ephemeral=True)
    
    @message_ch.error
    async def message_ch_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("このコマンドは管理者のみ使用できます。", ephemeral=True)
    
    @app_commands.command(name="set_warning_grace_period", description="警告までの日数を設定します")
    @app_commands.describe(days="警告までの猶予期間（日数）")
    @app_commands.checks.has_permissions(administrator=True)
    async def warning_grace_period(self, interaction: discord.Interaction, days: int):
        if days <= 0:
            await interaction.response.send_message("日数は1以上を指定してください。", ephemeral=True)
            return
        await self.set_warning_grace_period(interaction.guild_id, days)
        await interaction.response.send_message(f"警告までの日数を{days}日に設定しました。", ephemeral=True)
    
    @warning_grace_period.error
    async def warning_grace_period_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("このコマンドは管理者のみ使用できます。", ephemeral=True)
    
    @app_commands.command(name="set_kick_grace_period", description="警告からキックまでの日数を設定します")
    @app_commands.describe(days="キックまでの日数")
    @app_commands.checks.has_permissions(administrator=True)
    async def kick_grace_period(self, interaction: discord.Interaction, days: int):
        if days <= 0:
            await interaction.response.send_message("日数は1以上を指定してください。", ephemeral=True)
            return
        await self.set_kick_grace_period(interaction.guild_id, days)
        await interaction.response.send_message(f"警告からキックまでの日数を{days}日に設定しました。", ephemeral=True)

    @kick_grace_period.error
    async def kick_grace_period_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("このコマンドは管理者のみ使用できます。", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Config(bot))
    logger.info("Config cogを読み込みました。")
