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
# 1. ตั้งค่าพื้นฐาน
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
# 2. ตั้งค่า yt-dlp & FFmpeg (สูตรลับกัน Error)
# ==========================================
YDL_OPTS = {
    "quiet": True,
    "format": "bestaudio/best",
    "noplaylist": True,
    "cookiefile": "cookies.txt",  # บอสอย่าลืมอัปไฟล์นี้นะ
    "nocheckcertificate": True,
    "ignoreerrors": True,
    "extract_flat": False,
    # ช่วยให้ yt-dlp หาทางเลี่ยงการโดนบล็อคได้ดีขึ้น
    "extractor_args": {"youtube": {"player_client": ["web", "android"]}}, 
}

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin",
    "options": "-vn -af loudnorm=I=-16:TP=-1.5:LRA=11",
}

# ==========================================
# 3. ข้อความตอบกลับสุ่มๆ
# ==========================================
PLAY_MSGS = ["รับทราบครับบอส! เดี๋ยวจัดให้ 🎵", "รอแป๊บน้า กำลังจูนคลื่นเพลงให้... 🔍", "จัดไปวัยรุ่น! 🥰"]
SKIP_MSGS = ["ข้ามให้แล้วจ้า! เพลงถัดไปมาเลย ⏭", "โอเค ข้ามๆๆ 🏃‍♂️💨"]
STOP_MSGS = ["หยุดเล่นแล้วครับ ไว้เจอกันใหม่นะบอส! 👋", "พักเครื่องแป๊บ เรียกได้เสมอนะ 😴"]

def r(msgs): return random.choice(msgs)

# ==========================================
# 4. ฟังก์ชันหลัก (เล่นเพลง & ดึงข้อมูล)
# ==========================================
async def play_next(guild: discord.Guild):
    data = get_data(guild.id)
    vc = guild.voice_client
    if not vc: return

    # เช็คโหมดวนซ้ำ
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
        # ดึง URL สดๆ ก่อนเล่น เพื่อป้องกันลิงก์หมดอายุ
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ydl.extract_info(track['webpage_url'], download=False)
            )
            # ป้องกัน Error กรณีดึง URL ไม่ได้
            if not info or 'url' not in info:
                raise Exception("YouTube ไม่ยอมให้ดึงเพลงนี้ครับบอส")
            
            url = info['url']

        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(url, **FFMPEG_OPTS),
            volume=data["volume"]
        )
        vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop))
        
    except Exception as e:
        print(f"❌ Play Error: {e}")
        asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop)

# ==========================================
# 5. คำสั่ง Slash Commands
# ==========================================

@tree.command(name="เล่น", description="🎵 เล่นเพลงจาก YouTube")
async def play(interaction: discord.Interaction, เพลง: str):
    # --- 1. รีบทักทาย Discord ทันที (ห้ามมีอะไรคั่นก่อนบรรทัดนี้) ---
    try:
        await interaction.response.defer(thinking=True) 
    except:
        return # ถ้า Defer ไม่ทันก็ช่างมัน ให้จบการทำงานไปเลย

    # --- 2. เช็คเงื่อนไขต่างๆ ---
    if not interaction.user.voice:
        return await interaction.followup.send("บอสครับ! เข้าห้องเสียงก่อนนะ 🥺")

    vc = interaction.guild.voice_client
    if not vc:
        try:
            vc = await interaction.user.voice.channel.connect(self_deaf=True)
        except Exception as e:
            return await interaction.followup.send(f"เข้าห้องไม่ได้ครับ: {e}")

    data = get_data(interaction.guild_id)

    # --- 3. ค้นหาเพลง (ใช้ Followup แทน Edit Original เพราะปลอดภัยกว่า) ---
    try:
        # ใช้ลิ้งก์ตรงๆ หรือค้นหา
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            search_info = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ydl.extract_info(f"ytsearch1:{เพลง}", download=False)
            )
            
            if not search_info or 'entries' not in search_info or not search_info['entries']:
                return await interaction.followup.send("หาเพลงไม่เจอจริงๆ ครับบอส!")
            
            track = search_info['entries'][0]
            if track is None:
                return await interaction.followup.send("YouTube บล็อกเพลงนี้ (Signature Error)")

            data["queue"].append(track)
            await interaction.followup.send(f"เพิ่มเพลง **{track.get('title')}** แล้วจ้า! 🎶")

        if not vc.is_playing():
            await play_next(interaction.guild)

    except Exception as e:
        # ถ้าพังตรงนี้ ให้ส่ง Error บอกบอส
        try:
            await interaction.followup.send(f"เกิดข้อผิดพลาด: `{e}`")
        except:
            print(f"Error: {e}")

@tree.command(name="ข้าม", description="⏭ ข้ามไปเพลงถัดไป")
async def skip(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        interaction.guild.voice_client.stop()
        await interaction.response.send_message(r(SKIP_MSGS))

@tree.command(name="คิว", description="📋 ดูคิวเพลง")
async def queue_list(interaction: discord.Interaction):
    data = get_data(interaction.guild_id)
    q = list(data["queue"])
    cur = data["current"]
    if not cur and not q: return await interaction.response.send_message("คิวว่างจ้าาา")
    
    txt = f"🎵 **ตอนนี้เล่น:** {cur.get('title') if cur else '-'}\n"
    txt += "\n".join([f"`{i+1}.` {t.get('title')}" for i, t in enumerate(q[:10])])
    await interaction.response.send_message(txt)

@tree.command(name="ปิด", description="⏹ ปิดบอทและออกจากห้อง")
async def stop(interaction: discord.Interaction):
    data = get_data(interaction.guild_id)
    data["queue"].clear()
    data["current"] = None
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
    await interaction.response.send_message(r(STOP_MSGS))

@tree.command(name="วนซ้ำ", description="🔁 ตั้งค่าการวนซ้ำ")
@app_commands.choices(โหมด=[
    app_commands.Choice(name="ปิด", value="off"),
    app_commands.Choice(name="เพลงเดียว", value="one"),
    app_commands.Choice(name="ทั้งคิว", value="all"),
])
async def loop_cmd(interaction: discord.Interaction, โหมด: str):
    data = get_data(interaction.guild_id)
    data["loop"] = (โหมด == "one")
    data["loop_all"] = (โหมด == "all")
    await interaction.response.send_message(f"ตั้งค่าวนซ้ำเป็น: {โหมด} เรียบร้อย!")

# ==========================================
# 6. รันบอท
# ==========================================
@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ บอท {bot.user} พร้อมลุยครับบอส!")

if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ ไม่พบ Token ใน Environment Variable!")
