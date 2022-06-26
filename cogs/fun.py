from re import findall

import discord
from discord.ext.commands import Context, command, group, cooldown, BucketType

from utils import Cog


class Fun(Cog):
    """A cog for fun commands."""

    @command()
    async def how_many(self, ctx: Context, *, text):
        """Shows the amount of people that has the supplied text in their display name."""
        text = text.strip().lower()
        if text == "asked":
            return await ctx.send("Nobody.")
        count = sum(text in member.display_name.lower() for member in ctx.guild.members)
        await ctx.send(
            f"{count} people have `{text}` (any case) in their display name."
        )

    @group(invoke_without_command=True)
    @cooldown(1, 60, BucketType.channel)
    async def poll(self, ctx: Context, question: str, *choices: str):
        """Create a poll."""
        to_emoji = lambda key: chr(0x1F1E6 + key)
        body = "\n".join(f"{to_emoji(i)}: {choice}" for i, choice in enumerate(choices[:5]))

        message = await ctx.send(
            embed=discord.Embed(
                title=f"Poll: {question}",
                description=body,
                color=discord.Color.brand_red(),
            ).set_author(
                name=ctx.author.display_name, icon_url=ctx.author.display_avatar
            )
        )
        for i, _ in enumerate(choices[:5]):
            await message.add_reaction(to_emoji(i))

    @poll.command()
    async def yesno(self, ctx: Context, *, question):
        """Create a poll with the options being yes or no."""
        message = await ctx.send(
            embed=discord.Embed(
                title="Yes/No Poll",
                description=question,
                color=discord.Color.brand_green(),
            ).set_author(
                name=ctx.author.display_name, icon_url=ctx.author.display_avatar
            )
        )
        await message.add_reaction("✅")
        await message.add_reaction("❎")


def setup(bot):
    bot.add_cog(Fun(bot))
