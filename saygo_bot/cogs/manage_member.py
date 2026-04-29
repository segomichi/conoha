import discord, logging
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
from .config import ensure_config_table

logger = logging.getLogger(__name__)

class ManageMember(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.activity_check_loop.start() #Bot起動時に定期タスクを開始
    
    async def cog_load(self):
        await ensure_config_table(self.bot.db)
        await self.ensure_management_table()
        await self.ensure_warning_table()
        await self.ensure_user_activity_table()

        await super().cog_load()
        
    async def cog_unload(self):
        logger.info("ManageMember cogをアンロードします。")
        self.activity_check_loop.cancel() #Cogがアンロードされる際に定期タスクを停止
    
    @tasks.loop(hours=24)
    async def activity_check_loop(self):
        try:
            logger.info("定期タスク: activity_check を開始します。")
            await self.activity_check()
        except Exception as e:
            logger.error(f"activity_check でエラーが発生しました: {e}", exc_info=True)

    @activity_check_loop.error
    async def on_activity_check_loop_error(self, error):
        logger.error(f"activity_check_loop が予期せず停止しました: {error}", exc_info=True)
    
    @activity_check_loop.before_loop
    async def before_activity_check(self):
        await self.bot.wait_until_ready() #Botが完全に起動するまで待機
    
    async def activity_check(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # connを早期に解放し、サブメソッドとのコネクション入れ子を防ぐ
        async with self.bot.db.acquire() as conn:
            guilds = await conn.fetch("SELECT guild_id FROM configs") #管理対象のサーバーを取得
            management_records = await conn.fetch("SELECT guild_id, last_check FROM management")
        
        last_checks = {r["guild_id"]: r["last_check"] for r in management_records}

        for guild in guilds: #各サーバーごとに処理
            guild_id = guild["guild_id"] #サーバーIDを取得
            last_check = last_checks.get(guild_id)

            if last_check and (now - last_check).total_seconds() < 86400: #前回チェックから1日経過していない場合はスキップ
                continue
            
            await self.manage_warned_members(guild_id) #警告対象メンバーの管理
            await self.manage_members(guild_id) #その他のメンバー管理の処理
            
            await self.update_management_table(guild_id)

    async def ensure_management_table(self):
        async with self.bot.db.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS management (
                    guild_id BIGINT PRIMARY KEY,
                    last_check TIMESTAMP
                );
            """)

    async def ensure_warning_table(self):
        async with self.bot.db.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS warning (
                    guild_id BIGINT,
                    user_id BIGINT,
                    warning_time TIMESTAMP,
                    PRIMARY KEY (guild_id, user_id)
                );
            """)

    async def ensure_user_activity_table(self):
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
    
    async def update_management_table(self, guild_id: int):
        async with self.bot.db.acquire() as conn:
            await conn.execute("""
                INSERT INTO management (guild_id, last_check)
                VALUES ($1, NOW() AT TIME ZONE 'UTC')
                ON CONFLICT (guild_id)
                DO UPDATE SET last_check = EXCLUDED.last_check
            """, guild_id)

    async def add_warning(self, guild_id: int, user_id: int, conn=None):
        sql = """
            INSERT INTO warning (guild_id, user_id, warning_time)
            VALUES ($1, $2, NOW() AT TIME ZONE 'UTC')
            ON CONFLICT (guild_id, user_id)
            DO NOTHING
        """
        if conn is not None:
            await conn.execute(sql, guild_id, user_id)
        else:
            async with self.bot.db.acquire() as c:
                await c.execute(sql, guild_id, user_id)

    async def get_configs(self, guild_id: int):
        try:
            async with self.bot.db.acquire() as conn:
                config_record = await conn.fetchrow(
                    "SELECT * FROM configs WHERE guild_id = $1",
                    guild_id
                ) #サーバーの設定を取得
        except Exception as e:
            logger.error(f"Guild ID {guild_id}の設定取得中にエラーが発生しました: {e}", exc_info=True)
            raise
        
        if not config_record:
            return None
        
        management_channel_id = config_record["management_channel_id"]
        message_channel_id = config_record["message_channel_id"]
        warning_grace_period = config_record["warning_grace_period"]
        kick_grace_period = config_record["kick_grace_period"]
        
        if management_channel_id is None or message_channel_id is None or warning_grace_period is None or kick_grace_period is None:
            logger.warning(f"Guild ID {guild_id}の設定が不完全です: {config_record}")
            return None
        
        return management_channel_id, message_channel_id, warning_grace_period, kick_grace_period

    async def manage_warned_members(self, guild_id: int): #警告対象ユーザーの管理
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        configs = await self.get_configs(guild_id)
        if not configs:
            logger.warning(f"Guild ID {guild_id}の設定が不完全なため、警告対象ユーザーの管理をスキップします。")
            return
        management_channel_id, message_channel_id, warning_grace_period, kick_grace_period = configs
        management_channel = self.bot.get_channel(management_channel_id) #管理チャンネルを取得
        if not management_channel: 
            logger.warning(f"Guild ID {guild_id}の管理チャンネルが見つかりません: チャンネルID {management_channel_id}")
            return
        message_channel = self.bot.get_channel(message_channel_id) #メッセージ送信チャンネルを取得
        if not message_channel:
            logger.warning(f"Guild ID {guild_id}のメッセージ送信チャンネルが見つかりません: チャンネルID {message_channel_id}")
            return

        async with self.bot.db.acquire() as conn:
            warned_members = await conn.fetch("""
                SELECT user_id, warning_time FROM warning
                WHERE guild_id = $1
            """, guild_id) #警告対象ユーザーの情報取得
            
            for warned_member in warned_members: #警告対象ユーザーごとに処理
                warned_member_id = warned_member["user_id"] #警告対象ユーザーIDを取得
                guild = self.bot.get_guild(guild_id) #サーバーを取得
                if not guild:
                    await conn.execute("DELETE FROM warning WHERE guild_id = $1", guild_id)
                    await conn.execute("DELETE FROM user_activity WHERE guild_id = $1", guild_id)
                    await conn.execute("DELETE FROM management WHERE guild_id = $1", guild_id)
                    await conn.execute("DELETE FROM configs WHERE guild_id = $1", guild_id)
                    logger.warning(f"Guild ID {guild_id}が見つからないため、関連するすべてのレコードを削除しました。")
                    break
                try:
                    member = await guild.fetch_member(warned_member_id)
                except discord.NotFound:
                    logger.warning(f"Guild ID {guild_id}のメンバーID {warned_member_id}が見つかりません。警告を削除します。")
                    try:
                        await management_channel.send(f"ユーザーID {warned_member_id}はサーバーに存在しないため、警告を削除しました。") #管理チャンネルに警告解除メッセージを送信
                    except (discord.Forbidden, discord.HTTPException) as e:
                        logger.error(f"Guild ID {guild_id}の管理チャンネルへのメッセージ送信に失敗しました: {e}", exc_info=True)
                    await conn.execute("""
                        DELETE FROM warning
                        WHERE guild_id = $1 AND user_id = $2
                    """, guild_id, warned_member_id)
                    continue
                except (discord.Forbidden, discord.HTTPException) as e:
                    logger.error(f"Guild ID {guild_id}のメンバーID {warned_member_id}の取得に失敗しました: {e}", exc_info=True)
                    continue

                warning_date = warned_member["warning_time"] #警告日時を取得
                kick_date = warning_date + timedelta(days=kick_grace_period) #警告日にキック猶予を足したキック日を計算
                last_active_record = await conn.fetchrow("""
                    SELECT last_active FROM user_activity
                    WHERE guild_id = $1 AND user_id = $2
                """, guild_id, warned_member_id) #ユーザーの最終活動日時を取得
                last_active = last_active_record["last_active"] if last_active_record else None
            
                if last_active and warning_date < last_active: #ユーザーが警告後に活動している場合
                    await conn.execute("""
                        DELETE FROM warning
                        WHERE guild_id = $1 AND user_id = $2
                    """, guild_id, warned_member_id) #警告テーブルからユーザーを削除
                    logger.info(f"Guild ID {guild_id}のメンバーID {warned_member_id}の警告を解除しました。")
                    try:
                        await message_channel.send(f"{member.mention}さんは活動が確認されたため、警告が解除されました。") #メッセージ送信チャンネルに警告解除メッセージを送信
                    except (discord.Forbidden, discord.HTTPException) as e:
                        logger.error(f"Guild ID {guild_id}の管理チャンネルへのメッセージ送信に失敗しました: {e}", exc_info=True)
                else: #ユーザーが警告後に活動していない場合
                    if kick_date < now: #キック日を過ぎている場合はキック対象
                        if member:
                            try:
                                await member.kick(reason="非アクティブのため") #ユーザーをキック
                            except (discord.Forbidden, discord.HTTPException) as e:
                                logger.error(f"Guild ID {guild_id}のメンバーID {warned_member_id}のキックに失敗しました: {e}", exc_info=True)
                                continue
                        await conn.execute("""
                            DELETE FROM warning
                            WHERE guild_id = $1 AND user_id = $2
                        """, guild_id, warned_member_id) #警告テーブルからユーザーを削除
                        await conn.execute("""
                            UPDATE user_activity
                            SET is_kicked = TRUE
                            WHERE guild_id = $1 AND user_id = $2
                        """, guild_id, warned_member_id) #ユーザーの活動テーブルのis_kickedをTrueに更新
                        try:
                            await message_channel.send(f"{member.mention}さんはキックされました。") #メッセージ送信チャンネルにキックメッセージを送信
                        except (discord.Forbidden, discord.HTTPException) as e:
                            logger.error(f"Guild ID {guild_id}の管理チャンネルへのメッセージ送信に失敗しました: {e}", exc_info=True)
                    else: #キック日を過ぎていない場合は動作なし
                        pass

    async def manage_members(self, guild_id: int):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        configs = await self.get_configs(guild_id)
        if not configs:
            logger.warning(f"Guild ID {guild_id}の設定が不完全なため、警告対象ユーザーの管理をスキップします。")
            return
        management_channel_id, message_channel_id, warning_grace_period, kick_grace_period = configs
        management_channel = self.bot.get_channel(management_channel_id) # 管理チャンネルを取得
        if not management_channel:
            logger.warning(f"Guild ID {guild_id}の管理チャンネルが見つかりません: チャンネルID {management_channel_id}")
            return
        message_channel = self.bot.get_channel(message_channel_id) # メッセージチャンネルを取得
        if not message_channel:
            logger.warning(f"Guild ID {guild_id}のメッセージチャンネルが見つかりません: チャンネルID {message_channel_id}")
            return

        # サーバーを取得
        guild = self.bot.get_guild(guild_id)
        if not guild:
            async with self.bot.db.acquire() as conn:
                await conn.execute("DELETE FROM warning WHERE guild_id = $1", guild_id)
                await conn.execute("DELETE FROM user_activity WHERE guild_id = $1", guild_id)
                await conn.execute("DELETE FROM management WHERE guild_id = $1", guild_id)
                await conn.execute("DELETE FROM configs WHERE guild_id = $1", guild_id)
                logger.warning(f"Guild ID {guild_id}が見つからないため、関連するすべてのレコードを削除しました。")
                try:
                    await management_channel.send(f"Guild ID {guild_id}が見つからないため、関連するすべてのレコードを削除しました。") #管理チャンネルにメッセージを送信
                except (discord.Forbidden, discord.HTTPException) as e:
                    logger.error(f"Guild ID {guild_id}の管理チャンネルへのメッセージ送信に失敗しました: {e}", exc_info=True)
            return

        # メンバー管理処理
        try:
            members = guild.fetch_members(limit=None) #全メンバーを取得する
            async with self.bot.db.acquire() as conn:
                async for member in members:
                    if member.bot: #Botは管理対象外
                        continue

                #ユーザーの最終活動日時を取得
                    last_active_record = await conn.fetchrow("""
                        SELECT last_active FROM user_activity
                        WHERE guild_id = $1 AND user_id = $2
                    """, guild_id, member.id)

                    if not last_active_record: #ユーザーが活動テーブルに存在しない場合は追加
                        await conn.execute("""
                            INSERT INTO user_activity (guild_id, user_id, last_active, activity_type, is_kicked)
                            VALUES ($1, $2, NOW() AT TIME ZONE 'UTC', 'initial_check', FALSE)
                            ON CONFLICT (guild_id, user_id)
                            DO UPDATE SET last_active = NOW() AT TIME ZONE 'UTC', activity_type = 'initial_check', is_kicked = FALSE
                        """, guild_id, member.id)
                        continue
                    else: #ユーザーの最終活動日時を取得
                        last_active = last_active_record["last_active"]

                    if (now - last_active).total_seconds() > warning_grace_period * 86400: #警告日数を過ぎている場合
                        warning = await conn.fetchrow("""
                            SELECT * FROM warning
                            WHERE guild_id = $1 AND user_id = $2
                        """, guild_id, member.id) #ユーザーが警告対象かどうかを取得
                        if warning: #ユーザーがすでに警告対象の場合はスキップ
                            logger.info(f"Guild ID {guild_id}のメンバー{member.name}を確認しました。")
                            continue
                        await self.add_warning(guild_id, member.id, conn) #警告テーブルにユーザーを追加
                        try:
                            await message_channel.send(f"{member.mention}さんは{warning_grace_period}日間活動がありませんでした。{kick_grace_period}日後まで活動がない場合キックされます。") #メッセージチャンネルに警告メッセージを送信
                        except (discord.Forbidden, discord.HTTPException) as e:
                            logger.error(f"Guild ID {guild_id}のメッセージチャンネルへのメッセージ送信に失敗しました: {e}", exc_info=True)
                        logger.info(f"Guild ID {guild_id}のメンバー{member.name}に警告を追加しました。")
                    else: #警告日数を過ぎていない場合
                        logger.info(f"Guild ID {guild_id}のメンバー{member.name}を確認しました。")
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error(f"Guild ID {guild_id}のメンバー取得に失敗しました: {e}", exc_info=True)
            return
        
async def setup(bot):
    await bot.add_cog(ManageMember(bot))
    logger.info("ManageMember cogを読み込みました。")