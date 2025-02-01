import os
from dotenv import load_dotenv, find_dotenv
from datetime import datetime
import discord
from discord.ext import commands
from discord import app_commands
from discord import Interaction
import wavelink

""" Set up environment variables """
# Load default environment variables
load_dotenv(find_dotenv())
# Override with development environment variables
load_dotenv(".env.dev", override=True)
# Retrieve the environment variables
LAVALINK_URL = os.getenv("LAVALINK_URL")
LAVALINK_PW = os.getenv("LAVALINK_PW")
BOT_TOKEN = os.getenv("BOT_TOKEN")

""" Set up the bot """
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!',intents=intents)

@bot.event
async def on_ready():
    print(f'Logged on as {bot.user}')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="Music"))
    synced = await bot.tree.sync()
    print(f'Synced {len(synced)} commands')
    node = [wavelink.Node(uri=LAVALINK_URL, password=LAVALINK_PW)]
    await wavelink.Pool.connect(nodes=node, client=bot)

@bot.event
async def on_wavelink_node_ready(payload: wavelink.NodeReadyEventPayload):
    print(f"Node {payload.node.identifier} is ready!")

""" Bot Commands """
@bot.tree.command(name="play", description="Play the song")
async def play(interaction: Interaction, url: str=None):
    vClient = interaction.guild.voice_client
    await interaction.response.defer()

    if (url is None):
        if (vClient is None):
            await interaction.followup.send("I am not in a voice channel.")
            return
        if (not vClient.paused):
            await interaction.followup.send("Song is already playing.")
            return
        elif(vClient.paused):
            await vClient.pause(False)
            await interaction.followup.send("Song resumed.")
            return
        else:
            await interaction.followup.send("No song is playing.")
            return

    vChannel = interaction.user.voice.channel

    if (vClient is None): # check if bot is in vc
        try:
            vClient = await vChannel.connect(cls=wavelink.Player)
            await interaction.guild.change_voice_state(channel=vChannel, self_deaf=True)
        except AttributeError:
            await interaction.followup.send("Please join a voice channel playing.")
            return

    if (vClient.channel is not vChannel): # check if the bot is in the same voice channel as user
        vClient = await vClient.move_to(vChannel)

    try:
        tracks = await wavelink.Playable.search(url)
        if isinstance(tracks, wavelink.Playlist):
            added = await vClient.queue.put_wait(tracks)
            await interaction.followup.send(f"Added {added} songs from **`{tracks.name}`** to the queue.")
        else:
            track = tracks[0]
            await vClient.queue.put_wait(track)
            await interaction.followup.send(f"Added `{track}` to the queue.")
    except wavelink.LavalinkLoadException as e:
        print(f"{e}")
        await interaction.followup.send("Failed to load track.")

    if not vClient.playing:
        track = vClient.queue.get()
        vClient.autoplay = wavelink.AutoPlayMode.partial
        vClient.inactive_timeout = 0
        await vClient.play(track, add_history=False)


@bot.tree.command(name="pause", description="Pause the song")
async def pause(interaction: Interaction):
    vClient = interaction.guild.voice_client
    await interaction.response.defer()

    if (vClient is None):
        await interaction.followup.send("I am not in a voice channel.")
        return
    if (vClient.paused):
        await interaction.followup.send("Song is already paused.")
        return
    elif (not vClient.paused):
        await vClient.pause(True)
        await interaction.followup.send("Song paused.")
        return
    else:
        await interaction.followup.send("No song is playing.")

@bot.tree.command(name="queue", description="Display the queue")
async def queue(interaction: Interaction):
    vClient = interaction.guild.voice_client
    await interaction.response.defer()

    if (vClient is None):
        await interaction.followup.send("I am not in a voice channel.")
        return
    if (vClient.queue.is_empty):
        await interaction.followup.send("Queue is empty.")
        return
    else:
        queue_list = ""
        for i, track in enumerate(vClient.queue[:10]):
            queue_list += f"{i+1}. [{track}]({track.uri}) - `{datetime.fromtimestamp(track.length/1000).strftime('%-Mm%-Ss')}`\n"
        embed = discord.Embed(title="Queue", color=0x22a7f2)
        embed.add_field(name="", value=queue_list, inline=False)
        await interaction.followup.send(embed=embed)

@bot.tree.command(name="insert", description="Insert song to the front of the queue")
async def insert(interaction: Interaction, url: str):
    vClient = interaction.guild.voice_client
    await interaction.response.defer()

    if (vClient is None):
        await interaction.followup.send("I am not in a voice channel.")
        return

    try:
        tracks = await wavelink.Playable.search(url)
        if isinstance(tracks, wavelink.Playlist):
            for index, track in enumerate(tracks):
                vClient.queue.put_at(index, track)
            await interaction.followup.send(f"Inserted {len(tracks)} songs from **`{tracks.name}`** to the front of the queue.")
        else:
            track = tracks[0]
            vClient.queue.put_at(0, track)
            await interaction.followup.send(f"Inserted `{track}` to the queue.")
    except wavelink.LavalinkLoadException as e:
        print(f"{e}")
        await interaction.followup.send("Failed to load track.")

@bot.tree.command(name="nowplaying", description="Display the current song")
async def nowplaying(interaction: Interaction):
    vClient = interaction.guild.voice_client
    await interaction.response.defer()

    if (vClient is None):
        await interaction.followup.send("I am not in a voice channel.")
        return
    if (not vClient.playing):
        await interaction.followup.send("No song is playing.")
        return
    else:
        track = vClient.current
        embed = discord.Embed(title="Now Playing", color=0x22a7f2)
        embed.add_field(name="", value=f"[{track.title}]({track.uri})", inline=False)
        embed.add_field(name="", value=f"`{datetime.fromtimestamp(vClient.position/1000).strftime('%-Mm%-Ss')}/{datetime.fromtimestamp(track.length/1000).strftime('%-Mm%-Ss')}`", inline=False)
        embed.set_thumbnail(url=track.artwork)
        await interaction.followup.send(embed=embed)

@bot.tree.command(name="skip", description="Skip the song")
@app_commands.describe(to="Skip to this index in queue")
async def skip(interaction: Interaction, to: int=1):
    vClient = interaction.guild.voice_client
    await interaction.response.defer()

    if (vClient is None):
        await interaction.followup.send("I am not in a voice channel.")
        return
    if (vClient.playing):
        for _ in range(to-1):
            vClient.queue.delete(0)
        await vClient.skip()
        await interaction.followup.send(f"Skipped {to} songs.")
        return
    else:
        await interaction.followup.send("No song is playing.")

@bot.tree.command(name="shuffle", description="Shuffle the queue")
async def shuffle(interaction: Interaction):
    vClient = interaction.guild.voice_client
    await interaction.response.defer()

    if (vClient is None):
        await interaction.followup.send("I am not in a voice channel.")
        return
    else:
        vClient.queue.shuffle()
        await interaction.followup.send("Queue shuffled.")

@bot.tree.command(name="loop", description="Toggle loop mode")
@app_commands.describe(option="Loop the current song or the entire queue")
@app_commands.choices(option=[
    app_commands.Choice(name="Song", value="song"),
    app_commands.Choice(name="Queue", value="queue")
])
async def loop(interaction: Interaction, option: str):
    vClient = interaction.guild.voice_client
    await interaction.response.defer()

    if vClient is None:
        await interaction.followup.send("I am not in a voice channel.")
        return

    match option:
        case None:
            if vClient.queue.mode == wavelink.QueueMode.normal:
                await interaction.followup.send("Please specify an loop option.")
            else:
                vClient.queue.mode = wavelink.QueueMode.normal
                await interaction.followup.send("Loop mode disabled.")
        case "song":
            vClient.queue.mode = wavelink.QueueMode.loop
            await interaction.followup.send(f"Song loop enabled.")
        case "queue":
            vClient.queue.mode = wavelink.QueueMode.loop_all
            await interaction.followup.send(f"Queue loop enabled.")

@bot.tree.command(name="remove", description="Remove song from queue")
async def remove(interaction: Interaction, index: int):
    vClient = interaction.guild.voice_client
    await interaction.response.defer()

    if (vClient is None):
        await interaction.followup.send("I am not in a voice channel.")
        return
    if (vClient.queue.is_empty):
        await interaction.followup.send("Queue is empty.")
        return
    if (index < 1 or index > len(vClient.queue)):
        await interaction.followup.send("Invalid index.")
        return
    else:
        vClient.queue.delete(index-1)
        await interaction.followup.send(f"Removed song `{index}` from the queue.")

@bot.tree.command(name="clear", description="Clear the queue")
async def clear(interaction: Interaction):
    vClient = interaction.guild.voice_client
    await interaction.response.defer()

    if (vClient is None):
        await interaction.followup.send("I am not in a voice channel.")
        return
    else:
        vClient.queue.clear()
        await interaction.followup.send("Queue cleared.")

@bot.tree.command(name="stop", description="Terminate the player")
async def stop(interaction: Interaction):
    vClient = interaction.guild.voice_client
    await interaction.response.defer()

    if (vClient is None):
        await interaction.followup.send("No active player.")
        return
    else:
        await vClient.disconnect()
        await interaction.followup.send("Player Terminated.")

@bot.tree.command(name="playlist", description="Display updated playlist")
async def playlist(interaction: Interaction, url: str, added: int=None):
    channel = interaction.channel
    await interaction.response.defer(ephemeral=True)

    try:
        track = await wavelink.Playable.search(url)
        if isinstance(track, wavelink.Playlist):
            # delete old playlist message
            async for message in channel.history(limit=25):
                if message.embeds:
                    for embed in message.embeds:
                        if embed.url == url:
                            await message.delete()

            embed = discord.Embed(title=f"{track.name}", url=url, color=0x22a7f2)
            embed.set_thumbnail(url=track.tracks[0].artwork)
            if added:
                embed.add_field(name="New", value=f"`{added}`", inline=True)
            embed.add_field(name="Command", value=f"`/play url:{url}`", inline=True)
            await channel.send(embed=embed)
            await interaction.followup.send(f"Playlist updated.")
        else:
            await interaction.followup.send(f"Please provide a valid playlist URL.")
    except wavelink.LavalinkLoadException as e:
        print(f"{e}")
        await interaction.followup.send("Failed to load track.")

bot.run(BOT_TOKEN)