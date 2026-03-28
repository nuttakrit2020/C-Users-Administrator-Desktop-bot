import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import os
from collections import deque

TOKEN = os.environ.get("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

guilds_data: dict[int, dict] = {}

def get_data(guild_id):
    if guild_id not in guilds_data:
        guilds_data[guild_id] = {"queue": deque(), "loop": False, "loop_all": False, "volume": 0.5, "current": None}
    return guilds_data[guild_id]

# ตั้งค่า YT-DLP แบบ Bypass ทุกอย่าง
YDL_OPTS = {
    "quiet": True,
    "format": "bestaudio/best",
    "cookiefile": "cookies.txt",
    "nocheckcertificate": True,
    "ignoreerrors": True,
    "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
}

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin",
    "options": "-vn -af loudnorm=I=-16:TP=-1.5:LRA=11",
}

async def get_audio_url(url):
    loop = asyncio.get_event_loop()
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
    return info.get('url') or info.get('formats', [{}])[0].get('url')

async def play_next(guild: discord.Guild):
    data = get_data(guild.id)
    vc = guild.voice_client
    if not vc or not data["queue"]:
        data["current"] = None
        return

    track = data["queue"].popleft()
    data["current"] = track

    try:
        url = await get_audio_url(track['webpage_url'])
        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(url, **FFMPEG_OPTS), volume=data["volume"])
        vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop))
    except Exception as e:
        print(f"❌ Play Error: {e}")
        asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop)

@tree.command(name="เล่น", description="🎵 เล่นเพลง")
async def play(interaction: discord.Interaction, เพลง: str):
    await interaction.response.defer()
    
    if not interaction.user.voice:
        return await interaction.followup.send("บอส! เข้าห้องเสียงก่อนนน 🥺")

    # ปรับการ Connect ให้รองรับ DAVE
    vc = interaction.guild.voice_client
    if not vc:
        try:
            vc = await interaction.user.voice.channel.connect(self_deaf=True)
        except Exception as e:
            return await interaction.followup.send(f"เชื่อมต่อไม่ได้: {e}")

    data = get_data(interaction.guild_id)
    
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(f"ytsearch1:{เพลง}", download=False))
        if not info or 'entries' not in info or not info['entries']:
            return await interaction.edit_original_response(content="หาไม่เจอครับบอส!")
        
        track = info['entries'][0]
        data["queue"].append(track)
        await interaction.edit_original_response(content=f"เพิ่มเพลง **{track['title']}** แล้วครับ! 🎶")

    if not vc.is_playing():
        await play_next(interaction.guild)

@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ {bot.user} พร้อมลุย (DAVE Ready!)")

bot.run(TOKEN)
