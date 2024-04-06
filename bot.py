from datetime import datetime
import discord
from discord.ext import commands
from discord import Interaction
import wavelink

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!',intents=intents)

@bot.event
async def on_ready():
    print(f'Logged on as {bot.user}')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="Music"))
    synced = await bot.tree.sync()
    print(f'Synced {len(synced)} commands')
    node = wavelink.Node(uri="http://35.197.99.182:2333", password="a16101y")
    await wavelink.Pool.connect(nodes=[node], client=bot)

@bot.event
async def on_wavelink_node_ready(payload: wavelink.NodeReadyEventPayload):
    print(f"Node {payload.node.identifier} is ready!")

@bot.tree.command(name="play", description="Play the song")
async def play(interaction: Interaction, url: str=None):
    await interaction.response.defer()
    vClient = interaction.guild.voice_client

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

    if (interaction.user.voice is None): # check if user is in vc
        await interaction.followup.send("You are not in a voice channel.")
        return
    vChannel = interaction.user.voice.channel

    if (vClient is None): # check if bot is in vc
        vClient = await vChannel.connect(cls=wavelink.Player)
        await interaction.guild.change_voice_state(channel=vChannel, self_deaf=True)

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

        if not vClient.playing:
            track = vClient.queue.get()
            await vClient.play(track)
            vClient.autoplay = wavelink.AutoPlayMode.partial
    except wavelink.LavalinkLoadException as e:
        print(f"{e}")
        await interaction.followup.send("Failed to load track.")


@bot.tree.command(name="pause", description="Pause the song")
async def pause(interaction: Interaction):
    await interaction.response.defer()
    vClient = interaction.guild.voice_client

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
    await interaction.response.defer()
    vClient = interaction.guild.voice_client

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

@bot.tree.command(name="nowplaying", description="Display the current song")
async def nowplaying(interaction: Interaction):
    await interaction.response.defer()
    vClient = interaction.guild.voice_client

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
        await interaction.followup.send(embed=embed)

@bot.tree.command(name="skip", description="Skip the song")
async def skip(interaction: Interaction):
    await interaction.response.defer()
    vClient = interaction.guild.voice_client

    if (vClient is None):
        await interaction.followup.send("I am not in a voice channel.")
        return
    if (vClient.playing):
        await vClient.skip()
        await interaction.followup.send("Song skipped.")
        return
    else:
        await interaction.followup.send("No song is playing.")

@bot.tree.command(name="shuffle", description="Shuffle the queue")
async def shuffle(interaction: Interaction):
    await interaction.response.defer()
    vClient = interaction.guild.voice_client

    if (vClient is None):
        await interaction.followup.send("I am not in a voice channel.")
        return
    else:
        vClient.queue.shuffle()
        await interaction.followup.send("Queue shuffled.")

@bot.tree.command(name="clear", description="Clear the queue")
async def clear(interaction: Interaction):
    await interaction.response.defer()
    vClient = interaction.guild.voice_client

    if (vClient is None):
        await interaction.followup.send("I am not in a voice channel.")
        return
    else:
        vClient.queue.clear()
        await interaction.followup.send("Queue cleared.")

@bot.tree.command(name="playlist", description="Display updated playlist")
async def playlist(interaction: Interaction, url: str):
    await interaction.response.defer()

    try:
        playlist = await wavelink.Playable.search(url)
        if isinstance(playlist, wavelink.Playlist):
            embed = discord.Embed(title=f"{playlist.name}", url=playlist.url, color=0x22a7f2)
            embed.add_field(name="", value=f"{playlist.url}", inline=False)
            embed.add_field(name="", value=f"{playlist.artwork}", inline=False)
            embed.set_thumbnail(url=playlist.artwork)
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(f"Please provide a valid playlist URL.")
    except wavelink.LavalinkLoadException as e:
        print(f"{e}")
        await interaction.followup.send("Failed to load track.")

@bot.tree.command(name="stop", description="Terminate the player")
async def stop(interaction: Interaction):
    await interaction.response.defer()
    vClient = interaction.guild.voice_client

    if (vClient is None):
        await interaction.followup.send("No active player.")
        return
    else:
        await vClient.disconnect()
        await interaction.followup.send("Player Terminated.")

    await wavelink.Pool.close() 

bot.run("NzcxNjU1Njk5MDQ1Njc5MTI0.GtxmLZ.ZdtrBkyjpPBjK1qkxEOlSBvNy37XbdKlR6fTrI")