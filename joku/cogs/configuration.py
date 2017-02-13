"""
Configuration cog.
"""
import argparse
import shlex

import discord
from discord.ext import commands
from discord.ext.commands import MemberConverter, BadArgument, TextChannelConverter

from joku.bot import Jokusoramame, Context
from joku.cogs._common import Cog
from joku.checks import has_permissions
from joku.utils import get_role


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # raise the exception instead of printing it
        raise Exception(message)


class Config(Cog):
    @commands.command(pass_context=True)
    @has_permissions(manage_server=True, manage_messages=True)
    async def inviscop(self, ctx: Context, *, status: str = None):
        """
        Manages the Invisible cop

        The Invisible Cop automatically deletes any messages of users with Invisible on.
        """
        if status is None:
            # Check the status.
            setting = await ctx.bot.database.get_setting(ctx.message.guild, "dndcop", {})
            if setting.get("status") == 1:
                await ctx.channel.send("Invis Cop is currently **on.**")
            else:
                await ctx.channel.send("Invis Cop is currently **off.**")
        else:
            if status.lower() == "on":
                await ctx.bot.database.set_setting(ctx.message.guild, "dndcop", status=1)
                await ctx.channel.send(":heavy_check_mark: Turned Invis Cop on.")
                return
            elif status.lower() == "off":
                await ctx.bot.database.set_setting(ctx.message.guild, "dndcop", status=0)
                await ctx.channel.send(":heavy_check_mark: Turned Invis Cop off.")
                return
            else:
                await ctx.channel.send(":x: No.")

    @commands.group(pass_context=True, invoke_without_command=True)
    @has_permissions(manage_server=True, manage_roles=True)
    async def rolestate(self, ctx: Context, *, status: str = None):
        """
        Manages rolestate.

        This will automatically save roles for users who have left the server.
        """
        if status is None:
            # Check the status.
            setting = await ctx.bot.database.get_setting(ctx.message.guild, "rolestate", {})
            if setting.get("status") == 1:
                await ctx.channel.send("Rolestate is currently **on.**")
            else:
                await ctx.channel.send("Rolestate is currently **off.**")
        else:
            if status.lower() == "on":
                await ctx.bot.database.set_setting(ctx.message.guild, "rolestate", status=1)
                await ctx.channel.send(":heavy_check_mark: Turned Rolestate on.")
                return
            elif status.lower() == "off":
                await ctx.bot.database.set_setting(ctx.message.guild, "rolestate", status=0)
                await ctx.channel.send(":heavy_check_mark: Turned Rolestate off.")
                return
            else:
                await ctx.channel.send(":x: No.")

    @rolestate.command()
    async def view(self, ctx: Context, *, user_id: int = None):
        """
        Views the current rolestate of a member.
        """
        if user_id is None:
            user_id = ctx.author.id

        rolestate = await self.bot.database.get_rolestate_for_id(ctx.guild.id, user_id)
        user = await ctx.bot.get_user_info(user_id)

        em = discord.Embed(title="Rolestate viewer")

        if rolestate is None:
            em.description = "**No rolestate found for this user here.**"
        else:
            em.description = "This shows the most recent rolestate for a user ID. This is **not accurate** if they " \
                             "haven't left before, or are still in the guild."

            em.add_field(name="Nick", value=rolestate.nick, inline=False)
            roles = ", ".join([get_role(ctx.guild, r_id).mention for r_id in rolestate.roles])
            em.add_field(name="Roles", value=roles, inline=False)
        em.set_thumbnail(url=user.avatar_url)
        em.set_footer(text="Rolestate for guild {}".format(ctx.guild.name))

        await ctx.send(embed=em)

    @commands.command(pass_context=True)
    @has_permissions(manage_server=True, manage_channels=True)
    async def ignore(self, ctx: Context, *, args: str = None):
        """
        Adds an ignore rule to the bot.
        This allows ignoring of commands or levelling in this channel or server.

        Settings are persistent - i.e your settings will not disappear when the bot leaves the server.
        """
        # Construct the program name.
        p_name = ctx.prefix + ctx.invoked_with
        parser = ArgumentParser(prog=p_name, add_help=False, formatter_class=argparse.RawTextHelpFormatter)
        parser.add_argument("-a", "--add",
                            help="Adds an ignore action.",
                            action="store_true")
        parser.add_argument("-r", "--remove",
                            help="Removes an ignore action.",
                            action="store_true")
        parser.add_argument("--type",
                            help="Defines what type of ignore to add. Valid choices are: 'commands' 'levels'")
        parser.add_argument("--target",
                            help="Defines the target of this action. You can mention a channel or a user.")

        if args is None:
            # Print the help text.
            h = parser.format_help()
            await ctx.channel.send("```{}```".format(h))
            return

        try:
            args = parser.parse_args(shlex.split(args))
        except Exception as e:
            await ctx.channel.send(":x: {}".format(' '.join(e.args)))
            return

        if args.type not in ['commands', 'levels']:
            await ctx.channel.send(":x: That is not a valid type.")
            return

        # Try to convert the target.
        try:
            converted = MemberConverter(ctx, args.target).convert()
        except BadArgument:
            try:
                converted = TextChannelConverter(ctx, args.target).convert()
            except BadArgument:
                await ctx.channel.send(":x: Target was invalid or could not be found.")
                return

        # If it's a remove, try and remove it.
        if args.remove:
            # Try and get the ignore rule that is currently in the database.
            # This means filtering by name and type.
            query = await r.table("settings") \
                .get_all(ctx.message.guild.id, index="server_id") \
                .filter({
                "name": "ignore", "target": converted.id,
                "type": args.type
            }) \
                .run(ctx.bot.database.connection)

            got = await ctx.bot.database.to_list(query)
            if not got:
                await ctx.channel.send(":x: This item does not have an ignore rule on it of that type.")
                return

            # Remove the rule.
            await r.table("settings").get(got[0]["id"]).delete().run(ctx.bot.database.connection)
            await ctx.channel.send(":heavy_check_mark: Removed ignore rule.")
            return
        elif args.add:
            # Check if the rule already exists.
            query = await r.table("settings") \
                .get_all(ctx.message.guild.id, index="server_id") \
                .filter({
                "name": "ignore", "target": converted.id,
                "type": args.type
            }) \
                .run(ctx.bot.database.connection)

            got = await self.bot.database.to_list(query)
            if got:
                await ctx.channel.send(":x: This item already has a rule with that target.")
                return

            # Add the rule.
            built_dict = {
                "server_id": ctx.message.guild.id, "name": "ignore",
                "target": converted.id, "type": args.type
            }

            result = await r.table("settings").insert(built_dict).run(self.bot.database.connection)
            await ctx.channel.send(":heavy_check_mark: Added ignore rule.")


def setup(bot):
    bot.add_cog(Config(bot))
