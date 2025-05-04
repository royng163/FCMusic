import os
from dotenv import load_dotenv, find_dotenv
from datetime import datetime
import discord
from discord.ext import commands
from discord import app_commands
from discord import Interaction
import lavalink

""" Environment variables setup """
# Load default environment variables
load_dotenv(find_dotenv())
# Override with development environment variables
load_dotenv(".env.dev", override=True)
# Retrieve the environment variables
LAVALINK_HOST = os.getenv("LAVALINK_HOST")
LAVALINK_PORT = os.getenv("LAVALINK_PORT")
LAVALINK_PW = os.getenv("LAVALINK_PW")
BOT_TOKEN = os.getenv("BOT_TOKEN")

""" Bot and Lavalink setup """
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!',intents=intents)

# Lavalink Client Setup
class LavalinkClient(discord.VoiceProtocol):
    def __init__(self, client: discord.Client, channel: discord.abc.Connectable):
        self.client = client
        self.channel = channel
        self.guild_id = channel.guild.id
        self._destroyed = False

        # Ensure Lavalink client exists on the bot object
        if not hasattr(self.client, 'lavalink'):
            self.client.lavalink = lavalink.Client(client.user.id)
            self.client.lavalink.add_node(
                host=LAVALINK_HOST,
                port=LAVALINK_PORT,
                password=LAVALINK_PW,
                region="hk",
                name='default-node'
            )
        # Shorthand for lavalink client
        self.lavalink: lavalink.Client = self.client.lavalink

    async def on_voice_server_update(self, data):
        lavalink_data = {'t': 'VOICE_SERVER_UPDATE', 'd': data}
        await self.lavalink.voice_update_handler(lavalink_data)

    async def on_voice_state_update(self, data):
        channel_id = data['channel_id']

        # If the bot disconnects, handle cleanup
        if not channel_id:
            await self._destroy()
            return

        # Update channel if the bot is moved
        self.channel = self.client.get_channel(int(channel_id))

        lavalink_data = {'t': 'VOICE_STATE_UPDATE', 'd': data}
        await self.lavalink.voice_update_handler(lavalink_data)

    async def connect(self, *, timeout: float, reconnect: bool, self_deaf: bool = False, self_mute: bool = False) -> None:
        """ Connect the bot to the voice channel and create a player_manager if needed. """
        # Ensure player instance exists.
        self.lavalink.player_manager.create(guild_id=self.channel.guild.id)
        # Use discord.py's state change to establish connection.
        await self.channel.guild.change_voice_state(channel=self.channel, self_mute=self_mute, self_deaf=self_deaf)

    async def disconnect(self, *, force: bool = False) -> None:
        """ Handles the disconnect. Cleans up running player and leaves the voice client. """
        player = self.lavalink.player_manager.get(self.channel.guild.id)

        # If the player is not connected, do nothing.
        if not force and not player.is_connected:
            return

        # Use discord.py's state change to disconnect.
        await self.channel.guild.change_voice_state(channel=None)

        # Update player state and cleanup resources.
        player.channel_id = None
        await self._destroy()

    async def _destroy(self):
        """ Internal cleanup method. """
        if self._destroyed:
            return
        self._destroyed = True

        self.cleanup() # discord.py internal cleanup

        try:
            await self.lavalink.player_manager.destroy(self.guild_id)
        except lavalink.errors.ClientError:
            pass

# Bot event listeners
@bot.event
async def on_ready():
    print(f'Logged on as {bot.user}')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="Music"))

    # Initialize Lavalink client
    if not hasattr(bot, 'lavalink'):
        bot.lavalink = lavalink.Client(bot.user.id)
        bot.lavalink.add_node(
            host=LAVALINK_HOST,
            port=LAVALINK_PORT,
            password=LAVALINK_PW,
            region="hk",
            name='default-node'
        )

    # Add event listeners (hooks) to the Lavalink client instance
    bot.lavalink.add_event_hooks(bot)

    synced = await bot.tree.sync()
    print(f'Synced {len(synced)} commands')

# Lavalink event listeners
@lavalink.listener(lavalink.events.NodeReadyEvent)
async def on_node_ready(event: lavalink.events.NodeReadyEvent):
    print(f"Lavalink Node '{event.node.name}' is ready! Available: {event.node.available}")

@lavalink.listener(lavalink.events.NodeDisconnectedEvent)
async def on_node_disconnect(event: lavalink.events.NodeDisconnectedEvent):
    print(f"Lavalink Node '{event.node.name}' disconnected! Reason: {event.reason}, Code: {event.code}")

# Helper function to create a player and ensure the bot is connected to a voice channel
async def ensure_voice(interaction: Interaction, user_should_connect: bool, bot_should_connect: bool = True):
    player = bot.lavalink.player_manager.create(interaction.guild.id)

    if (not interaction.user.voice or not interaction.user.voice.channel) and user_should_connect:
        raise app_commands.AppCommandError('Please join a voice channel first.')

    if not user_should_connect:
        return player

    voice_channel = interaction.user.voice.channel

    if not interaction.guild.voice_client:
        if bot_should_connect:
            raise app_commands.AppCommandError("I am not connected to a voice channel.")

        permissions = voice_channel.permissions_for(interaction.guild.me)
        if not permissions.connect or not permissions.speak:
            raise app_commands.AppCommandError('I need the `CONNECT` and `SPEAK` permissions.')

        if voice_channel.user_limit > 0 and len(voice_channel.members) >= voice_channel.user_limit \
           and not interaction.guild.me.guild_permissions.move_members:
            raise app_commands.AppCommandError('Your voice channel is full!')

    elif interaction.guild.voice_client.channel.id != voice_channel.id:
        raise app_commands.AppCommandError('You need to be in my voice channel.')

    return player

""" Bot Commands """
@bot.tree.command(name="play", description="Play the song or resume playback")
@app_commands.describe(query="URL or search query")
async def play(interaction: Interaction, query: str=None):
    await interaction.response.defer()

    try:

        # --- Resume Logic ---
        if query is None:
            player = await ensure_voice(interaction, user_should_connect=True)
            if not player.paused:
                await interaction.followup.send("Song is already playing.")
                return
            elif player.paused:
                await player.set_pause(False)
                await interaction.followup.send("Song resumed.")
                return
            else:
                await interaction.followup.send("No song is playing.")
                return
            
        player = await ensure_voice(interaction, user_should_connect=True, bot_should_connect=False)

        # --- Play Logic ---
        if not interaction.guild.voice_client:
            await interaction.user.voice.channel.connect(cls=LavalinkClient, self_deaf=True)
        # Search for the tracks using the provided query
        result = await player.node.get_tracks(query)
        match(result.load_type):
            # The result is a playlist
            case lavalink.LoadType.PLAYLIST:
                tracks = result.tracks
                for track in tracks:
                    player.add(requester=interaction.user.id, track=track)
                await interaction.followup.send(f"Added {len(tracks)} songs from **`{result.playlist_info.name}`** to the queue.")
            # The result is a song
            case lavalink.LoadType.TRACK:
                track = result.tracks[0]
                player.add(requester=interaction.user.id, track=track)
                await interaction.followup.send(f"Added `{track.title}` to the queue.")
            # Empty/Error result
            case _:
                await interaction.followup.send("No results found.")
                return

        # If nothing is playing, start playback
        if not player.is_playing:
            await player.play()
    
    except app_commands.AppCommandError as e:
        await interaction.followup.send(str(e))
    except Exception as e:
        print(f"Error in play command: {e}")
        await interaction.followup.send("An error occurred while trying to play the track.")


@bot.tree.command(name="pause", description="Pause the song")
async def pause(interaction: Interaction):
    await interaction.response.defer()

    try:
        player = await ensure_voice(interaction, user_should_connect=True)

        if player.paused:
            await interaction.followup.send("Song is already paused.")
            return
        elif not player.paused:
            await player.set_pause(True)
            await interaction.followup.send("Song paused.")
            return
        else:
            await interaction.followup.send("No song is playing.")
    except app_commands.AppCommandError as e:
        await interaction.followup.send(str(e))
    except Exception as e:
        print(f"Error in pause command: {e}")
        await interaction.followup.send("An error occurred.")

@bot.tree.command(name="queue", description="Display the queue")
async def queue(interaction: Interaction):
    await interaction.response.defer()
    try:
        player = await ensure_voice(interaction, user_should_connect=True)

        if not player.queue:
            await interaction.followup.send("The queue is empty.")
            return
        else:
            queue_list = ""
            for i, track in enumerate(player.queue[:10]):
                duration = lavalink.utils.format_time(track.duration)
                if duration.startswith("00:"):
                    duration = duration[3:]
                queue_list += f"{i+1}. [{track.title}]({track.uri}) - `{duration}`\n"
            embed = discord.Embed(title="Queue", color=0x22a7f2)
            embed.add_field(name="", value=queue_list, inline=False)
            await interaction.followup.send(embed=embed)
    except app_commands.AppCommandError as e:
        await interaction.followup.send(str(e))
    except Exception as e:
        print(f"Error in queue command: {e}")
        await interaction.followup.send("An error occurred while trying to display the queue.")

@bot.tree.command(name="insert", description="Insert song or playlist to the front of the queue")
@app_commands.describe(query="URL or search query")
async def insert(interaction: Interaction, query: str):
    await interaction.response.defer()

    try:
        player = await ensure_voice(interaction, user_should_connect=True)

        # Search for the tracks using the provided query
        result = await player.node.get_tracks(query)
        match(result.load_type):
            # The result is a playlist
            case lavalink.LoadType.PLAYLIST:
                tracks = result.tracks
                # Insert the tracks at the front of the queue
                for track in reversed(tracks):
                    player.queue.insert(0, track)
                await interaction.followup.send(f"Inserted {len(tracks)} songs from **`{result.playlist_info.name}`** to the front of the queue.")
            # The result is a song
            case lavalink.LoadType.TRACK:
                track = result.tracks[0]
                player.queue.insert(0, track)
                await interaction.followup.send(f"Inserted `{track.title}` to the queue.")
            # Empty/Error result
            case _:
                await interaction.followup.send("No results found.")
                return

    except app_commands.AppCommandError as e:
        await interaction.followup.send(str(e))
    except Exception as e:
        print(f"Error in insert command: {e}")
        await interaction.followup.send("An error occurred while trying to insert the track.")

@bot.tree.command(name="nowplaying", description="Display the current song")
async def nowplaying(interaction: Interaction):
    await interaction.response.defer()

    try:
        player = await ensure_voice(interaction, user_should_connect=True)

        if not player.is_playing or player.current is None:
            await interaction.followup.send("No song is playing.")
            return
        else:
            track = player.current
            position = lavalink.utils.format_time(player.position)
            duration = lavalink.utils.format_time(track.duration)
            if position.startswith("00:"):
                position = position[3:]
            if duration.startswith("00:"):
                duration = duration[3:]
            embed = discord.Embed(title="Now Playing", color=0x22a7f2)
            embed.add_field(name="", value=f"[{track.title}]({track.uri})", inline=False)
            embed.add_field(name="", value=f"`{position}/{duration}`", inline=False)
            embed.set_thumbnail(url=track.artwork_url)
            user = bot.get_user(track.requester)
            if user:
                embed.set_footer(text=f"Requested by: {user.display_name}", icon_url=user.display_avatar.url)
            await interaction.followup.send(embed=embed)
    except app_commands.AppCommandError as e:
        await interaction.followup.send(str(e))
    except Exception as e:
        print(f"Error in nowplaying command: {e}")
        await interaction.followup.send("An error occurred while trying to display the current song.")

@bot.tree.command(name="skip", description="Skip the song")
@app_commands.describe(to="Skip to this index in queue")
async def skip(interaction: Interaction, to: int=1):
    await interaction.response.defer()

    try:
        player = await ensure_voice(interaction, user_should_connect=True)
        
        if not player.is_playing:
            await interaction.followup.send("No song is playing.")
            return

        if to < 1:
            await interaction.followup.send("Please enter a valid number of songs to skip (1 or more).")
            return

        if to == 1:
            await interaction.followup.send(f"Skipping **`{player.current.title}`** that is currently playing.")
            await player.skip()
        else:
            # Remove tracks from the front of the queue
            for _ in range(to-1):
                # Ensure queue is not empty before popping
                if player.queue:
                    player.queue.pop(0)
                else:
                    # Stop if queue becomes empty
                    break
            # Also skip the current track
            await player.skip()
            await interaction.followup.send(f"Skipped {to} songs.")
    except app_commands.AppCommandError as e:
        await interaction.followup.send(str(e))
    except Exception as e:
        print(f"Error in skip command: {e}")
        await interaction.followup.send("An error occurred while trying to skip the song.")

@bot.tree.command(name="shuffle", description="Toggle queue shuffle")
async def shuffle(interaction: Interaction):
    await interaction.response.defer()

    try:
        player = await ensure_voice(interaction, user_should_connect=True)
        
        # Toggle shuffle state
        player.shuffle = not player.shuffle

        if player.shuffle:
            await interaction.followup.send("Queue shuffle enabled.")
        else:
            # Only stops randomizing future plays
            await interaction.followup.send("Queue shuffle disabled.")
    except app_commands.AppCommandError as e:
        await interaction.followup.send(str(e))
    except Exception as e:
        print(f"Error in shuffle command: {e}")
        await interaction.followup.send("An error occurred while trying to shuffle the queue.")

@bot.tree.command(name="loop", description="Toggle loop mode")
@app_commands.describe(option="Loop the current song or the entire queue")
@app_commands.choices(option=[
    app_commands.Choice(name="Loop song", value="song"),
    app_commands.Choice(name="Loop queue", value="queue")
])
async def loop(interaction: Interaction, option: str="normal"):
    await interaction.response.defer()

    try:
        player = await ensure_voice(interaction, user_should_connect=True)

        match option:
            case "normal":
                if player.loop == 0:
                    await interaction.followup.send("Please specify an loop option.")
                else:
                    player.loop = 0
                    await interaction.followup.send("Loop mode disabled.")
            case "song":
                player.loop = 1
                await interaction.followup.send(f"Song loop enabled.")
            case "queue":
                player.loop = 2
                await interaction.followup.send(f"Queue loop enabled.")

    except app_commands.AppCommandError as e:
        await interaction.followup.send(str(e))
    except Exception as e:
        print(f"Error in loop command: {e}")
        await interaction.followup.send("An error occurred while trying to set loop mode.")

@bot.tree.command(name="remove", description="Remove song from queue")
async def remove(interaction: Interaction, index: int):
    await interaction.response.defer()

    try:
        player = await ensure_voice(interaction, user_should_connect=True)

        if not player.queue:
            await interaction.followup.send("Queue is empty.")
            return
        if index < 1 or index > len(player.queue):
            await interaction.followup.send("Invalid index.")
            return
        else:
            removed_track = player.queue.pop(index-1)
            await interaction.followup.send(f"Removed **`{removed_track.title}`** (at index {index}) from the queue.")
    except app_commands.AppCommandError as e:
        await interaction.followup.send(str(e))
    except Exception as e:
        print(f"Error in remove command: {e}")
        await interaction.followup.send("An error occurred while trying to remove the track.")

@bot.tree.command(name="clear", description="Clear the queue")
async def clear(interaction: Interaction):
    await interaction.response.defer()

    try:
        player = await ensure_voice(interaction, user_should_connect=True)
        
        if not player.queue:
            await interaction.followup.send("The queue is already empty.")
            return
        else:
            player.queue.clear()
            await interaction.followup.send("Queue cleared.")
    except app_commands.AppCommandError as e:
        await interaction.followup.send(str(e))
    except Exception as e:
        print(f"Error in clear command: {e}")
        await interaction.followup.send("An error occurred while trying to clear the queue.")

@bot.tree.command(name="stop", description="Terminate the player")
async def stop(interaction: Interaction):
    await interaction.response.defer()

    try:
        player = await ensure_voice(interaction, user_should_connect=True)

        player.queue.clear()
        await player.stop()
        if interaction.guild.voice_client:
                await interaction.guild.voice_client.disconnect(force=True)
        await interaction.followup.send("Player Terminated.")
        
    except app_commands.AppCommandError as e:
        await interaction.followup.send(str(e))
    except Exception as e:
        print(f"Error in stop command: {e}")
        await interaction.followup.send("An error occurred while trying to stop the player.")

@bot.tree.command(name="playlist", description="Display updated playlist")
async def playlist(interaction: Interaction, url: str, added: int=None):
    channel = interaction.channel
    await interaction.response.defer(ephemeral=True)
    player = await ensure_voice(interaction, user_should_connect=False)

    try:
        # Search for the tracks using the provided query
        result = await player.node.get_tracks(url)
        if result.load_type == lavalink.LoadType.PLAYLIST:
            # delete old playlist message
            async for message in channel.history(limit=25):
                if message.embeds:
                    for embed in message.embeds:
                        if embed.url == url:
                            await message.delete()

            embed = discord.Embed(title=f"{result.playlist_info.name}", url=url, color=0x22a7f2)
            embed.set_thumbnail(url=result.tracks[0].artwork_url)
            if added:
                embed.add_field(name="New", value=f"`{added}`", inline=True)
            embed.add_field(name="Command", value=f"`/play query:{url}`", inline=True)
            await channel.send(embed=embed)
            await interaction.followup.send(f"Playlist updated.")
        else:
            await interaction.followup.send(f"Please provide a valid playlist URL.")

    except Exception as e:
        print(f"Error in playlist command: {e}")
        await interaction.followup.send("An error occurred while trying to update the playlist.")

bot.run(BOT_TOKEN)