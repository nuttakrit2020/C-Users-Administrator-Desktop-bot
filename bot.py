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
# 1. ตั้งค่าพื้นฐาน (TOKEN & INTENTS)
# ==========================================
TOKEN = os.environ.get("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# เก็บข้อมูลแยกตาม Server
guilds_data = {}

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
# 2. ตั้งค่าการดึงข้อมูล (สูตรแก้ Signature & Format)
# ==========================================

# ใช้ 'best' แทน 'bestaudio' เพื่อหลอก YouTube ว่าเป็นคนดูวิดีโอ
YDL_OPTS = {
    "quiet": True,
    "format": "best", 
    "cookiefile": "cookies.txt",  # บอสต้องมีไฟล์นี้ในโฟลเดอร์บอทนะ!
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "extract_flat": False,
    "no_warnings": True,
    "default_search": "ytsearch",
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

# FFmpeg จะกรองเอาแค่เสียงจากไฟล์วิดีโอที่ดึงมา
FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin",
    "options": "-vn -af loudnorm=I=-16:TP=-1.5:LRA=11",
}

# ==========================================
# 3. ฟังก์ชันหัวใจหลัก (เล่นเพลงถัดไป)
# ==========================================
async def play_next(guild: discord.Guild):
    data = get_data(guild.id)
    vc = guild.voice_client
    if not vc: return

    # ตรวจสอบคิวและโหมดวนซ้ำ
    if data["loop"] and data["current"]:
        track = data["current"]
    elif data["queue"]:
        track = data["queue"].popleft()
        if data["loop_all"]:
            data["queue"].append(track)
        data["current"] = track
    else:
        data["current"] = None
        return

    try:
        # ดึง URL ล่าสุดก่อนเล่น (กันลิงก์ตาย)
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ydl.extract_info(track['webpage_url'], download=False)
            )
            if not info:
                raise Exception("YouTube บล็อกข้อมูลเพลงนี้")
            
            url = info.get('url') or info.get('formats', [{}])[0].get('url')

        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(url, **FFMPEG_OPTS),
            volume=data["volume"]
        )
        vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop))
        
    except Exception as e:
        print(f"❌ Play Error: {e}")
        # ถ้าพัง ให้ข้ามไปเพลงถัดไปเลย
        asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop)

# ==========================================
# 4. คำสั่งหลัก (Slash Commands)
# ==========================================

@tree.command(name="เล่น", description="🎵 เล่นเพลงหรือลิ้งก์ YouTube")
async def play(interaction: discord.Interaction, เพลง: str):
    # --- รีบ Defer ทันทีภายใน 3 วินาที เพื่อกัน Unknown Interaction Error ---
    try:
        await interaction.response.defer(thinking=True)
    except:
        return

    # เช็คห้องเสียง
    if not interaction.user.voice:
        return await interaction.followup.send("บอสครับ! เข้าห้องเสียงก่อนนะ 🥺")

    vc = interaction.guild.voice_client
    if not vc:
        try:
            vc = await interaction.user.voice.channel.connect(self_deaf=True)
        except Exception as e:
            return await interaction.followup.send(f"เชื่อมต่อห้องเสียงไม่ได้: {e}")

    data = get_data(interaction.guild_id)

    # เริ่มกระบวนการค้นหา
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            # ลองดึงข้อมูล (รองรับทั้งลิ้งก์ตรงและคำค้นหา)
            search_info = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ydl.extract_info(f"ytsearch1:{เพลง}" if not เพลง.startswith("http") else เพลง, download=False)
            )
            
            if not search_info:
                return await interaction.followup.send("หาเพลงไม่เจอจริงๆ ครับบอส! (YouTube บล็อกการค้นหา)")

            # ตรวจสอบผลลัพธ์
            if 'entries' in search_info:
                if not search_info['entries']:
                    return await interaction.followup.send("ไม่พบผลการค้นหาครับบอส")
                track = search_info['entries'][0]
            else:
                track = search_info

            if track is None:
                return await interaction.followup.send("เกิดข้อผิดพลาดในการดึงข้อมูล (Signature Error)")

            data["queue"].append(track)
            await interaction.followup.send(f"เพิ่มเพลง **{track.get('title', 'Unknown')}** แล้วจ้า! 🎶")

        # ถ้าบอทเงียบอยู่ ให้เริ่มเล่น
        if not vc.is_playing() and not vc.is_paused():
            await play_next(interaction.guild)

    except Exception as e:
        await interaction.followup.send(f"เกิดข้อผิดพลาด: `{e}`")

@tree.command(name="ข้าม", description="⏭ ข้ามไปเพลงถัดไป")
async def skip(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("ข้ามให้แล้วครับบอส! ⏭")
    else:
        await interaction.response.send_message("ไม่มีเพลงให้ข้ามนะบอส")

@tree.command(name="ปิด", description="⏹ ปิดบอทและล้างคิว")
async def stop(interaction: discord.Interaction):
    data = get_data(interaction.guild_id)
    data["queue"].clear()
    data["current"] = None
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
    await interaction.response.send_message("บ๊ายบายครับบอส! ไว้เรียกใหม่นะ 👋")

@tree.command(name="คิว", description="📋 ดูรายการเพลงในคิว")
async def queue_cmd(interaction: discord.Interaction):
    data = get_data(interaction.guild_id)
    q = list(data["queue"])
    cur = data["current"]
    if not cur and not q:
        return await interaction.response.send_message("ตอนนี้ไม่มีเพลงในคิวเลยครับบอส")
    
    msg = f"🎵 **กำลังเล่น:** {cur.get('title') if cur else '-'}\n\n**คิวถัดไป:**\n"
    msg += "\n".join([f"`{i+1}.` {t.get('title')}" for i, t in enumerate(q[:10])])
    await interaction.response.send_message(msg)

# ==========================================
# 5. เริ่มทำงาน
# ==========================================
@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ บอท {bot.user} ออนไลน์สมบูรณ์แบบแล้วครับบอส!")

if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ Error: ไม่พบ Discord Token ใน Environment Variable")
