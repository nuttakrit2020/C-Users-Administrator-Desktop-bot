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
# ดึง Token จาก Environment Variable ของระบบ
# วิธีนี้ปลอดภัยที่สุดสำหรับเอาขึ้น GitHub โค้ดคลีนๆ เลย
# ==========================================
TOKEN = os.environ.get("DISCORD_TOKEN")

if not TOKEN:
    print("❌ ไม่พบ Token! อย่าลืมตั้งค่า Environment Variable ชื่อ DISCORD_TOKEN ก่อนรันบอทนะครับ")
    exit()
# ==========================================

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
#  ตั้งค่า yt-dlp และ FFmpeg
# ==========================================
YDL_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "extract_flat": "in_playlist",
    "socket_timeout": 10,
    "cookiefile": "cookies.txt",  # <--- เพิ่มบรรทัดนี้ลงไปครับ! 🍪
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
    opts = {**YDL_OPTS, "extract_flat": "in_playlist" if is_url else False}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(search, download=False))
    return info.get("entries", [info]) if "entries" in info else [info]

async def get_audio_url(webpage_url: str):
    loop = asyncio.get_event_loop()
    opts = {**YDL_OPTS, "noplaylist": True, "extract_flat": False}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(webpage_url, download=False))
    audio = [f for f in info.get("formats", []) if f.get("acodec") != "none" and f.get("vcodec") == "none"]
    return max(audio, key=lambda f: f.get("abr") or 0)["url"] if audio else info["url"]

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
        if vc and not vc.is_playing():
            await vc.disconnect()
        return

    try:
        url = await get_audio_url(track.get("webpage_url") or track.get("url"))
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(url, **FFMPEG_OPTS),
            volume=data["volume"]
        )
        vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop))
    except Exception as e:
        print(f"[เล่นไม่ได้] {e}")
        asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop)

# ==========================================
#  คำตอบแบบน่ารัก random~
# ==========================================
PLAY_MSGS   = ["เด้งๆ กำลังหาเพลงให้เลยนะ 🎵", "โอเคค รอแปปนึง~ 🔍", "หาให้ละ แป๊บนึงนะ 🥰"]
ADDED_MSGS  = ["เพิ่มแล้วจ้า! คิวยาวขึ้นอีกแล้ว 🎶", "โอเคเพิ่มแล้ว~ รอฟังนะ 💕", "ได้เลย! เพลงดีแน่นอน 🌸"]
SKIP_MSGS   = ["ข้ามแล้วจ้า ไปเพลงต่อไป~ ⏭", "โอเค ข้ามๆ 🏃‍♀️💨", "ข้ามแล้ว! เพลงหน้ามาเลย 🎵"]
PAUSE_MSGS  = ["หยุดพักก่อนนะ~ ⏸", "โอเค หยุดก่อน กลับมาเล่นต่อได้เลย 💤", "พักก่อนนะ อย่าไปไหน 🥺"]
RESUME_MSGS = ["กลับมาแล้ว~ เล่นต่อเลย! ▶️", "เย้! เพลงกลับมาแล้ว 🎉", "เล่นต่อแล้วนะ 💕"]
STOP_MSGS   = ["โอเค หยุดแล้วนะ บาย~ 👋", "โอเค ออกไปพักก่อน เรียกกลับมาได้เสมอนะ 🥹", "โอเคๆ ไปพักก่อนละ 😴"]

def r(msgs): return random.choice(msgs)

# ==========================================
#  คำสั่ง
# ==========================================

@tree.command(name="เล่น", description="🎵 เล่นเพลงจาก YouTube — ใส่ชื่อเพลงหรือลิ้งก์ได้เลย!")
@app_commands.describe(เพลง="ชื่อเพลง หรือ ลิ้งก์ YouTube")
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
    except:
        return await interaction.edit_original_response(content="หาไม่เจออ่ะ ลองใหม่นะ 😢")

    for t in tracks:
        data["queue"].append(t)

    if len(tracks) == 1:
        msg = f"{r(ADDED_MSGS)}\n🎵 **{tracks[0].get('title','?')}**"
    else:
        msg = f"เพิ่ม **{len(tracks)} เพลง** ลงคิวแล้วจ้า 🎶"

    await interaction.edit_original_response(content=msg)
    if not vc.is_playing() and not vc.is_paused():
        await play_next(interaction.guild)


@tree.command(name="ข้าม", description="⏭ ข้ามเพลงนี้ไปเพลงหน้าเลย")
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await interaction.response.send_message(r(SKIP_MSGS))
    else:
        await interaction.response.send_message("ไม่มีเพลงเล่นอยู่อ่ะ 😅")


@tree.command(name="หยุด", description="⏸ หยุดเพลงชั่วคราว")
async def pause(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await interaction.response.send_message(r(PAUSE_MSGS))
    else:
        await interaction.response.send_message("ไม่มีเพลงเล่นอยู่เลยนะ 🤔")


@tree.command(name="เล่นต่อ", description="▶️ เล่นเพลงต่อจากที่หยุด")
async def resume(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await interaction.response.send_message(r(RESUME_MSGS))
    else:
        await interaction.response.send_message("ไม่ได้หยุดอยู่นะ 😊")


@tree.command(name="ปิด", description="⏹ หยุดและออกจากห้องเสียง")
async def stop(interaction: discord.Interaction):
    data = get_data(interaction.guild_id)
    data["queue"].clear()
    data["current"] = None
    vc = interaction.guild.voice_client
    if vc:
        vc.stop()
        await vc.disconnect()
    await interaction.response.send_message(r(STOP_MSGS))


@tree.command(name="คิว", description="📋 ดูเพลงที่รออยู่ทั้งหมด")
async def queue_cmd(interaction: discord.Interaction):
    data = get_data(interaction.guild_id)
    q = list(data["queue"])
    cur = data["current"]
    if not cur and not q:
        return await interaction.response.send_message("คิวว่างอยู่เลย ลองสั่ง /เล่น ดูนะ 🎵")

    lines = []
    if cur:
        lines.append(f"🎵 **กำลังเล่น:** {cur.get('title','?')}")
    for i, t in enumerate(q[:15], 1):
        lines.append(f"`{i}.` {t.get('title','?')}")
    if len(q) > 15:
        lines.append(f"...และอีก {len(q)-15} เพลงนะ 🎶")

    embed = discord.Embed(title="📋 คิวเพลงทั้งหมด", description="\n".join(lines), color=0xFF8FAB)
    embed.set_footer(text=f"มีเพลงรออยู่ {len(q)} เพลงเลย~")
    await interaction.response.send_message(embed=embed)


@tree.command(name="เพลงนี้", description="🎶 ดูข้อมูลเพลงที่เล่นอยู่ตอนนี้")
async def nowplaying(interaction: discord.Interaction):
    data = get_data(interaction.guild_id)
    t = data["current"]
    if not t:
        return await interaction.response.send_message("ยังไม่มีเพลงเลยนะ สั่ง /เล่น ได้เลย! 🎵")

    embed = discord.Embed(title="🎵 เพลงที่เล่นอยู่ตอนนี้", description=f"**{t.get('title','?')}**", color=0xFF8FAB)
    if t.get("thumbnail"):
        embed.set_thumbnail(url=t["thumbnail"])
    if t.get("duration"):
        m, s = divmod(int(t["duration"]), 60)
        embed.add_field(name="⏱ ความยาว", value=f"{m}:{s:02d}")
    if t.get("uploader"):
        embed.add_field(name="📺 ช่อง", value=t["uploader"])
    loop_txt = "🔂 เพลงนี้" if data["loop"] else ("🔁 ทั้งหมด" if data["loop_all"] else "ปิด")
    embed.add_field(name="🔁 Loop", value=loop_txt)
    embed.add_field(name="🔊 เสียง", value=f"{int(data['volume']*100)}%")
    embed.set_footer(text="สนุกกับเพลงนะ~ 🥰")
    await interaction.response.send_message(embed=embed)


@tree.command(name="เสียง", description="🔊 ปรับระดับเสียง 0-100")
@app_commands.describe(ระดับ="0 = เงียบ, 100 = ดังสุด")
async def volume(interaction: discord.Interaction, ระดับ: int):
    if not 0 <= ระดับ <= 100:
        return await interaction.response.send_message("ใส่ 0-100 นะ อย่าเกินนะ~ 😅")
    data = get_data(interaction.guild_id)
    data["volume"] = ระดับ / 100
    vc = interaction.guild.voice_client
    if vc and vc.source:
        vc.source.volume = data["volume"]
    emoji = "🔇" if ระดับ == 0 else "🔉" if ระดับ < 50 else "🔊"
    await interaction.response.send_message(f"{emoji} ปรับเสียงเป็น **{ระดับ}%** แล้วนะ~")


@tree.command(name="วนซ้ำ", description="🔁 ตั้งค่าการวนซ้ำเพลง")
@app_commands.choices(โหมด=[
    app_commands.Choice(name="ปิด — ไม่วนซ้ำ", value="off"),
    app_commands.Choice(name="เพลงนี้ — วนซ้ำแค่เพลงนี้", value="one"),
    app_commands.Choice(name="ทั้งหมด — วนซ้ำทั้ง queue", value="all"),
])
@app_commands.describe(โหมด="เลือกโหมดวนซ้ำ")
async def loop_cmd(interaction: discord.Interaction, โหมด: str):
    data = get_data(interaction.guild_id)
    if โหมด == "off":
        data["loop"] = data["loop_all"] = False
        await interaction.response.send_message("โอเค ปิด loop แล้วนะ 🎵")
    elif โหมด == "one":
        data["loop"] = True
        data["loop_all"] = False
        await interaction.response.send_message("🔂 วนซ้ำเพลงนี้ไปเรื่อยๆ เลย~")
    else:
        data["loop"] = False
        data["loop_all"] = True
        await interaction.response.send_message("🔁 วนซ้ำทั้ง queue เลยนะ~")


@tree.command(name="สลับ", description="🔀 สลับลำดับเพลงใน queue แบบ random")
async def shuffle(interaction: discord.Interaction):
    data = get_data(interaction.guild_id)
    q = list(data["queue"])
    if not q:
        return await interaction.response.send_message("คิวว่างอยู่นะ~ 😅")
    random.shuffle(q)
    data["queue"] = deque(q)
    await interaction.response.send_message(f"🔀 สลับเพลงแบบ random แล้ว! {len(q)} เพลง พร้อมเลย~")


@tree.command(name="ลบ", description="🗑 ลบเพลงออกจาก queue")
@app_commands.describe(ลำดับ="ลำดับที่ต้องการลบ ดูได้จาก /คิว")
async def remove(interaction: discord.Interaction, ลำดับ: int):
    data = get_data(interaction.guild_id)
    q = list(data["queue"])
    if ลำดับ < 1 or ลำดับ > len(q):
        return await interaction.response.send_message("ลำดับไม่ถูกต้องนะ ลองดู /คิว ก่อน~ 🤔")
    removed = q.pop(ลำดับ - 1)
    data["queue"] = deque(q)
    await interaction.response.send_message(f"🗑 ลบแล้ว: **{removed.get('title','?')}** ออกจากคิวแล้วนะ~")


@tree.command(name="ช่วย", description="💡 ดูคำสั่งทั้งหมดของบอท")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎵 บอทเพลงสุดน่ารัก~",
        description="สั่งได้เลยนะ! บอทพร้อมเสมอ 💕",
        color=0xFF8FAB
    )
    commands_list = [
        ("🎵 /เล่น [ชื่อ/ลิ้งก์]", "เล่นเพลงหรือเพิ่ม queue"),
        ("⏭ /ข้าม", "ข้ามไปเพลงหน้า"),
        ("⏸ /หยุด", "หยุดชั่วคราว"),
        ("▶️ /เล่นต่อ", "เล่นต่อจากที่หยุด"),
        ("⏹ /ปิด", "หยุดและออกห้อง"),
        ("📋 /คิว", "ดูเพลงทั้งหมดในคิว"),
        ("🎶 /เพลงนี้", "ดูข้อมูลเพลงที่เล่นอยู่"),
        ("🔊 /เสียง [0-100]", "ปรับระดับเสียง"),
        ("🔁 /วนซ้ำ", "ตั้งค่าวนซ้ำ"),
        ("🔀 /สลับ", "สลับเพลง random"),
        ("🗑 /ลบ [ลำดับ]", "ลบเพลงออกจากคิว"),
    ]
    for name, desc in commands_list:
        embed.add_field(name=name, value=desc, inline=False)
    embed.set_footer(text="ฟังเพลงให้สนุกนะ~ 🌸")
    await interaction.response.send_message(embed=embed)


# ==========================================
#  ออกห้องเสียงเมื่อไม่มีคน
# ==========================================
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    vc = member.guild.voice_client
    if vc and all(m.bot for m in vc.channel.members):
        await asyncio.sleep(60)
        vc = member.guild.voice_client
        if vc and not vc.is_playing():
            await vc.disconnect()


@bot.event
async def on_ready():
    await tree.sync()
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening,
        name="เพลงสุดชิล~ 🎵"
    ))
    print(f"✅ บอทออนไลน์แล้ว! {bot.user} พร้อมเล่นเพลงแล้ว~")


bot.run(TOKEN)
