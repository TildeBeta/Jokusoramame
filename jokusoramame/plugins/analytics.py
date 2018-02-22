"""
Analytical work.
"""
import entropy
import string
import threading
from io import BytesIO
from typing import Awaitable, Dict

import asks
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
import tabulate
from asks.response_objects import Response
from curio.thread import async_thread
from curious import Embed, EventContext, Guild, Member, Message, event
from curious.commands import Context, Plugin
from curious.commands.decorators import autoplugin, ratelimit
from curious.commands.ratelimit import BucketNamer
from matplotlib.axes import Axes


@autoplugin
class Analytics(Plugin):
    def __init__(self, client):
        super().__init__(client)

        self._plot_lock = threading.Lock()

    @event("message_create")
    async def add_to_analytics(self, ctx: EventContext, message: Message):
        await ctx.bot.redis.add_message(message)

    async def command_entropy(self, ctx: Context, *, message: str = None):
        """
        Gets the entropy of a sentence.
        """
        if message is None:
            # assume a file
            try:
                f = ctx.message.attachments[0]
            except IndexError:
                return await ctx.channel.send(":x: You must provide a message or attach a file.")

            async with ctx.channel.typing:
                r: Response = await asks.get(f.url)
            message = r.content
        else:
            message = message.encode('utf-8', errors='ignore')

        en = entropy.shannon_entropy(message)
        await ctx.channel.messages.send(f"Entropy: {en}")

    async def command_analyse(self, ctx: Context):
        """
        Analyses various things about users or guilds.
        """
        return await self.command_analyse_member(ctx, victim=ctx.author)

    async def toggle(self, ctx: Context, *, guild_id: int):
        """
        Toggles analytics for the specified guild ID.
        """
        if ctx.author.id != 214796473689178133:
            return await ctx.channel.messages.send(":x: Analytics are expensive, so only the owner"
                                                   " can enable them.")

        guild = ctx.bot.guilds.get(guild_id)
        if guild is None:
            return await ctx.channel.send(":x: This guild does not exist.")

        enabled = await ctx.bot.redis.toggle_analytics(guild)
        await ctx.channel.messages.send(f":heavy_check_mark: Analytics status: {enabled}")

    async def analyse_member(self, member: Member) -> dict:
        """
        Analyses a member's messages, returning a dictionary of statistics.
        """
        messages = await self.client.redis.get_messages(member.user)
        if len(messages) == 0:
            return {}

        # do some processing
        total_entropy = 0
        total_length = 0

        # count capitals vs lowercase
        capitals = 0

        # track number of used messages
        used_messages = 0

        for message in messages:
            content = message["c"]
            if not content:
                continue

            used_messages += 1

            total_entropy += entropy.shannon_entropy(content)
            total_length += len(content)
            capitals += sum(char in string.ascii_uppercase for char in content)

        # calculate averages
        avg_entropy = total_entropy / len(messages)
        avg_message_length = sum(len(m["c"]) for m in messages) / len(messages)

        return {
            "message_count": used_messages,
            "message_total": len(messages),
            "total_entropy": total_entropy,
            "total_length": total_length,
            "average_entropy": avg_entropy,
            "average_length": avg_message_length,
            "capitals": capitals
        }

    async def command_analyse_member(self, ctx: Context, *, victim: Member = None):
        """
        Analyses a member.
        """
        if victim is None:
            victim = ctx.author

        async with ctx.channel.typing:
            processed = await self.analyse_member(victim)
            if not processed:
                return await ctx.channel.messages.send(":x: There are no analytics available for "
                                                       "this user.")

        messages = processed['message_total']
        used_messages = processed['message_count']
        avg_entropy = processed['average_entropy']
        avg_length = processed['average_length']
        total_length = processed['total_length']
        capitals = processed['capitals']
        em = Embed()
        em.title = "GHCQ Analysis Department"
        em.description = f"Analysis for {victim.user.username} used {used_messages} " \
                         f"messages. Skipped {messages - used_messages} messages."
        em.colour = victim.colour
        em.set_thumbnail(url=str(victim.user.avatar_url))
        em.add_field(name="Avg. Entropy", value=format(avg_entropy, '.4f'))
        em.add_field(name="Avg. message length",
                     value=f"{format(avg_length, '.2f')} chars")
        em.add_field(name="Total message length", value=f"{total_length} chars")
        em.add_field(name="% capital letters",
                     value=format((capitals / total_length) * 100, '.2f'))

        await ctx.channel.messages.send(embed=em)

    async def get_combined_member_data(self, guild: Guild) -> Dict[Member, dict]:
        """
        Gets the combined member data for a guild.
        """
        member_data = {member: await self.analyse_member(member)
                       for member in guild.members.values() if not member.user.bot}
        member_data = {member: data for (member, data) in member_data.items()
                       if data}

        return member_data

    async def command_analyse_server(self, ctx: Context):
        """
        Analyses the current server.
        """
        async with ctx.channel.typing:
            member_data = await self.get_combined_member_data(ctx.guild)

        def sum_data(key: str) -> int:
            return sum(x[key] for x in member_data.values())

        message_count = sum_data('message_count')
        message_total = sum_data('message_total')
        average_entropy = sum_data('average_entropy') / len(member_data)
        average_length = sum_data('average_length') / len(member_data)
        total_length = sum_data('total_length')
        capitals = sum_data('capitals')

        em = Embed()
        em.title = "GHCQ Analysis Department"
        em.description = f"Analysis for {ctx.guild.name} used {message_count} messages " \
                         f"({message_total - message_count} messages skipped) " \
                         f"from {len(member_data)} members"
        em.add_field(name="Avg. entropy",
                     value=format(average_entropy, '.4f'))
        em.add_field(name="Avg. message length",
                     value=f"{format(average_length, '.2f')} chars")
        em.add_field(name="Total message length", value=f"{total_length} chars")
        em.add_field(name="% capital letters",
                     value=format((capitals / total_length) * 100, '.2f'))
        em.set_thumbnail(url=ctx.guild.icon_url)
        em.colour = ctx.guild.owner.colour

        await ctx.channel.messages.send(embed=em)

    async def get_sorted_items(self, guild: Guild, sort_key: str = "average_entropy"):
        """
        Gets a list of sorted member analytics data.
        """
        member_data = await self.get_combined_member_data(guild)
        sorted_data = sorted(list(member_data.items()),
                             key=lambda i: i[1][sort_key], reverse=True)

        return sorted_data

    async def command_server_top(self, ctx: Context, *, sort_by: str = "entropy"):
        """
        Shows the top 10 people in the server by a field, where field is one of
        `[entropy, length, capitals]`.
        """

        sort_key = "average_entropy"
        if sort_by == "length":
            sort_key = "average_length"
        elif sort_by == "capitals":
            sort_key = "capitals"

        # sort by key, get the top 10
        async with ctx.channel.typing:
            member_data = (await self.get_sorted_items(ctx.guild, sort_key))[:10]

        headers = ["POS", "Name", "Entropy", "Avg. Length", "Capitals"]
        rows = []
        for i, (member, stats) in enumerate(member_data):
            # we're gonna add to this list to build the list of rows
            current_row = [i + 1]
            name = member.user.name.encode("ascii", errors="replace") \
                .decode("ascii", errors="replace")
            current_row.append(name)

            current_row.append(format(stats['average_entropy'], '.3f'))
            current_row.append(format(stats['average_length'], '.2f') + ' chars')
            capitals = (stats['capitals'] / stats['total_length']) * 100
            current_row.append(format(capitals, '.2f') + '%')
            rows.append(current_row)

        table = tabulate.tabulate(rows, headers, tablefmt='orgtbl')
        await ctx.channel.messages.send(f"```\n{table}```")

    @ratelimit(limit=1, time=60, bucket_namer=BucketNamer.GUILD)
    async def command_server_distribution(self, ctx: Context, *, item: str = "entropy"):
        """
        Plots a distribution plot for the specified item.
        """

        item_key = "average_entropy"
        if item == "length":
            item_key = "average_length"
        elif item == "capitals":
            item_key = "capitals"

        @async_thread()
        def plotter(member_data) -> Awaitable[BytesIO]:
            """
            The main plotter function.
            """
            with ctx.bot._plot_lock:
                array = np.asarray([m[item_key] for m in member_data.values()])

                axes: Axes = sns.kdeplot(array, bw=0.3)
                axes.set_xlabel(item.capitalize())
                axes.set_ylabel("Count")
                axes.set_xbound(0, np.max(array))
                plt.title("Distribution curve")
                plt.tight_layout()
                sns.despine()

                # write to the main buffer
                buf = BytesIO()
                plt.savefig(buf, format='png')
                buf.seek(0)

                # cleanup after ourselves
                plt.clf()
                plt.cla()

                return buf

        async with ctx.channel.typing:
            fetched_data = await self.get_combined_member_data(ctx.guild)

            if ctx.bot._plot_lock.locked():
                await ctx.channel.send("Waiting for plot lock...")

            buf = await plotter(fetched_data)  # wait for the plotter to lock and plot

        await ctx.channel.messages.upload(buf.read(), filename="plot.png")
