import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import re
import random
from collections import deque
import os

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

# ==========================================
#  สูตรแก้ Requested format (ฉบับอัปเกรด)
# ==========================================
YDL_OPTS_BASE = {
    "quiet": True,
    "no_warnings": True,
    "format": "bestaudio/best", # บังคับเลือกฟอร์แมตที่ยืดหยุ่นที่สุดตรงนี้เลย
    "extract_flat": "in_playlist",
    "cookiefile": "cookies.txt", 
    "nocheckcertificate": True,
    "ignoreerrors": True,
    "extractor_args": {"youtube": {"player_client": ["android", "web"]}}, # ใช้ Client หลายตัวช่วยหา
}

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin",
    "options": "-vn -af loudnorm=I=-16:TP=-1.5:LRA=11",
}

async def fetch_tracks(query: str):
    loop = asyncio.get_event_loop()
    is_url = re.match(r"https?://", query)
    search = query if is_url else f"ytsearch5:{query}"
    with yt_dlp.YoutubeDL(YDL_OPTS_BASE) as ydl:
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(search, download=False))
    if not info: return []
    return info.get("entries", [info]) if "entries" in info else [info]

async def get_audio_url(webpage_url: str):
    loop = asyncio.get_event_loop()
    # ใช้ฟอร์แมต ba* เพื่อให้มันเอา Audio อะไรก็ได้ที่มี (แก้ Requested format error)
    opts = {**YDL_OPTS_BASE, "format": "ba/ba*", "noplaylist": True, "extract_flat": False}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(webpage_url, download=False))
    
    if not info: raise Exception("หาข้อมูลไม่เจอ")
    return info.get('url') or info.get('formats', [{}])[0].get('url')

async def play_next(guild: discord.Guild):
    data = get_data(guild.id)
    vc = guild.voice_client
    if not vc: return

    if data["loop"] and data["current"]:
        track = data["current"]
    elif data["queue"]:
        track = data["queue"].popleft()
        if data["loop_all"]: data["queue"].append(track)
        data["current"] = track
    else:
        data["current"] = None
        return

    try:
        url = await get_audio_url(track.get("webpage_url") or track.get("url"))
        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(url, **FFMPEG_OPTS), volume=data["volume"])
        vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop))
    except Exception as e:
        print(f"❌ [Error]: {e}")
        asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop)

# ==========================================
#  คำสั่ง (ครบชุด)
# ==========================================

@tree.command(name="เล่น", description="🎵 เล่นเพลง")
async def play(interaction: discord.Interaction, เพลง: str):
    await interaction.response.defer()
    if not interaction.user.voice: return await interaction.followup.send("บอส! เข้าห้องเสียงก่อนนน 🥺")
    
    vc = interaction.guild.voice_client or await interaction.user.voice.channel.connect()
    data = get_data(interaction.guild_id)
    
    try:
        tracks = await fetch_tracks(เพลง)
        if not tracks: return await interaction.edit_original_response(content="หาไม่เจอจริงๆ อ่ะ บอสเปลี่ยนชื่อดูนะ 😢")
        
        for t in tracks[:50]: data["queue"].append(t)
        await interaction.edit_original_response(content=f"เพิ่ม **{tracks[0].get('title')}** แล้วจ้า! 🎶")
        
        if not vc.is_playing() and not vc.is_paused(): await play_next(interaction.guild)
    except Exception as e:
        await interaction.edit_original_response(content=f"Error: `{e}`")

@tree.command(name="ข้าม", description="⏭ ข้ามเพลง")
async def skip(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("ข้ามให้แล้วครับบอส! ⏭")

@tree.command(name="ปิด", description="⏹ ปิดบอท")
async def stop(interaction: discord.Interaction):
    get_data(interaction.guild_id)["queue"].clear()
    if interaction.guild.voice_client: await interaction.guild.voice_client.disconnect()
    await interaction.response.send_message("บ๊ายบายครับบอส! 👋")

@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ {bot.user} พร้อมลุย!")

bot.run(TOKEN)
