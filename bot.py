import discord
from discord.ext import commands
from discord import Interaction
import youtube_dl

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!',intents=intents)

@bot.event
async def on_ready():
    print(f'Logged on as {bot.user}')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="Music"))
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} commands')
    except Exception as e:
        print(e)

@bot.tree.command(name="play", description="Play the song from the URL")
async def play(interaction: Interaction, url: str):
    vc = interaction.user.voice.channel
    player = await vc.connect()
    ydl_opts = {'format': 'bestaudio/best'}
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        url2 = info['formats'][0]['url']
        player.play(discord.FFmpegPCMAudio(url2))

bot.run('NzcxNjU1Njk5MDQ1Njc5MTI0.GtxmLZ.ZdtrBkyjpPBjK1qkxEOlSBvNy37XbdKlR6fTrI')