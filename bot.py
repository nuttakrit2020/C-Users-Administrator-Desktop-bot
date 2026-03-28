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
        guilds_data[guild_id] = {"queue": deque(), "volume": 0.5, "current": None}
    return guilds_data[guild_id]

# ตั้งค่า YT-DLP ใหม่ ตัด Android ออกเพราะมันมีปัญหากับคุกกี้บนเซ็นเซอร์
YDL_OPTS = {
    "quiet": True,
    "format": "bestaudio/best",
    "noplaylist": True,
    "cookiefile": "cookies.txt",
    "nocheckcertificate": True,
    "ignoreerrors": False, # เปิดไว้เพื่อให้เห็น Error ชัดๆ
    "extract_flat": False,
    "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
}

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin",
    "options": "-vn",
}

async def play_next(guild: discord.Guild):
    data = get_data(guild.id)
    vc = guild.voice_client
    if not vc or not data["queue"]:
        data["current"] = None
        return

    track_url = data["queue"].popleft()
    
    try:
        # ดึง URL สดๆ ก่อนเล่น
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(track_url, download=False))
            url = info['url']
            data["current"] = info['title']

        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(url, **FFMPEG_OPTS), volume=data["volume"])
        vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop))
    except Exception as e:
        print(f"❌ Play Next Error: {e}")
        asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop)

@tree.command(name="เล่น", description="🎵 เล่นเพลง")
async def play(interaction: discord.Interaction, เพลง: str):
    await interaction.response.defer()
    
    if not interaction.user.voice:
        return await interaction.followup.send("บอส! เข้าห้องเสียงก่อนนน 🥺")

    vc = interaction.guild.voice_client or await interaction.user.voice.channel.connect(self_deaf=True)
    data = get_data(interaction.guild_id)
    
    try:
        # ค้นหาแบบเรียบง่ายที่สุด
        with yt_dlp.YoutubeDL({"quiet": True, "format": "bestaudio", "cookiefile": "cookies.txt"}) as ydl:
            search_info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(f"ytsearch1:{เพลง}", download=False))
            
            if not search_info or 'entries' not in search_info or not search_info['entries']:
                return await interaction.edit_original_response(content="หาเพลงไม่เจอจริงๆ ครับบอส ลองเปลี่ยนคำดูนะ")
            
            track = search_info['entries'][0]
            if track is None:
                return await interaction.edit_original_response(content="YouTube บล็อกการเข้าถึงข้อมูลเพลงนี้ครับ")
                
            data["queue"].append(track['webpage_url'])
            await interaction.edit_original_response(content=f"เพิ่มเพลง **{track.get('title', 'Unknown')}** เข้าคิวแล้วครับ! 🎶")

        if not vc.is_playing():
            await play_next(interaction.guild)

    except Exception as e:
        await interaction.edit_original_response(content=f"เกิดข้อผิดพลาด: `{e}`")

@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ บอท {bot.user} พร้อมสู้ YouTube แล้วบอส!")

bot.run(TOKEN)
