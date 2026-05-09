from gradio_client import Client, handle_file
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
from urllib.request import urlretrieve


def _local_path_from_string(s: str) -> str:
    """将 file:// URL 转为本地路径；其余原样返回。"""
    if not s.startswith("file://"):
        return s
    parsed = urlparse(s)
    path = unquote(parsed.path or "")
    if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return path or s


def _find_col(headers, *substrings) -> int | None:
    for i, h in enumerate(headers):
        hs = str(h).lower()
        for s in substrings:
            if s.lower() in hs:
                return i
    return None


def _find_job_row(job_id: str, table: dict) -> list | None:
    headers = table.get("headers")
    data = table.get("data")
    if not isinstance(headers, list) or not isinstance(data, list):
        return None
    idx_job = _find_col(headers, "job id", "job") or 0
    for row in data:
        if row and len(row) > idx_job and str(row[idx_job]) == str(job_id):
            return row
    return None


def _parse_job_in_queue_row(job_id: str, table: dict) -> tuple[str, str | None]:
    """
    解析队列表格中某 job 的状态。
    返回 (state, wav_cell)：state 为 done | pending | error | missing
    """
    if not isinstance(table, dict) or "data" not in table or "headers" not in table:
        return ("missing", None)
    headers = table["headers"]
    data = table["data"]
    if not isinstance(headers, list) or not isinstance(data, list):
        return ("missing", None)

    idx_job = _find_col(headers, "job id", "job") or 0
    idx_status = _find_col(headers, "status") or 1
    idx_result = _find_col(headers, "result", "error") or 4

    row = _find_job_row(job_id, table)
    if not row or len(row) <= max(idx_job, idx_status, idx_result):
        return ("missing", None)

    status = str(row[idx_status]).lower()
    cell = row[idx_result] if len(row) > idx_result else ""
    cell = (cell or "").strip() if isinstance(cell, str) else ""

    if status in ("error", "failed", "failure"):
        print(f"TTS2 任务失败 ({job_id}): {cell or row}")
        return ("error", None)
    if status == "done" and cell:
        if ".wav" in cell.lower():
            return ("done", cell)
        print(f"TTS2 已完成但 Result 非 wav: {cell}")
        return ("error", None)
    return ("pending", None)


def _poll_until_job_wav(
    client: Client,
    job_id: str,
    *,
    timeout: float | None = None,
    interval: float = 2.0,
) -> str | None:
    """
    IndexTTS2 在任务入队后异步推理，需反复调用 /refresh_all_outputs 刷新任务表，
    直到本 job_id 对应行 Status 为 done 且 Result 为 wav 路径。
    """
    if timeout is None:
        timeout = float(os.environ.get("INDEX_TTS2_POLL_TIMEOUT", "3600"))
    deadline = time.time() + timeout
    last_progress = ""
    while time.time() < deadline:
        try:
            out = client.predict(api_name="/refresh_all_outputs")
        except Exception as e:
            print(f"TTS2 刷新队列失败: {e}")
            time.sleep(interval)
            continue

        table = None
        if isinstance(out, (list, tuple)) and out and isinstance(out[0], dict):
            table = out[0]
        if not table:
            time.sleep(interval)
            continue

        state, wav_cell = _parse_job_in_queue_row(job_id, table)
        if state == "done" and wav_cell:
            return wav_cell
        if state == "error":
            return None

        row = _find_job_row(job_id, table)
        if row:
            headers = table.get("headers") or []
            i_st = _find_col(headers, "status") or 1
            i_pr = _find_col(headers, "progress") or 2
            prog = f"{row[i_st]} {row[i_pr] if len(row) > i_pr else ''}"
            if prog != last_progress:
                print(f"TTS2 等待合成 job={job_id}: {prog.strip()}")
                last_progress = prog
        else:
            if last_progress != "(无此行，队列可能已滚动)":
                print(f"TTS2 刷新表中暂未看到 job={job_id}，继续轮询…")
                last_progress = "(无此行，队列可能已滚动)"

        time.sleep(interval)

    print(f"TTS2 等待超时 ({timeout}s) job={job_id}")
    return None


def _gradio_file_urls(client: Client, rel_or_abs: str) -> list[str]:
    """尝试构造 Gradio 可下载的 file URL（不同版本路径略有差异）。"""
    base = client.src.rstrip("/")
    rel = rel_or_abs.replace("\\", "/").lstrip("/")
    enc = quote(rel, safe="/")
    enc_abs = quote(rel_or_abs.replace("\\", "/"), safe="/:/")
    urls = [
        f"{base}/file={enc}",
        f"{base}/file={enc_abs}",
        f"{base}/gradio_api/file={enc}",
        f"{base}/gradio_api/file={enc_abs}",
    ]
    seen: list[str] = []
    for u in urls:
        if u not in seen:
            seen.append(u)
    return seen


def _try_resolve_local_gradio_path(raw: str) -> str | None:
    """
    表格中的相对/绝对路径（如 outputs\\随时间消失的刺。刘同。我不赞成_1777624049.wav）。
    在客户端本机若存在对应文件则返回绝对路径；相对路径会按段拼接 INDEX_TTS2_HOME 等根目录。
    """
    raw = raw.strip()
    if not raw or raw.startswith(("http://", "https://")):
        return None

    p_norm = raw.replace("\\", "/")
    if os.path.isfile(raw):
        return os.path.abspath(raw)
    ap = os.path.abspath(p_norm.replace("/", os.sep))
    if os.path.isfile(ap):
        return ap

    parts = [x for x in p_norm.split("/") if x and x != "."]
    if not parts:
        return None

    roots: list[Path] = []
    for env in ("INDEX_TTS2_HOME", "INDEX_TTS2_ROOT", "GRADIO_SERVER_DIR"):
        v = os.environ.get(env)
        if v:
            roots.append(Path(v))
    # 本机常见安装路径；目录不存在则跳过。优先仍使用上面的环境变量。
    for fallback in (r"D:\SoftWare\indexTTS\index-tts-2",):
        fp = Path(fallback)
        if fp.is_dir():
            roots.append(fp)
    roots.append(Path.cwd())

    for root in roots:
        try:
            cand = root.joinpath(*parts).resolve()
        except (OSError, ValueError):
            continue
        if cand.is_file():
            return str(cand)
    return None


def _coerce_gradio_file_path(slot) -> str | None:
    """Gradio Audio/File 输出可能是 str 或含 path 的 dict。"""
    if slot is None:
        return None
    if isinstance(slot, str) and slot.strip():
        return slot.strip()
    if isinstance(slot, dict):
        p = slot.get("path") or slot.get("value")
        if isinstance(p, str) and p.strip():
            return p.strip()
    return None


def _pick_wav_path_after_done(client: Client, raw_from_table: str) -> str:
    """
    优先使用队列表格 Result 列路径；再尝试 /refresh_all_outputs 返回的「下载最新选中音频」
    （有时为服务器绝对路径，更利于本机复制）。
    """
    print(f"TTS2 Result 列路径: {raw_from_table}")
    out = None
    try:
        out = client.predict(api_name="/refresh_all_outputs")
    except Exception as e:
        print(f"TTS2 完成后刷新（取下载路径）跳过: {e}")
    if isinstance(out, (list, tuple)) and len(out) >= 3:
        alt = _coerce_gradio_file_path(out[2])
        if alt and os.path.isfile(alt):
            print(f"TTS2 使用刷新接口返回的本地文件: {alt}")
            return alt
        if alt:
            print(f"TTS2 刷新接口返回路径（将再尝试解析）: {alt}")
            return alt
    return raw_from_table


def _download_wav_from_gradio(client: Client, raw_cell: str, dest: Path) -> bool:
    """通过 HTTP 从 Gradio 拉取 outputs/xxx.wav（相对路径）。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    urls: list[str] = []
    if raw_cell.strip().startswith(("http://", "https://")):
        urls.append(raw_cell.strip())
    urls.extend(_gradio_file_urls(client, raw_cell))

    last_err: Exception | None = None
    tried = set()
    for url in urls:
        if url in tried:
            continue
        tried.add(url)
        try:
            urlretrieve(url, str(dest))
            if dest.is_file() and dest.stat().st_size > 0:
                return True
        except Exception as e:
            last_err = e
    if last_err:
        print(f"TTS2 通过 HTTP 拉取音频失败: {last_err}")
    print(
        "若 Gradio 与脚本不同工作目录，请设置环境变量 INDEX_TTS2_HOME 为 IndexTTS2 项目根目录，"
        "或确认浏览器中能打开对应音频文件。"
    )
    return False


def _save_local_to_dest(src: str, dest: Path) -> bool:
    """从本地路径复制或移动到 dest。"""
    src = _local_path_from_string(src)
    if not os.path.isfile(src):
        print(f"TTS2 源文件不存在: {src}")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(src, str(dest))
    except OSError:
        try:
            shutil.copy2(src, str(dest))
            try:
                os.unlink(src)
            except OSError:
                pass
        except OSError as e:
            print(f"TTS2 保存音频失败: {e}")
            return False
    ok = dest.is_file() and dest.stat().st_size > 0
    if not ok:
        print(f"TTS2 目标无效或为空: {dest}")
    return ok


_client = None


def _get_tts_client():
    global _client
    if _client is None:
        _client = Client("http://localhost:7860/")
    return _client


def getnowtime():
    formattrd_time = datetime.now()
    print(formattrd_time)
    return formattrd_time.strftime("%p") + formattrd_time.strftime("%Y-%m-%d") + formattrd_time.strftime("%H%M%S")


def send_LLM_indexTTS2(prompt, emo_ref_path, content, hotfilename) -> Path | None:
    """
    调用本地 IndexTTS2 Gradio。hotfilename 为不含扩展名的完整路径（与 txt 同主名）。

    /submit_and_refresh 仅提交任务并返回队列快照（常为 queued），推理在后台进行；
    因此提交后必须用 /refresh_all_outputs 轮询，直到该 job_id 行为 done 再取 Result 中的 wav。
    """
    dest = Path(hotfilename).with_suffix(".wav")
    client = _get_tts_client()
    kwargs = dict(
        voices_dropdown="使用参考音频",
        speed=1.0,
        emo_control_method="与音色参考音频相同",
        prompt=handle_file(prompt),
        text=content,
        emo_ref_path=handle_file(emo_ref_path),
        emo_weight=1,
        emo_text="",
        emo_random=False,
        max_tokens=100,
        vec1=0,
        vec2=0,
        vec3=0,
        vec4=0,
        vec5=0,
        vec6=0,
        vec7=0,
        vec8=0,
        do_sample=True,
        top_p=0.8,
        top_k=30,
        temperature=0.8,
        length_penalty=0,
        num_beams=3,
        repetition_penalty=10,
        max_mel=1500,
        api_name="/submit_and_refresh",
    )
    try:
        result = client.predict(**kwargs)
        print("submit_and_refresh:", result)

        if not isinstance(result, (list, tuple)) or len(result) < 2:
            print("TTS2 提交返回值格式异常:", type(result))
            return None

        job_id = str(result[0])
        raw_cell = _poll_until_job_wav(client, job_id)
        if not raw_cell:
            print("TTS2 轮询结束仍未获得 wav，job_id=", job_id)
            return None

        raw_cell = _pick_wav_path_after_done(client, raw_cell)
        local = _try_resolve_local_gradio_path(raw_cell)
        if local:
            if _save_local_to_dest(local, dest):
                print("TTS2 合成成功:", dest)
                return dest.resolve()
            return None
        if _download_wav_from_gradio(client, raw_cell, dest):
            print("TTS2 合成成功（HTTP）:", dest)
            return dest.resolve()
        return None
    except Exception as e:
        print(f"TTS2 调用异常: {e}")
        return None
