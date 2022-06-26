from __future__ import annotations
import asyncio

from contextlib import suppress
from inspect import getsource, getsourcefile
from io import StringIO
from typing import Any, Dict, Literal, Optional, Union
from urllib import parse
from re import compile

import discord
from discord.ext.commands import Context, command, group, guild_only, has_permissions

from utils import Cog, GuildModel, humanize_time, TextChannelID

PULL_HASH_REGEX = compile(r'(?:(?P<org>(?:[A-Za-z]|\d|-)+)/)?(?P<repo>(?:[A-Za-z]|\d|-)+)?(?:##)(?P<index>[0-9]+)')

UPVOTE = discord.PartialEmoji(name="upvote", id=881521766231584848)
DOWNVOTE = discord.PartialEmoji(name="downvote", id=904068725475508274)
OTHER_REACTION = {
    "INVALID": {"emoji": "\N{WARNING SIGN}", "color": 0xFFFFE0},
    "ABUSE": {"emoji": "\N{DOUBLE EXCLAMATION MARK}", "color": 0xFFA500},
    "INCOMPLETE": {"emoji": "\N{WHITE QUESTION MARK ORNAMENT}", "color": 0xFFFFFF},
    "DECLINE": {"emoji": "\N{CROSS MARK}", "color": 0xFF0000},
    "APPROVED": {"emoji": "\N{WHITE HEAVY CHECK MARK}", "color": 0x90EE90},
}


class General(Cog):
    """A cog for general commands."""
    def __init__(self, bot):
        super().__init__(bot)
        self.message: Dict[int, discord.Message] = {}
        # *thinks* should be using LRU cache st., only thing scare me is that the dictionary will keep growing

    async def suggestions_channel(
        self, guild: discord.Guild
    ) -> Optional[discord.TextChannel]:
        guild_data, _ = await GuildModel.get_or_create(id=guild.id)
        if guild_data.suggestions:
            return guild.get_channel(guild_data.suggestions)

    async def get_or_fetch_message(
        self, message_id: int, *, fetch: bool=False, partial: bool=False, cache: bool=True, guild: discord.Guild
    ) -> Union[discord.Message, discord.PartialMessage]:
        """Fastest way to get the messages from cache or fetch them from the API."""
        try:
            return self.message[message_id]
            # try except is better than if-else, in this case
        except KeyError:
            pass

        if cache:
            for msg in self.bot.cached_messages:
                if msg.id == message_id:
                    self.message[msg.id] = msg
                    return msg

        await self.bot.wait_until_ready()

        channel = await self.suggestions_channel(guild)
        if channel is None:
            return

        if partial:
            return channel.get_partial_message(message_id)

        if fetch:
            msg = await channel.fetch_message(message_id)
            if msg:
                self.message[msg.id] = msg
                return msg

    @group(name="suggestions", aliases=["suggest"], invoke_without_command=True)
    @guild_only()
    async def suggest(self, ctx: Context, *, suggestion: str):
        """Make a suggestion for the server. This will be sent to the channel set by the server managers."""
        if ctx.invoked_subcommand is None:
            if not (channel := await self.suggestions_channel(ctx.guild)):
                return await ctx.send("This server doesn't have a suggestions channel.")

            await ctx.message.delete(delay=0)
            msg = await channel.send(
                embed=discord.Embed(
                    description=suggestion,
                    colour=discord.Color.blurple(),
                )
                .set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
                .set_footer(text=f"ID: {ctx.author.id}")
            )
            await msg.add_reaction(UPVOTE)
            await msg.add_reaction(DOWNVOTE)
            self.message[msg.id] = msg

    @suggest.command(name="set", aliases=["channel", "setchannel"])
    @has_permissions(manage_guild=True)  # I prefer the permission should be lowered to manage_channels
    @guild_only()
    async def suggestions(self, ctx: Context, channel_id: TextChannelID):
        """Set the channel for suggestions. Use `0` as channel_id to disable suggestions.
        Members can use `p.suggest` to make a suggestion."""
        await GuildModel.update("suggestions", ctx.guild.id, channel_id)
        if channel_id == 0:
            return await ctx.send("Suggestions been disabled for this server.")
        await ctx.send(
            f"The suggestions channel for this server is now <#{channel_id}>."
        )

    @suggest.command()
    async def suggest_delete(self, ctx: Context, message_id: int):
        """Delete the suggestion you suggest. Member with manage_messages permissions can delete any suggestion"""
        msg = await self.get_or_fetch_message(message_id, guild=ctx.guild)
        if msg.author is not ctx.guild.me:
            # to make sure that, its bot's message
            return await ctx.send("Invalid message.")

        if not msg:
            return await ctx.send("Message not found. Probably deleted.")
        
        if not msg.embeds:
            # mods suppressed the embeds
            # it is sure that message alaways be having embeds
            return await ctx.send("This message is not a suggestion.")

        if ctx.author.guild_permissions.manage_messages:
            await msg.delete(delay=0)
            return await ctx.send("Message deleted.")

        if int(msg.embeds[0].footer.text.split(":")[1]) != ctx.author.id:
            # it is also sure that message footer will be having text like "ID: <id>"
            return await ctx.send("You are not the author of this suggestion.")

        await msg.delete(delay=0)
        await ctx.send("Message deleted.")
        if msg.id in self.message:
            del self.message[msg.id]
            await asyncio.sleep(0)

    @suggest.command(name="note", aliases=["remark"])
    @has_permissions(manage_messages=True)
    async def suggest_note(self, ctx: Context, message_id: int, *, note: str):
        """Add a note to the suggestion."""
        msg = await self.get_or_fetch_message(message_id, guild=ctx.guild)
        if msg.author is not ctx.guild.me:
            # to make sure that, its bot's message
            return await ctx.send("Invalid message.")

        if not msg:
            return await ctx.send("Message not found. Probably deleted.")
        
        if not msg.embeds:
            # mods suppressed the embeds
            # it is sure that message alaways be having embeds
            return await ctx.send("This message is not a suggestion.")

        embed = msg.embeds[0]
        embed.add_field(name="Remark", value=note,)
        await msg.edit(embed=embed)
        await ctx.send("Note added.")

    @suggest.command(name="flag")
    async def suggest_flag(self, ctx: Context, message_id: int, flag: str):
        """Flag the suggestion.
        
        Avalibale Flags :-
        - INVALID
        - ABUSE
        - INCOMPLETE
        - DECLINE
        - APPROVED
        """
        # This is very similar to github issue flags
        msg = await self.get_or_fetch_message(message_id, guild=ctx.guild)
        if msg.author is not ctx.guild.me:
            # to make sure that, its bot's message
            return await ctx.send("Invalid message.")
        flag = flag.upper()
        try:
            payload: Dict[str, Union[int, str]] = OTHER_REACTION[flag]
        except KeyError:
            return await ctx.send("Invalid flag.")
        
        embed = msg.embeds[0]
        embed.color = payload["color"]

        content = f"Flagged: {flag} | {payload['emoji']}"
        await msg.edit(content=content, embed=embed)
        await msg.add_reaction(payload["emoji"])
        await ctx.send("Flag added.")

    @Cog.listener(name="on_raw_message_delete")
    async def suggest_msg_delete(self, payload) -> None:
        if payload.message_id in self.message:
            del self.message[payload.message_id]

    @command()
    async def ping(self, ctx: Context):
        """Get the websocket latency of the bot."""
        await ctx.send(f"Pong! `{self.bot.latency*1000:.2f}ms`")

    @command(aliases=["time"])
    async def timestamp(self, ctx: Context, style: Literal["f", "F", "d", "D", "t", "T", "R"]=None):
        """Get the current timestamp.
        Valid styles are `f|F|d|D|t|T|R`."""
        _time = ctx.message.created_at
        # `time`/`time()` is builtin function/module, so we should not use it
        # might raised errors, in future
        await ctx.send(
            f"{discord.utils.format_dt(_time, style=style)} (`{_time.timestamp()}`)"
        )

    @command()
    async def search(self, ctx: Context, *, query):
        """Get a search url from Bing, DuckDuckGo and Google."""
        param = parse.urlencode({"q": query})
        await ctx.send(
            f"Use the buttons below to search for `{query}` on the internet.",
            view=discord.ui.View(
                discord.ui.Button(
                    label="Google", url=f"https://www.google.com/search?{param}"
                ),
                discord.ui.Button(
                    label="Bing", url=f"https://www.bing.com/search?{param}"
                ),
                discord.ui.Button(
                    label="DuckDuckGo", url=f"https://www.duckduckgo.com/?{param}"
                ),
            ),
        )

    @command()
    async def afk(self, ctx: Context, *, message="_No reason specified._"):
        """Become AFK."""
        await ctx.send(f"Set your AFK: {message}")
        self.bot.cache["afk"][ctx.author.id] = message
        if not ctx.author.display_name.startswith("[AFK] "):
            with suppress(discord.HTTPException):
                await ctx.author.edit(nick=f"[AFK] {ctx.author.display_name}")

    @Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        # AFK
        if message.author.id in self.bot.cache["afk"].keys():
            del self.bot.cache["afk"][message.author.id]
            await message.add_reaction("\U0001f44b")
            if message.author.nick and message.author.nick.startswith("[AFK] "):
                with suppress(discord.HTTPException):
                    await message.author.edit(nick=message.author.nick[6:])
        for mention in message.mentions:
            if msg := self.bot.cache["afk"].get(mention.id):
                await message.channel.send(f"{mention.display_name} is AFK: {msg}")

        # Pull requests and issues
        def make_link(index, org=None, repo=None):
            org = org or "Pycord-Development"
            repo = repo or "pycord"
            return f"https://github.com/{org}/{repo}/pull/{index}"

        links = list(set([make_link(index, org, repo) for org, repo, index in PULL_HASH_REGEX.findall(message.content)]))[:15]
        if len(links) > 2:
            links = [f"<{link}>" for link in links]
        if links:
            await message.reply("\n".join(links))

    @command(aliases=["src"])
    async def source(self, ctx: Context, *, command: str = None):
        """See the source code of the bot."""
        if not command:
            return await ctx.send("https://github.com/Dorukyum/Pycord-Manager")
        c = self.bot.get_command(command) or self.bot.get_application_command(command)
        if not c:
            return await ctx.send(f"Command {command} was not found")
        callback = self.bot.help_command.__class__ if command == "help" else c.callback
        src = getsource(callback)
        buf = StringIO(src)
        file = discord.File(buf, getsourcefile(callback))
        await ctx.send(file=file)

    @discord.user_command(name="View Account Age")
    async def account_age(self, ctx, member: discord.Member):
        """View the age of an account."""
        age = discord.utils.utcnow() - member.created_at
        await ctx.respond(
            f"{member.mention} is {humanize_time(age)} old.", ephemeral=True
        )


def setup(bot):
    bot.add_cog(General(bot))
