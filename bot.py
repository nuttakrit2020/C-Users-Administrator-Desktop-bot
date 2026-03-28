import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import re
import random
from collections import deque
import os

# ==========================================
# ดึง Token
# ==========================================
TOKEN = os.environ.get("DISCORD_TOKEN")

if not TOKEN:
    print("❌ ไม่พบ Token! อย่าลืมตั้งค่า Environment Variable ชื่อ DISCORD_TOKEN")
    exit()

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

guilds_data: dict[int, dict] = {}

def get_data(guild_id):
    if guild_id not in guilds_data:
        guilds_data[guild_id] = {
            "queue": deque(),
            "loop": False,
            "loop_all": False,
            "volume": 0.5,
            "current": None,
        }
    return guilds_data[guild_id]

# ==========================================
#  ตั้งค่า yt-dlp และ FFmpeg (สูตรอมตะแก้ Requested format)
# ==========================================

# ⚠️ กฎเหล็ก: ห้ามใส่คีย์ 'format' ใน Option ของ YoutubeDL ตรงนี้เด็ดขาด
YDL_OPTS_BASE = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": "in_playlist",
    "socket_timeout": 30,
    "cookiefile": "cookies.txt", 
    "nocheckcertificate": True,
    "ignoreerrors": True,
}

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin",
    "options": "-vn -af loudnorm=I=-16:TP=-1.5:LRA=11",
}

# ==========================================
#  ฟังก์ชันดึง URL (หัวใจสำคัญที่ต้องแก้)
# ==========================================
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
    
    # ดึงข้อมูลแบบดิบที่สุด ไม่ระบุ format เพื่อให้ YouTube ยอมคายข้อมูลออกมา
    with yt_dlp.YoutubeDL(YDL_OPTS_BASE) as ydl:
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(webpage_url, download=False))
    
    if not info: raise Exception("หาข้อมูลไม่เจอ")

    # บอทจะมาเลือก Format เองจากรายการที่ YouTube ส่งมา (ไม่ผ่านฟิลเตอร์ของ yt-dlp)
    formats = info.get('formats', [])
    
    # 1. ลองหาไฟล์เสียงล้วน (M4A หรือ WebM)
    audio_only = [f for f in formats if f.get('acodec') != 'none' and (f.get('vcodec') == 'none' or f.get('vcodec') == 'audio only')]
    
    if audio_only:
        # เลือกตัวที่ Bitrate สูงที่สุดเท่าที่มี
        best_audio = max(audio_only, key=lambda f: f.get('abr') or 0)
        return best_audio['url']
    
    # 2. ถ้าไม่มีเสียงล้วน ให้เลือกฟอร์แมตใดก็ได้ที่มี URL (วิดีโอรวมเสียง)
    for f in formats:
        if f.get('url') and 'manifest' not in f.get('url', ''):
            return f['url']
            
    # 3. ถ้าหาไม่ได้จริงๆ ให้เอา URL หลักที่มันยัดเยียดมาให้
    if 'url' in info: return info['url']
    
    raise Exception("YouTube บล็อคการดึงไฟล์เสียงเพลงนี้ครับบอส")

# ==========================================
#  ระบบเล่นเพลง
# ==========================================
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
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(url, **FFMPEG_OPTS),
            volume=data["volume"]
        )
        vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop))
    except Exception as e:
        print(f"❌ [Error]: {e}")
        asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop)

# ==========================================
#  คำสั่ง (ครบชุดเดิมที่บอสชอบ)
# ==========================================

@tree.command(name="เล่น", description="🎵 เล่นเพลง")
async def play(interaction: discord.Interaction, เพลง: str):
    await interaction.response.defer()
    
    # ตรวจสอบห้องเสียง
    if not interaction.user.voice:
        return await interaction.followup.send("บอสครับ! เข้าห้องเสียงก่อนน้าาา 🥺")
    
    vc = interaction.guild.voice_client
    if not vc:
        vc = await interaction.user.voice.channel.connect()
    
    data = get_data(interaction.guild_id)
    await interaction.followup.send("🔍 กำลังหาเพลงให้ครับบอส...")

    try:
        tracks = await fetch_tracks(เพลง)
        if not tracks:
            return await interaction.edit_original_response(content="หาไม่เจอจริงๆ อ่ะ บอสลองเปลี่ยนชื่อดูนะ 😢")
        
        for t in tracks[:50]:
            data["queue"].append(t)
            
        msg = f"เพิ่ม **{tracks[0].get('title')}** ลงคิวแล้วครับ! 🎶"
        await interaction.edit_original_response(content=msg)
        
        if not vc.is_playing() and not vc.is_paused():
            await play_next(interaction.guild)
            
    except Exception as e:
        await interaction.edit_original_response(content=f"เกิดข้อผิดพลาด: `{e}`")

# --- คำสั่งพื้นฐาน (ใส่มาให้ครบตามสัญญา) ---

@tree.command(name="ข้าม", description="⏭ ข้ามเพลง")
async def skip(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("ข้ามให้แล้วจ้า! ⏭")

@tree.command(name="หยุด", description="⏸ หยุดเพลง")
async def pause(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        interaction.guild.voice_client.pause()
        await interaction.response.send_message("หยุดพักก่อนนะ~ ⏸")

@tree.command(name="เล่นต่อ", description="▶️ เล่นต่อ")
async def resume(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        interaction.guild.voice_client.resume()
        await interaction.response.send_message("เล่นต่อแล้วจ้า! ▶️")

@tree.command(name="ปิด", description="⏹ ปิดบอท")
async def stop(interaction: discord.Interaction):
    get_data(interaction.guild_id)["queue"].clear()
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
    await interaction.response.send_message("บ๊ายบายจ้าบอส! 👋")

@tree.command(name="คิว", description="📋 ดูคิวเพลง")
async def queue_cmd(interaction: discord.Interaction):
    data = get_data(interaction.guild_id)
    q = list(data["queue"])
    if not q and not data["current"]: return await interaction.response.send_message("คิวว่างจ้าาา")
    txt = f"🎵 **กำลังเล่น:** {data['current'].get('title') if data['current'] else '-'}\n"
    txt += "\n".join([f"`{i+1}.` {t.get('title')}" for i, t in enumerate(q[:10])])
    await interaction.response.send_message(txt)

@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ บอท {bot.user} พร้อมลุยแล้วบอส!")

bot.run(TOKEN)
