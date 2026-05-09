from indexTTS2 import send_LLM_indexTTS2
from datetime import datetime
import os
import requests
from bs4 import BeautifulSoup
import wave
import cv2
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageStat, ImageTk
import numpy as np
import subprocess
import shutil
from pathlib import Path
import threading
import sys
import queue
try:
    import vlc  # 可选，用于内嵌播放器
except Exception:
    vlc = None
import tkinter as tk
from tkinter import messagebox, filedialog
 
 
STATUS_FIRST_FRAME = 0  # 第一帧的标识
STATUS_CONTINUE_FRAME = 1  # 中间帧标识
STATUS_LAST_FRAME = 2  # 最后一帧的标识
 
# -------------------- 可执行打包适配 --------------------
def is_frozen():
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')

def resource_path(relative_path):
    try:
        base_path = getattr(sys, '_MEIPASS') if is_frozen() else Path(__file__).parent
    except Exception:
        base_path = Path('.')
    return str(Path(base_path) / relative_path)

def get_data_dir():
    # 使用应用当前执行路径作为数据根目录
    try:
        base_dir = Path.cwd()
    except Exception:
        base_dir = Path('.')
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir

def get_subdir(name):
    sub = get_data_dir() / name
    sub.mkdir(parents=True, exist_ok=True)
    return sub


def open_video_external(video_path):
    """
    在 Windows 上打开 mp4。若未关联默认播放器，os.startfile 会报 WinError -2147221003，
    依次尝试：startfile、cmd start、PATH/常见路径中的 VLC、资源管理器定位到文件。
    任一成功返回 True。
    """
    p = Path(video_path)
    if not p.is_file():
        return False
    resolved = str(p.resolve())

    if os.name == "nt":
        try:
            os.startfile(resolved)
            return True
        except OSError:
            pass
        try:
            subprocess.run(
                ["cmd", "/c", "start", "", resolved],
                check=True,
                shell=False,
            )
            return True
        except (OSError, subprocess.CalledProcessError):
            pass
        vlc_exe = shutil.which("vlc")
        if vlc_exe:
            try:
                subprocess.Popen([vlc_exe, resolved])
                return True
            except OSError:
                pass
        for vlc_candidate in (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "VideoLAN"
            / "VLC"
            / "vlc.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
            / "VideoLAN"
            / "VLC"
            / "vlc.exe",
        ):
            if vlc_candidate.is_file():
                try:
                    subprocess.Popen([str(vlc_candidate), resolved])
                    return True
                except OSError:
                    pass
        try:
            subprocess.Popen(["explorer", "/select,", resolved])
            return True
        except OSError:
            pass
        return False

    if sys.platform == "darwin":
        try:
            subprocess.Popen(["open", resolved])
            return True
        except OSError:
            return False
    opener = shutil.which("xdg-open")
    if opener:
        try:
            subprocess.Popen([opener, resolved])
            return True
        except OSError:
            pass
    return False

def getnowtime():
    formattrd_time =datetime.now()
    return formattrd_time.strftime('%p')+formattrd_time.strftime('%Y-%m-%d')+ formattrd_time.strftime('%H%M%S')

# indexTTS2 参考音频：未在界面选择时使用以下默认路径
DEFAULT_TIMBRE_MP3 = r"D:\SoftWare\TTSources\DQ.mp3"
DEFAULT_EMOTION_MP3 = r"D:\SoftWare\TTSources\dqbs.mp3"

def load_hot_segments_from_txt(txt_path):
    """从用户选择的 txt 读取正文并按与网页抓取相同的规则切分为分段文件。返回 (分段路径列表, 本批前缀 textname)。"""
    path = Path(txt_path)
    if not path.is_file():
        print(f"文本文件不存在: {txt_path}")
        return [], None
    content = read_file(str(path))
    if not content or content.startswith("文件 ") or content.startswith("读取文件时发生错误"):
        print(f"无法读取文本: {txt_path} -> {content[:120] if content else ''}")
        return [], None
    text = content.strip()
    if not text:
        print("文本文件为空")
        return [], None
    textname = getnowtime()
    textnamelist = []
    textnamelist = splitfile(text, textname, textnamelist)
    print(f"已使用本地 TXT 生成分段，本批 textname={textname}")
    return textnamelist, textname

 #获取热点新闻
def getredhubhot():
   # 发送HTTP请求
    print("获取数据中...")
    url = 'https://www.dushu.com/meiwen/random/'
    # url = 'https://www.dushu.com/meiwen/'
    response = requests.get(url)
    textnamelist = []
    # filename ="./newwav/new/"+textname+".txt"
    # 检查请求是否成功
    if response.status_code != 200:
        print(f"请求失败，状态码: {response.status_code}")
        return textnamelist, None
    print("获取数据成功")
    print("开始解析数据")
    soup = BeautifulSoup(response.text, 'html.parser')
    hot_news_container = soup.find('div', class_='article-detail')
    if not hot_news_container:
        print("解析失败：未找到 article-detail")
        return textnamelist, None
    hot_news_items = hot_news_container.find_all('div', class_='text')
    if not hot_news_items:
        print("解析失败：未找到 div.text 正文")
        return textnamelist, None
    h1 = hot_news_container.find('h1')
    info = hot_news_container.find('div', class_='article-info')
    if not h1 or not info:
        print("解析失败：缺少标题或作者区域")
        return textnamelist, None

    textname = getnowtime()
    title = h1.text.replace(" ", "")
    author = info.text.replace(" ", "").replace("\n", "")
    text = title + '\n' + author + '\n' + hot_news_items[0].text.replace(" ", "").replace("\n", "")

    textnamelist = splitfile(text, textname, textnamelist)

    print(f"标题: {title}")
    print(f"作者: {author}")
    print(f"详情：{text}")
    print(f"解析数据完成，本批 textname={textname}")
    return textnamelist, textname
    
def splitfile(text ,textname,textnamelist):
    max_size = 3 * 1024  # 9KB in bytes
    text_length = len(text)
    start = 0

    file_number = 1
    while start < text_length:
        end = start + max_size
        if end > text_length:
            end = text_length
        filename = str(get_subdir('new') / (textname+str(file_number)+".txt"))
        textnamelist.append(filename)
        with open(f'{filename}', 'w', encoding='utf-8') as file:
            file.write(text[start:end])
        start = end
        file_number += 1
    return textnamelist

 
def read_file(file_path):
    """
    读取文件的全部内容并返回。
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        return content
    except FileNotFoundError:
        return f"文件 {file_path} 未找到"
    except Exception as e:
        return f"读取文件时发生错误: {e}"

# 计算文本宽度
def wrap_text(text, font, max_chars_per_line=16):
    lines = []
    current_line = ''
    for char in text:
        if len(current_line) >= max_chars_per_line or (char == '\n' and current_line):
            current_line += char
            lines.append(current_line)
            current_line = char if char == '\n' else ''
        else:
            current_line += char
    if current_line:
        lines.append(current_line)
    return lines

#获取音频时长
def get_wav_duration(wav_file):
    try:
        with wave.open(str(wav_file), 'r') as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            duration = frames / float(rate)
            return duration
    except (wave.Error, OSError, FileNotFoundError) as e:
        print(f"无法打开 WAV 文件 {wav_file}: {e}")
        return None


def OPenCVPIL(text, wav_path, background_images):
    print("视频生成中...")
        # 加载背景图片
    # background_image_path = "./95.jpg"  # 替换为您的背景图片路径
    # background_image = Image.open(background_image_path).convert("RGB").resize((1080, 1920))

    # 创建绘图对象
    draw = ImageDraw.Draw(background_images[0])
    font = ImageFont.truetype("C:/Windows/Fonts/simfang.ttf", 50)  # 替换为您的字体路径

    # 分割文本
    lines = wrap_text(text, font)

    # 行间距
    line_spacing = 47

    # 计算每行文本的高度
    line_height = font.getbbox("高")[3] - font.getbbox("高")[1] + line_spacing  # 获取字体高度

    # 计算总文本高度
    total_text_height = len(lines) * line_height

    # 计算起始位置
    start_x = 100  # 根据需要调整起始X坐标
    start_y = 1000  # 根据需要调整起始Y坐标

    # 视频输出设置
    fps = 16  # 帧/秒
    wav_path = Path(wav_path)
    if not wav_path.is_file():
        print(f"跳过视频合成：WAV 不存在 {wav_path.resolve()}")
        return
    raw_dur = get_wav_duration(wav_path)
    duration_per_line = int(raw_dur) if raw_dur and raw_dur > 0 else 30
    total_frames = max(1, duration_per_line * fps)
    mp4_out = wav_path.with_suffix(".mp4")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    temp_output = str(get_data_dir() / 'output.mp4')
    out = cv2.VideoWriter(temp_output, fourcc, fps, (1080, 1920))

    # 计算滚动速度
    scroll_speed = total_text_height / total_frames # 每帧移动的距离

     # 计算每张背景图的显示帧数
    frames_per_background = int(total_frames / len(background_images))
    if frames_per_background < 80:
        frames_per_background = 80  # 确保每张背景图至少显示16*5帧

    # 写入帧
    num_backgrounds = len(background_images)
    for frame_idx in range(total_frames):
        # # 创建一个新的背景图像
        # frame = background_image.copy()
        # draw = ImageDraw.Draw(frame)
         # 选择背景图片
        background_idx = (frame_idx // frames_per_background) % num_backgrounds
        frame = background_images[background_idx].copy()
        draw = ImageDraw.Draw(frame)

        # 计算当前偏移量
        offset = start_y - frame_idx * scroll_speed

        # 绘制所有行文本
        for i, line in enumerate(lines):
            hpyl =  line_height if i==0 else i * line_height #行偏移量
            y_position = offset + hpyl
            if y_position < 1920 and y_position  > 0:
                draw.text((start_x, y_position), line, font=font, fill="#000000")

        # 转换为 OpenCV 格式
        frame = np.array(frame)
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        # 写入帧
        out.write(frame)

    out.release()

    # 添加音频
    subprocess.run([
        'ffmpeg', '-y', '-i', temp_output, '-i', str(wav_path), '-c:v', 'libx264', '-preset', 'slow', '-crf', '23',
        '-c:a', 'aac', '-b:a', '128k', '-vf', 'format=yuv420p', str(mp4_out)
    ], check=False)

def create_concat_list(video_files, list_filename):
    with open(list_filename, 'w') as f:
        for video_file in video_files:
            f.write(f"file '{str(Path(video_file).resolve())}'\n")

def merge_videos(video_folder, prefix, output_filename):
    """将 video_folder 下以 prefix 开头的分段 mp4 合并为 output_filename。成功返回 True。"""
    folder = Path(video_folder)
    video_files = sorted(str(f) for f in folder.glob(f'{prefix}*.mp4'))

    if not video_files:
        print(f"没有找到以 {prefix} 开头的视频文件（本批是否全部 TTS/合成失败？）。")
        return False

    list_filename = str(get_subdir('new') / 'concat_list.txt')
    try:
        create_concat_list(video_files, list_filename)
        Path(output_filename).parent.mkdir(parents=True, exist_ok=True)
        command = [
            'ffmpeg',
            '-f', 'concat',
            '-safe', '0',
            '-i', str(Path(list_filename).resolve()),
            '-c', 'copy',
            output_filename,
        ]
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        print(f"ffmpeg 合并失败: {e}")
        return False
    except OSError as e:
        print(f"合并过程出错: {e}")
        return False
    finally:
        if Path(list_filename).exists():
            try:
                os.remove(list_filename)
            except OSError:
                pass

    out = Path(output_filename)
    if not out.is_file() or out.stat().st_size == 0:
        print(f"合并后输出无效: {output_filename}")
        return False
    return True
# 创建目录的函数
def create_directory(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    print(f"已创建目录 {path}")

# 删除目录下所有文件的函数
def delete_files_in_directory(file_path):
    folder = Path(file_path)
    if not folder.exists():  # 检查目录是否存在
        print(f"目录 {file_path} 不存在。")
        return

    for file in folder.iterdir():
        try:
            file.unlink()  # 删除文件
            print(f"已删除文件: {file}")
        except Exception as e:
            print(f"无法删除文件 {file}: {e}")

class StdoutRedirector(object):
    def __init__(self, queue_obj):
        self.queue = queue_obj

    def write(self, message):
        if message:
            self.queue.put(message)

    def flush(self):
        pass


def generate_workflow(
    background_image_paths,
    timbre_path=None,
    emotion_path=None,
    user_txt_path=None,
    on_video_ready=None,
):
    # 目录就绪
    new_dir = get_subdir('new')
    videos_dir = get_subdir('videos')
    user_txt = (user_txt_path or "").strip()
    if user_txt:
        print("使用本地 TXT，跳过网页抓取")
        hotfilelist, batch_textname = load_hot_segments_from_txt(user_txt)
    else:
        hotfilelist, batch_textname = getredhubhot()
    if not hotfilelist or not batch_textname:
        print("未获取到可用文本，流程终止")
        return None

    timbre = (timbre_path or "").strip() or DEFAULT_TIMBRE_MP3
    emotion = (emotion_path or "").strip() or DEFAULT_EMOTION_MP3
    if not Path(timbre).is_file():
        print(f"音色参考文件不存在: {timbre}")
        return None
    if not Path(emotion).is_file():
        print(f"情感参考文件不存在: {emotion}")
        return None
    # 背景图
    try:
        resolved_paths = []
        for p in background_image_paths:
            p = p.strip()
            if not p:
                continue
            rp = Path(p)
            if not rp.is_absolute():
                rp = Path(resource_path(p))
            resolved_paths.append(rp)
        background_images = [Image.open(str(p)).convert("RGB").resize((1080, 1920)) for p in resolved_paths]
    except Exception as e:
        print(f"加载背景图失败: {e}，使用默认背景。")
        try:
            default_bg = Image.new("RGB", (1080, 1920), (245, 245, 245))
            background_images = [default_bg]
        except Exception as e2:
            print(f"创建默认背景失败: {e2}")
            return None

    # 合成每段并生成分段视频
    for hotfile in hotfilelist:
        content = read_file(hotfile)
        if not content or content.startswith("文件 ") or content.startswith("读取文件时发生错误"):
            print(f"跳过无效文本: {hotfile} -> {content[:80] if content else ''}")
            continue
        stem_path = str(Path(hotfile).with_suffix(""))
        wav_path = send_LLM_indexTTS2(
            timbre,
            emotion,
            content,
            stem_path,
        )
        if not wav_path:
            print(f"本段 TTS 失败，已跳过视频合成: {stem_path}")
            continue
        OPenCVPIL(content, wav_path, background_images)

    # 合并（前缀与 splitfile 使用的 textname 一致，避免误匹配其它批次的 mp4）
    video_folder = str(new_dir)
    final_name = getnowtime() + ".mp4"
    output_filename = str((videos_dir / final_name).resolve())
    ok = False
    try:
        ok = merge_videos(video_folder, batch_textname, output_filename)
        if ok:
            print("视频合成完成：" + output_filename)
            if callable(on_video_ready):
                on_video_ready(output_filename)
        else:
            print("本次未生成最终合并视频，请检查日志中的 TTS 与 ffmpeg 提示。")
            output_filename = None
    finally:
        delete_files_in_directory(video_folder)
    return output_filename if ok else None


class AppGUI:
    """界面配色与雨天窗景背景图协调：木色描边、米白面板、鼠尾草绿按钮。"""

    STYLE = {
        "surface": "#EDE8DF",
        "text": "#2A2319",
        "muted": "#5C5348",
        "accent": "#5F7D5F",
        "accent_active": "#4F6B4F",
        "border": "#5C4336",
        "entry_bg": "#FFFBF6",
        "log_bg": "#FAF8F4",
        "log_fg": "#2A2319",
        "video_bg": "#1E1914",
        "video_placeholder": "#B8B0A8",
        # 背景：模糊半径越大越虚；蒙层比例越大越偏乳白、背景越“透”感弱
        "bg_blur_radius": 0,
        "bg_frost_blend": 0.22,
        "bg_frost_rgb": (237, 232, 223),
    }
    FONT_UI = ("Microsoft YaHei UI", 10)
    FONT_UI_BOLD = ("Microsoft YaHei UI", 10, "bold")
    FONT_SMALL = ("Microsoft YaHei UI", 9)
    _SHELL_MARGIN = 22
    _PANEL_GAP = 10

    @staticmethod
    def _pil_mean_hex(im):
        m = ImageStat.Stat(im).mean
        return "#%02x%02x%02x" % tuple(int(max(0, min(255, x))) for x in m[:3])

    def __init__(self, root):
        self.root = root
        self.root.title("每日一文")
        self.root.minsize(960, 700)
        self.root.geometry("1080x820")
        st = self.STYLE

        self.log_queue = queue.Queue()
        self.stdout_backup = sys.stdout
        self.stderr_backup = sys.stderr
        sys.stdout = StdoutRedirector(self.log_queue)
        sys.stderr = StdoutRedirector(self.log_queue)

        self._bg_photo = None
        self._bg_pil_canvas = None
        self._bg_image_raw = None
        bg_file = Path(resource_path("watermark-removed.png"))
        if not bg_file.is_file():
            bg_file = Path(__file__).resolve().parent / "watermark-removed.png"
        try:
            self._bg_image_raw = Image.open(bg_file).convert("RGB")
        except Exception:
            self._bg_image_raw = Image.new("RGB", (1024, 1024), (212, 206, 196))

        self.bg_canvas = tk.Canvas(root, highlightthickness=0, bd=0, bg="#2a2520")
        self.bg_canvas.pack(fill=tk.BOTH, expand=True)

        # 自定义：Canvas + 与主背景同步的裁切图（视觉上透明）；控件叠在上方
        self.form_canvas = tk.Canvas(
            self.bg_canvas,
            highlightthickness=1,
            highlightbackground=st["border"],
            bd=0,
            width=400,
            height=320,
        )
        self.form_inner = tk.Frame(self.form_canvas, bd=0, highlightthickness=0)
        self._form_inner_win = self.form_canvas.create_window(
            10, 10, window=self.form_inner, anchor="nw"
        )

        # 表单：音色/情感留空则用默认路径；文本留空则按原逻辑抓取网页
        self.timbre_path_var = tk.StringVar(value="")
        self.emotion_path_var = tk.StringVar(value="")
        self.user_txt_var = tk.StringVar(value="")
        self.bg_path_var = tk.StringVar(value="./95.jpg")

        row = 0
        self._form_title = tk.Label(
            self.form_inner,
            text=" 自定义 ",
            fg=st["text"],
            font=self.FONT_UI_BOLD,
            bd=0,
        )
        self._form_title.grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 6))
        row += 1
        self._form_row(self.form_inner, row, "音色文件:", self.timbre_path_var, self.choose_timbre)
        row += 1
        self._form_row(self.form_inner, row, "情感文件:", self.emotion_path_var, self.choose_emotion)
        row += 1
        self._form_row(self.form_inner, row, "文本(txt):", self.user_txt_var, self.choose_user_txt)
        row += 1
        self._form_row(self.form_inner, row, "背景图(JPG):", self.bg_path_var, self.choose_bg)
        row += 1

        self.start_btn = tk.Button(
            self.form_inner,
            text="开始生成",
            command=self.on_start,
            font=self.FONT_UI,
            bg=st["accent"],
            fg="white",
            activebackground=st["accent_active"],
            activeforeground="white",
            disabledforeground="#E8E4DE",
            relief=tk.FLAT,
            cursor="hand2",
            padx=20,
            pady=8,
        )
        self.start_btn.grid(row=row, column=0, columnspan=3, pady=(12, 8))
        self.form_inner.grid_columnconfigure(1, weight=1)

        self._form_win = self.bg_canvas.create_window(
            self._SHELL_MARGIN,
            self._SHELL_MARGIN,
            window=self.form_canvas,
            anchor="nw",
        )

        # 视频预览：实色面板；video_host 为 VLC HWND / OpenCV 帧绘制区（勿在 host 内叠放子控件以免遮挡 VLC）
        self.preview_frame = tk.LabelFrame(
            self.bg_canvas,
            text=" 视频预览 ",
            bg=st["surface"],
            fg=st["text"],
            font=self.FONT_UI_BOLD,
            labelanchor="nw",
            bd=1,
            relief=tk.GROOVE,
        )
        self.preview_inner = tk.Frame(self.preview_frame, bg=st["surface"])
        self.preview_inner.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.video_host = tk.Frame(self.preview_inner, bg=st["video_bg"], highlightthickness=0, bd=0)
        self.video_host.pack(fill=tk.BOTH, expand=True)
        self.video_placeholder = tk.Label(
            self.preview_inner,
            text="生成完成后在此内嵌预览\n（推荐：pip install python-vlc 并安装 VLC；否则使用 OpenCV 画面预览）",
            bg=st["video_bg"],
            fg=st["video_placeholder"],
            font=self.FONT_SMALL,
            anchor="center",
            justify=tk.CENTER,
        )
        self.video_placeholder.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._preview_win = self.bg_canvas.create_window(
            self._SHELL_MARGIN + 420,
            self._SHELL_MARGIN,
            window=self.preview_frame,
            anchor="nw",
        )

        self.player_instance = None
        self.player = None
        self._cv_job = None
        self._cv_cap = None
        self._cv_photo = None
        self.cv_label = None
        self._reembed_job = None
        self._video_mode = None

        if vlc is not None:
            try:
                self.player_instance = vlc.Instance(
                    "--intf",
                    "dummy",
                    "--quiet",
                    "--no-video-title-show",
                )
                self.player = self.player_instance.media_player_new()
            except Exception as e:
                print(f"初始化 VLC 失败（将使用 OpenCV 预览）: {e}")
                self.player_instance = None
                self.player = None

        self.video_host.bind("<Configure>", self._on_video_host_configure)
        self.root.after(200, self._initial_vlc_embed)

        # 日志：与自定义相同，裁切背景 + 略提亮的 Text 底
        self.log_canvas = tk.Canvas(
            self.bg_canvas,
            highlightthickness=1,
            highlightbackground=st["border"],
            bd=0,
            width=400,
            height=260,
        )
        self.text_widget = tk.Text(
            self.log_canvas,
            height=12,
            font=self.FONT_SMALL,
            bg=st["log_bg"],
            fg=st["log_fg"],
            insertbackground=st["text"],
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=st["border"],
            padx=8,
            pady=8,
        )
        self._log_text_win = self.log_canvas.create_window(
            8, 36, window=self.text_widget, anchor="nw"
        )

        self._log_win = self.bg_canvas.create_window(
            self._SHELL_MARGIN,
            self._SHELL_MARGIN + 340,
            window=self.log_canvas,
            anchor="nw",
        )

        self.bg_canvas.bind("<Configure>", self._on_canvas_configure)
        self.root.after_idle(lambda: self._redraw_background(
            max(self.bg_canvas.winfo_width(), 1080),
            max(self.bg_canvas.winfo_height(), 820),
        ))

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.poll_log_queue)

        self.current_video_path = None

    def _form_row(self, parent, row, label_text, textvariable, pick_command):
        st = self.STYLE
        tk.Label(parent, text=label_text, bg=st["surface"], fg=st["text"], font=self.FONT_UI).grid(
            row=row, column=0, sticky="e", padx=(8, 6), pady=5
        )
        ent = tk.Entry(
            parent,
            textvariable=textvariable,
            width=32,
            font=self.FONT_SMALL,
            bg=st["entry_bg"],
            fg=st["text"],
            insertbackground=st["text"],
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=st["border"],
            highlightcolor=st["accent"],
        )
        ent.grid(row=row, column=1, sticky="ew", padx=(0, 6), pady=5)
        tk.Button(
            parent,
            text="浏览…",
            command=pick_command,
            font=self.FONT_SMALL,
            bg=st["surface"],
            fg=st["text"],
            activebackground=st["entry_bg"],
            activeforeground=st["text"],
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=st["border"],
            cursor="hand2",
            padx=8,
            pady=4,
        ).grid(row=row, column=2, sticky="e", padx=(0, 8), pady=5)

    def _apply_form_transparency_chrome(self, mean_hex):
        st = self.STYLE
        self.form_inner.config(bg=mean_hex)
        for w in self.form_inner.winfo_children():
            if isinstance(w, tk.Label):
                w.config(bg=mean_hex)
            elif isinstance(w, tk.Button) and w is not self.start_btn:
                w.config(bg=mean_hex, activebackground=st["entry_bg"])

    def _layout_floating_panels(self, w, h):
        if self._bg_pil_canvas is None or w < 32 or h < 32:
            return
        m = self._SHELL_MARGIN
        gap = self._PANEL_GAP
        inner_w = max(200, w - 2 * m)
        inner_h = max(200, h - 2 * m)
        log_h = max(168, int(inner_h * 0.36))
        top_h = max(200, inner_h - log_h - gap)
        form_w = max(300, int(inner_w * 0.36))
        preview_w = max(220, inner_w - form_w - gap)

        fx, fy = m, m
        px, py = m + form_w + gap, m
        lx, ly = m, m + top_h + gap

        self.bg_canvas.coords(self._form_win, fx, fy)
        self.bg_canvas.itemconfigure(self._form_win, width=form_w, height=top_h)
        self.form_canvas.config(width=form_w, height=top_h)

        self.bg_canvas.coords(self._preview_win, px, py)
        self.bg_canvas.itemconfigure(self._preview_win, width=preview_w, height=top_h)

        self.bg_canvas.coords(self._log_win, lx, ly)
        self.bg_canvas.itemconfigure(self._log_win, width=inner_w, height=log_h)
        self.log_canvas.config(width=inner_w, height=log_h)

        pad = 10
        self.form_canvas.itemconfigure(
            self._form_inner_win,
            width=max(80, form_w - 2 * pad),
            height=max(80, top_h - 2 * pad),
        )
        self.form_canvas.coords(self._form_inner_win, pad, pad)

        log_title_h = 32
        tw = max(60, inner_w - 16)
        th = max(60, log_h - log_title_h - 12)
        self.log_canvas.itemconfigure(self._log_text_win, width=tw, height=th)
        self.log_canvas.coords(self._log_text_win, 8, log_title_h)

        self._sync_form_backdrop(fx, fy, form_w, top_h)
        self._sync_log_backdrop(lx, ly, inner_w, log_h, log_title_h)

    def _sync_form_backdrop(self, fx, fy, fw, fh):
        if self._bg_pil_canvas is None or fw < 2 or fh < 2:
            return
        cw, ch = self._bg_pil_canvas.size
        sub = self._bg_pil_canvas.crop(
            (max(0, fx), max(0, fy), min(cw, fx + fw), min(ch, fy + fh))
        )
        self._form_panel_photo = ImageTk.PhotoImage(sub)
        self.form_canvas.delete("backdrop")
        self.form_canvas.create_image(0, 0, anchor="nw", image=self._form_panel_photo, tags="backdrop")
        self.form_canvas.tag_lower("backdrop")
        self.form_canvas.tag_raise(self._form_inner_win)
        mean_hex = self._pil_mean_hex(sub)
        self._apply_form_transparency_chrome(mean_hex)

    def _sync_log_backdrop(self, lx, ly, lw, lh, title_h):
        st = self.STYLE
        if self._bg_pil_canvas is None or lw < 2 or lh < 2:
            return
        cw, ch = self._bg_pil_canvas.size
        sub = self._bg_pil_canvas.crop(
            (max(0, lx), max(0, ly), min(cw, lx + lw), min(ch, ly + lh))
        )
        self._log_panel_photo = ImageTk.PhotoImage(sub)
        self.log_canvas.delete("backdrop", "log_title")
        self.log_canvas.create_image(0, 0, anchor="nw", image=self._log_panel_photo, tags="backdrop")
        self.log_canvas.tag_lower("backdrop")
        self.log_canvas.create_text(
            14,
            10,
            anchor="nw",
            text="日志",
            fill=st["text"],
            font=self.FONT_UI_BOLD,
            tags="log_title",
        )
        self.log_canvas.tag_raise("log_title")
        self.log_canvas.tag_raise(self._log_text_win)
        blended = Image.blend(
            sub,
            Image.new("RGB", sub.size, (252, 250, 246)),
            0.34,
        )
        text_bg = self._pil_mean_hex(blended)
        self.text_widget.config(bg=text_bg, fg=st["log_fg"], highlightbackground=st["border"])

    def _redraw_background(self, w, h):
        if w < 2 or h < 2 or self._bg_image_raw is None:
            return
        iw, ih = self._bg_image_raw.size
        scale = max(w / iw, h / ih)
        nw = max(1, int(iw * scale))
        nh = max(1, int(ih * scale))
        img = self._bg_image_raw.resize((nw, nh), Image.Resampling.LANCZOS)
        left = max(0, (nw - w) // 2)
        top = max(0, (nh - h) // 2)
        img = img.crop((left, top, left + w, top + h))
        st = self.STYLE
        radius = float(st.get("bg_blur_radius", 8))
        blend = float(st.get("bg_frost_blend", 0.22))
        frost = st.get("bg_frost_rgb", (237, 232, 223))
        if radius > 0:
            img = img.filter(ImageFilter.GaussianBlur(radius=radius))
        if blend > 0:
            frost_img = Image.new("RGB", img.size, frost)
            img = Image.blend(img, frost_img, min(1.0, max(0.0, blend)))
        self._bg_pil_canvas = img
        self._bg_photo = ImageTk.PhotoImage(img)
        self.bg_canvas.delete("background")
        self.bg_canvas.create_image(0, 0, anchor="nw", image=self._bg_photo, tags="background")
        self.bg_canvas.tag_lower("background")
        self._layout_floating_panels(w, h)

    def _on_canvas_configure(self, event):
        if event.widget is not self.bg_canvas:
            return
        w, h = event.width, event.height
        if w < 4 or h < 4:
            return
        self._redraw_background(w, h)

    def embed_vlc_player(self, widget):
        """将 VLC 视频输出绑定到 Tk 控件（Windows: HWND；Linux: X window id）。"""
        if self.player is None:
            return
        try:
            self.root.update_idletasks()
            hid = widget.winfo_id()
            if widget.winfo_width() <= 1 or widget.winfo_height() <= 1:
                return
            if os.name == "nt":
                self.player.set_hwnd(int(hid))
            else:
                self.player.set_xwindow(int(hid))
        except Exception as e:
            print(f"VLC 绑定预览窗口失败: {e}")

    def _initial_vlc_embed(self):
        if self.player is not None:
            self.embed_vlc_player(self.video_host)

    def _on_video_host_configure(self, event):
        if event.widget is not self.video_host:
            return
        if self.player is None or self._video_mode != "vlc":
            return
        if self._reembed_job is not None:
            try:
                self.root.after_cancel(self._reembed_job)
            except Exception:
                pass
        self._reembed_job = self.root.after(120, self._do_vlc_reembed)

    def _do_vlc_reembed(self):
        self._reembed_job = None
        if self.player is not None and self._video_mode == "vlc" and self.current_video_path:
            self.embed_vlc_player(self.video_host)

    def _show_video_placeholder(self):
        self.video_placeholder.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.video_placeholder.lift()

    def _prepare_preview_for_new_run(self):
        self._stop_cv_preview()
        self._video_mode = None
        if self.player is not None:
            try:
                self.player.stop()
            except Exception:
                pass
        self._show_video_placeholder()

    def _stop_cv_preview(self):
        if self._cv_job is not None:
            try:
                self.root.after_cancel(self._cv_job)
            except Exception:
                pass
            self._cv_job = None
        if self._cv_cap is not None:
            try:
                self._cv_cap.release()
            except Exception:
                pass
            self._cv_cap = None
        if self.cv_label is not None:
            try:
                self.cv_label.pack_forget()
            except Exception:
                pass

    def _start_cv_preview(self, path):
        """无 python-vLC 或 VLC 失败时，用 OpenCV 在窗口内逐帧显示（无系统音频）。"""
        self._stop_cv_preview()
        self.video_placeholder.place_forget()
        self._video_mode = "cv"
        if self.cv_label is None:
            self.cv_label = tk.Label(self.video_host, bg=self.STYLE["video_bg"], bd=0)
        self.cv_label.pack(fill=tk.BOTH, expand=True)
        self._cv_cap = cv2.VideoCapture(str(path))
        if not self._cv_cap.isOpened():
            print("OpenCV 无法打开视频，将尝试系统播放器")
            self._video_mode = None
            self._show_video_placeholder()
            return
        self._cv_preview_tick()

    def _cv_preview_tick(self):
        if self._cv_cap is None or self._video_mode != "cv":
            return
        ok, frame = self._cv_cap.read()
        if not ok:
            self._cv_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._cv_cap.read()
        if not ok:
            self._cv_job = self.root.after(100, self._cv_preview_tick)
            return
        self.video_host.update_idletasks()
        w = max(2, self.video_host.winfo_width())
        h = max(2, self.video_host.winfo_height())
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
        im = Image.fromarray(frame)
        self._cv_photo = ImageTk.PhotoImage(image=im)
        self.cv_label.config(image=self._cv_photo)
        self._cv_job = self.root.after(33, self._cv_preview_tick)

    def poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.text_widget.insert(tk.END, msg)
                self.text_widget.see(tk.END)
        except queue.Empty:
            pass
        self.root.after(100, self.poll_log_queue)

    def on_start(self):
        if getattr(self, "worker", None) and self.worker.is_alive():
            messagebox.showinfo("提示", "生成任务正在进行中...")
            return
        self._prepare_preview_for_new_run()
        timbre = (self.timbre_path_var.get() or "").strip()
        emotion = (self.emotion_path_var.get() or "").strip()
        user_txt = (self.user_txt_var.get() or "").strip()
        if timbre and not Path(timbre).is_file():
            messagebox.showwarning("文件无效", "所选音色文件不存在或无法访问")
            return
        if emotion and not Path(emotion).is_file():
            messagebox.showwarning("文件无效", "所选情感文件不存在或无法访问")
            return
        if user_txt and not Path(user_txt).is_file():
            messagebox.showwarning("文件无效", "所选文本文件不存在或无法访问")
            return
        bg_path = (self.bg_path_var.get() or "").strip() or "./95.jpg"
        if not bg_path.lower().endswith((".jpg", ".jpeg")):
            messagebox.showwarning("格式不支持", "请选择 JPG/JPEG 格式的图片作为背景图")
            return
        bg_paths = [bg_path]
        self.start_btn.config(state=tk.DISABLED)
        self.worker = threading.Thread(
            target=self.run_generation,
            args=(bg_paths, timbre or None, emotion or None, user_txt or None),
            daemon=True,
        )
        self.worker.start()

    def choose_timbre(self):
        path = filedialog.askopenfilename(
            title="选择音色参考音频",
            filetypes=[("Audio", "*.mp3;*.wav;*.m4a"), ("All files", "*.*")],
        )
        if path:
            self.timbre_path_var.set(path)

    def choose_emotion(self):
        path = filedialog.askopenfilename(
            title="选择情感参考音频",
            filetypes=[("Audio", "*.mp3;*.wav;*.m4a"), ("All files", "*.*")],
        )
        if path:
            self.emotion_path_var.set(path)

    def choose_user_txt(self):
        path = filedialog.askopenfilename(
            title="选择文本文件",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self.user_txt_var.set(path)

    def choose_bg(self):
        path = filedialog.askopenfilename(
            title="选择背景图 (JPG)",
            filetypes=[("JPEG Images", "*.jpg;*.jpeg")]
        )
        if not path:
            return
        if not path.lower().endswith((".jpg", ".jpeg")):
            messagebox.showwarning("格式不支持", "请选择 JPG/JPEG 格式的图片")
            return
        self.bg_path_var.set(path)

    def run_generation(self, bg_paths, timbre_path, emotion_path, user_txt_path):
        try:
            self.current_video_path = None

            def on_video_ready(path):
                self.current_video_path = path
                self.root.after(0, self.play_video)
            out = generate_workflow(
                bg_paths,
                timbre_path=timbre_path,
                emotion_path=emotion_path,
                user_txt_path=user_txt_path,
                on_video_ready=on_video_ready,
            )
            if not out:
                self.root.after(
                    0,
                    lambda: messagebox.showwarning(
                        "未生成视频",
                        "没有可播放的合并视频。常见原因：IndexTTS2 未返回音频、Gradio 未启动，或本批全部分段合成失败。请查看下方日志。",
                    ),
                )
        except Exception as e:
            print(f"生成失败: {e}")
        finally:
            self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))

    def play_video(self):
        if not self.current_video_path or not Path(self.current_video_path).is_file():
            return
        path = str(Path(self.current_video_path).resolve())
        self._stop_cv_preview()
        self.video_placeholder.place_forget()
        self.root.update_idletasks()

        if self.player is not None:
            try:
                self.embed_vlc_player(self.video_host)
                media = self.player_instance.media_new(path)
                self.player.set_media(media)
                self.player.play()
                self._video_mode = "vlc"
                return
            except Exception as e:
                print(f"VLC 内嵌播放失败，改用 OpenCV 预览: {e}")

        self._start_cv_preview(path)
        if self._video_mode != "cv" and not open_video_external(path):
            print(
                "无法内嵌或打开视频。请安装 VLC 与 python-vlc，或检查 OpenCV 与文件路径；"
                f"文件位置: {path}"
            )

    def on_close(self):
        self._prepare_preview_for_new_run()
        try:
            sys.stdout = self.stdout_backup
            sys.stderr = self.stderr_backup
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = AppGUI(root)
    root.mainloop()