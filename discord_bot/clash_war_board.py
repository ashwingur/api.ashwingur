"""
Live war board + war announcements.

Every minute this cog fetches /clashofclans/clan/<tag>/warboard once and uses it to:
  1. Keep a single message in CLASH_WAR_BOARD_CHANNEL_ID up to date (edited in place).
     The message is found again after restarts by looking for the bot's own message in the
     channel, so no state needs to be stored. Anything else posted there is deleted.
  2. Post announcements to the war channel: new war / CWL battle day, a reminder 3h before
     the end listing who still has attacks, and a summary when a war (or CWL round) ends.
     Each announcement carries a 'ref' footer so a restart doesn't post it twice.
"""
import hashlib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Set

import discord
from discord.ext import commands, tasks

import coc_http
from clash_common import CHANNEL_WAR, CHANNEL_WAR_BOARD, DEFAULT_CLAN_TAG
from clash_war_image import WAR_MAP_FILENAME, build_war_message, render_war_map, war_map_file
from clash_war import (
    WarView, embeds_signature, new_war_embed, reminder_embed, war_end_embed,
)

log = logging.getLogger("clash.warboard")

REFRESH_SECONDS = 60
FORCE_EDIT_SECONDS = 300          # re-edit at least this often so "last updated" stays honest
REMINDER_BEFORE_END = timedelta(hours=3)
ANNOUNCE_END_WITHIN = timedelta(hours=3)     # don't post summaries for wars that ended long ago
ANNOUNCE_BATTLE_START_WITHIN = timedelta(hours=1)
REF_PATTERN = re.compile(r"ref (\w+)-(\d+)")


class ClashWarBoard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.board_message: Optional[discord.Message] = None
        self.last_signature: Optional[str] = None
        self.last_edit = 0.0
        self.sent_refs: Set[str] = set()
        self.refs_seeded = False
        self.latest_board: Optional[dict] = None
        self.refresh.start()

    async def cog_unload(self):
        self.refresh.cancel()

    # ---- main loop ------------------------------------------------------------------------------

    @tasks.loop(seconds=REFRESH_SECONDS)
    async def refresh(self):
        # Never let an exception escape: tasks.loop stops for good on an unhandled error
        try:
            board = await coc_http.fetch_war_board(DEFAULT_CLAN_TAG)
        except coc_http.ApiError as e:
            log.warning("War board fetch failed: %s", e.message)
            return
        except Exception:
            log.exception("War board fetch crashed")
            return
        self.latest_board = board

        # Each step is isolated so one failure (e.g. missing permission) doesn't block the other
        try:
            await self.update_board(board)
        except Exception:
            log.exception("Failed to update war board")
        try:
            await self.send_announcements(board)
        except Exception:
            log.exception("Failed to send war announcements")

    @refresh.before_loop
    async def before_refresh(self):
        await self.bot.wait_until_ready()

    # ---- board message --------------------------------------------------------------------------

    def _board_channel(self) -> Optional[discord.TextChannel]:
        if not CHANNEL_WAR_BOARD:
            return None
        channel = self.bot.get_channel(CHANNEL_WAR_BOARD)
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _find_board_message(self, channel: discord.TextChannel) -> Optional[discord.Message]:
        """Reuse the bot's newest message in the channel; delete any older duplicates."""
        mine = [m async for m in channel.history(limit=50) if m.author == self.bot.user]
        if not mine:
            return None
        newest, *older = mine  # history() is newest first
        for message in older:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
        return newest

    async def update_board(self, board: dict):
        channel = self._board_channel()
        if channel is None:
            return

        embeds, files, png = await build_war_message(board, live=True)
        signature = embeds_signature(embeds) + (hashlib.sha256(png).hexdigest() if png else "")
        if (signature == self.last_signature and self.board_message
                and time.monotonic() - self.last_edit < FORCE_EDIT_SECONDS):
            return

        if self.board_message is None:
            self.board_message = await self._find_board_message(channel)

        try:
            if self.board_message:
                await self.board_message.edit(content=None, embeds=embeds, attachments=files)
            else:
                self.board_message = await channel.send(embeds=embeds, files=files)
        except discord.NotFound:
            # Someone deleted the board message; post a fresh one next time round
            self.board_message = None
            return
        except discord.Forbidden:
            log.error("Missing permission to post/edit in war board channel %s", CHANNEL_WAR_BOARD)
            return

        self.last_signature = signature
        self.last_edit = time.monotonic()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Keep the board channel to just the board message."""
        if not CHANNEL_WAR_BOARD or message.channel.id != CHANNEL_WAR_BOARD or message.author == self.bot.user:
            return
        try:
            await message.delete()
        except discord.HTTPException:
            pass  # No Manage Messages permission; channel permissions should prevent this anyway

    # ---- announcements --------------------------------------------------------------------------

    async def _seed_sent_refs(self, channel: discord.TextChannel):
        """Read our recent announcements so a restart doesn't repeat them."""
        async for message in channel.history(limit=100):
            if message.author != self.bot.user:
                continue
            for embed in message.embeds:
                match = REF_PATTERN.search((embed.footer.text or "") if embed.footer else "")
                if match:
                    self.sent_refs.add(match.group(0))
        self.refs_seeded = True

    async def _announce(self, channel: discord.TextChannel, embed: discord.Embed, map_view: WarView = None):
        """Send once per ref. map_view: also attach that war's map image to the embed."""
        ref = REF_PATTERN.search(embed.footer.text or "").group(0)
        if ref in self.sent_refs:
            return
        self.sent_refs.add(ref)  # mark first: a failed send shouldn't turn into a spam loop
        files = []
        png = await render_war_map(map_view) if map_view else None
        if png:
            embed.set_image(url=f"attachment://{WAR_MAP_FILENAME}")
            files = [war_map_file(png)]
        await channel.send(embed=embed, files=files)

    async def send_announcements(self, board: dict):
        channel = self.bot.get_channel(CHANNEL_WAR)
        if not isinstance(channel, discord.TextChannel):
            return
        if not self.refs_seeded:
            await self._seed_sent_refs(channel)

        now = datetime.now(timezone.utc)
        war = board.get("war")
        view = WarView(war) if war else None

        if view and view.war_id:
            # New war: during preparation, or shortly after battle starts (CWL rounds go straight
            # to battle day from our point of view, since the previous round is still running in prep)
            just_started = view.state == "inWar" and view.start and now - view.start < ANNOUNCE_BATTLE_START_WITHIN
            if view.state == "preparation" or just_started:
                await self._announce(channel, new_war_embed(board, view), map_view=view)

            if (view.state == "inWar" and view.end and timedelta(0) < view.end - now <= REMINDER_BEFORE_END
                    and view.attacks_left()):
                await self._announce(channel, reminder_embed(board, view))

        # War end summary: the shown war if it has ended, plus a CWL round that just finished
        for ended in (war, board.get("recent_ended_war")):
            if not ended or ended.get("state") != "warEnded":
                continue
            ended_view = WarView(ended)
            if ended_view.war_id and ended_view.end and timedelta(0) <= now - ended_view.end < ANNOUNCE_END_WITHIN:
                await self._announce(channel, war_end_embed(board, ended_view), map_view=ended_view)


async def setup(bot: commands.Bot):
    await bot.add_cog(ClashWarBoard(bot))
