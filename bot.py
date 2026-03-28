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
# ดึง Token จาก Environment Variable
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
#  ตั้งค่า yt-dlp และ FFmpeg (สูตรแก้ Requested format)
# ==========================================

# ตัวเลือกพื้นฐาน - เราจะไม่ใส่ 'format' ตรงนี้เด็ดขาดเพื่อกัน Error
YDL_OPTS_BASE = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": "in_playlist",
    "socket_timeout": 30,
    "cookiefile": "cookies.txt", # <--- สำคัญมากสำหรับเพลงดังๆ
    "nocheckcertificate": True,
    "ignoreerrors": True,
}

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin",
    "options": "-vn -af loudnorm=I=-16:TP=-1.5:LRA=11",
}

# ==========================================
#  ดึงข้อมูลเพลง
# ==========================================
async def fetch_tracks(query: str):
    loop = asyncio.get_event_loop()
    is_url = re.match(r"https?://", query)
    search = query if is_url else f"ytsearch5:{query}"
    
    with yt_dlp.YoutubeDL(YDL_OPTS_BASE) as ydl:
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(search, download=False))
    
    if not info:
        return []
        
    return info.get("entries", [info]) if "entries" in info else [info]

async def get_audio_url(webpage_url: str):
    loop = asyncio.get_event_loop()
    
    # วิธีแก้ปัญหา: ไม่ใส่ format ใน opts เลย เพื่อให้ดึงข้อมูลได้ทุกกรณี
    extract_opts = {
        **YDL_OPTS_BASE,
        "noplaylist": True,
        "extract_flat": False,
    }
    
    with yt_dlp.YoutubeDL(extract_opts) as ydl:
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(webpage_url, download=False))
    
    if not info:
        raise Exception("หาข้อมูลเพลงไม่เจอ")

    # เรามาเลือก URL เองจากรายการ formats ที่ YouTube ส่งมาให้ทั้งหมด
    # ค้นหา format ที่เป็น audio เท่านั้นก่อน
    formats = info.get('formats', [])
    audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
    
    if audio_formats:
        # เอาตัวที่ bit rate สูงที่สุด
        best_audio = max(audio_formats, key=lambda f: f.get('abr') or 0)
        return best_audio['url']
    
    # ถ้าไม่มี audio อย่างเดียว ให้เอาอันไหนก็ได้ที่มี URL (รวมวิดีโอ)
    if 'url' in info:
        return info['url']
    
    if formats:
        return formats[0]['url']
        
    raise Exception("ไม่สามารถดึง URL สำหรับเล่นเพลงได้")

# ==========================================
#  เล่นเพลงต่อไป
# ==========================================
async def play_next(guild: discord.Guild):
    data = get_data(guild.id)
    vc = guild.voice_client
    if not vc:
        return

    if data["loop"] and data["current"]:
        track = data["current"]
    elif data["queue"]:
        track = data["queue"].popleft()
        if data["loop_all"]:
            data["queue"].append(track)
        data["current"] = track
    else:
        data["current"] = None
        await asyncio.sleep(300)
        if vc and not vc.is_playing() and not data["queue"]:
            await vc.disconnect()
        return

    try:
        # ดึง URL สำหรับสตรีม
        url = await get_audio_url(track.get("webpage_url") or track.get("url"))
        
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(url, **FFMPEG_OPTS),
            volume=data["volume"]
        )
        
        vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop))
        
    except Exception as e:
        print(f"❌ [Error ในการเล่น]: {e}")
        asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop)

# ==========================================
#  คำตอบแบบน่ารัก random~
# ==========================================
PLAY_MSGS    = ["เด้งๆ กำลังหาเพลงให้เลยนะ 🎵", "โอเคค รอแปปนึง~ 🔍", "หาให้ละ แป๊บนึงนะ 🥰"]
ADDED_MSGS   = ["เพิ่มแล้วจ้า! คิวยาวขึ้นอีกแล้ว 🎶", "โอเคเพิ่มแล้ว~ รอฟังนะ 💕", "ได้เลย! เพลงดีแน่นอน 🌸"]
SKIP_MSGS    = ["ข้ามแล้วจ้า ไปเพลงต่อไป~ ⏭", "โอเค ข้ามๆ 🏃‍♀️💨", "ข้ามแล้ว! เพลงหน้ามาเลย 🎵"]
PAUSE_MSGS   = ["หยุดพักก่อนนะ~ ⏸", "โอเค หยุดก่อน กลับมาเล่นต่อได้เลย 💤", "พักก่อนนะ อย่าไปไหน 🥺"]
RESUME_MSGS  = ["กลับมาแล้ว~ เล่นต่อเลย! ▶️", "เย้! เพลงกลับมาแล้ว 🎉", "เล่นต่อแล้วนะ 💕"]
STOP_MSGS    = ["โอเค หยุดแล้วนะ บาย~ 👋", "โอเค ออกไปพักก่อน เรียกกลับมาได้เสมอนะ 🥹", "โอเคๆ ไปพักก่อนละ 😴"]

def r(msgs): return random.choice(msgs)

# ==========================================
#  คำสั่ง
# ==========================================

@tree.command(name="เล่น", description="🎵 เล่นเพลงจาก YouTube")
async def play(interaction: discord.Interaction, เพลง: str):
    await interaction.response.defer()

    if not interaction.user.voice:
        return await interaction.followup.send("เฮ้~ เข้าห้องเสียงก่อนนะ บอทจะได้ตามไปได้ 🥺")

    vc = interaction.guild.voice_client
    ch = interaction.user.voice.channel
    
    if vc and vc.channel != ch:
        await vc.move_to(ch)
    elif not vc:
        vc = await ch.connect()

    data = get_data(interaction.guild_id)
    await interaction.followup.send(r(PLAY_MSGS))

    try:
        tracks = await fetch_tracks(เพลง)
        tracks = [t for t in tracks if t][:50]
        
        if not tracks:
            return await interaction.edit_original_response(content="หาไม่เจอจริงๆ อ่ะ ลองเปลี่ยนคำค้นหาดูนะ 😢")
            
    except Exception as e:
        return await interaction.edit_original_response(content=f"เกิดข้อผิดพลาด: `{str(e)[:100]}`")

    for t in tracks:
        data["queue"].append(t)

    if len(tracks) == 1:
        msg = f"{r(ADDED_MSGS)}\n🎵 **{tracks[0].get('title','ไม่ทราบชื่อ')}**"
    else:
        msg = f"เพิ่ม **{len(tracks)} เพลง** ลงคิวแล้วจ้า 🎶"

    await interaction.edit_original_response(content=msg)
    
    if not vc.is_playing() and not vc.is_paused():
        await play_next(interaction.guild)

# --- (คำสั่งอื่นๆ คงเดิมไว้ทั้งหมดตามที่คุณต้องการ) ---

@tree.command(name="ข้าม", description="⏭ ข้ามเพลง")
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()
        await interaction.response.send_message(r(SKIP_MSGS))
    else:
        await interaction.response.send_message("ไม่มีเพลงเล่นอยู่อ่ะ 😅")

@tree.command(name="หยุด", description="⏸ หยุดชั่วคราว")
async def pause(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await interaction.response.send_message(r(PAUSE_MSGS))
    else:
        await interaction.response.send_message("ไม่มีเพลงเล่นอยู่เลยนะ 🤔")

@tree.command(name="เล่นต่อ", description="▶️ เล่นต่อ")
async def resume(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await interaction.response.send_message(r(RESUME_MSGS))
    else:
        await interaction.response.send_message("ไม่ได้หยุดอยู่นะ 😊")

@tree.command(name="ปิด", description="⏹ ปิดบอท")
async def stop(interaction: discord.Interaction):
    data = get_data(interaction.guild_id)
    data["queue"].clear()
    data["current"] = None
    vc = interaction.guild.voice_client
    if vc:
        vc.stop()
        await vc.disconnect()
    await interaction.response.send_message(r(STOP_MSGS))

@tree.command(name="คิว", description="📋 ดูคิว")
async def queue_cmd(interaction: discord.Interaction):
    data = get_data(interaction.guild_id)
    q = list(data["queue"])
    cur = data["current"]
    if not cur and not q:
        return await interaction.response.send_message("คิวว่างอยู่เลย ลองสั่ง /เล่น ดูนะ 🎵")
    lines = [f"🎵 **กำลังเล่น:** {cur.get('title','?')}" if cur else ""]
    for i, t in enumerate(q[:15], 1):
        lines.append(f"`{i}.` {t.get('title','?')}")
    embed = discord.Embed(title="📋 คิวเพลง", description="\n".join(lines), color=0xFF8FAB)
    await interaction.response.send_message(embed=embed)

@tree.command(name="เพลงนี้", description="🎶 ดูข้อมูลเพลง")
async def nowplaying(interaction: discord.Interaction):
    data = get_data(interaction.guild_id)
    t = data["current"]
    if not t: return await interaction.response.send_message("ไม่มีเพลงเล่นอยู่จ้า")
    embed = discord.Embed(title="🎵 กำลังเล่น", description=f"**{t.get('title','?')}**", color=0xFF8FAB)
    if t.get("thumbnail"): embed.set_thumbnail(url=t["thumbnail"])
    await interaction.response.send_message(embed=embed)

@tree.command(name="เสียง", description="🔊 ปรับเสียง")
async def volume(interaction: discord.Interaction, ระดับ: int):
    if not 0 <= ระดับ <= 100: return await interaction.response.send_message("0-100 นะ!")
    data = get_data(interaction.guild_id)
    data["volume"] = ระดับ / 100
    if interaction.guild.voice_client and interaction.guild.voice_client.source:
        interaction.guild.voice_client.source.volume = data["volume"]
    await interaction.response.send_message(f"🔊 ปรับเสียงเป็น {ระดับ}%")

@tree.command(name="วนซ้ำ", description="🔁 วนซ้ำ")
@app_commands.choices(โหมด=[
    app_commands.Choice(name="ปิด", value="off"),
    app_commands.Choice(name="เพลงนี้", value="one"),
    app_commands.Choice(name="ทั้งหมด", value="all"),
])
async def loop_cmd(interaction: discord.Interaction, โหมด: str):
    data = get_data(interaction.guild_id)
    data["loop"] = (โหมด == "one")
    data["loop_all"] = (โหมด == "all")
    await interaction.response.send_message(f"ตั้งค่าวนซ้ำเป็น {โหมด} แล้วจ้า")

@tree.command(name="สลับ", description="🔀 สลับคิว")
async def shuffle(interaction: discord.Interaction):
    data = get_data(interaction.guild_id)
    q = list(data["queue"])
    random.shuffle(q)
    data["queue"] = deque(q)
    await interaction.response.send_message("🔀 สลับเพลงในคิวแล้ว!")

@tree.command(name="ลบ", description="🗑 ลบเพลง")
async def remove(interaction: discord.Interaction, ลำดับ: int):
    data = get_data(interaction.guild_id)
    if 1 <= ลำดับ <= len(data["queue"]):
        data["queue"].rotate(-(ลำดับ-1))
        removed = data["queue"].popleft()
        data["queue"].rotate(ลำดับ-1)
        await interaction.response.send_message(f"🗑 ลบเพลง {removed.get('title')} แล้ว")
    else:
        await interaction.response.send_message("ลำดับไม่ถูกนะ")

@tree.command(name="ช่วย", description="💡 ดูคำสั่ง")
async def help_cmd(interaction: discord.Interaction):
    await interaction.response.send_message("ใช้ /เล่น [ชื่อเพลง] ได้เลยจ้า และคำสั่งอื่นๆ ดูได้จากเมนู Slash Command นะ!")

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot: return
    vc = member.guild.voice_client
    if vc and len(vc.channel.members) == 1:
        await asyncio.sleep(30)
        if len(vc.channel.members) == 1: await vc.disconnect()

@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ บอทออนไลน์แล้วในชื่อ: {bot.user}")

bot.run(TOKEN)
