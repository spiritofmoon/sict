
# 此脚本使用鼠标侧键控制录制。
# CSV事件日志的格式已恢复为 v7_0_3.py 的通用六列格式。

import dxcam
import time
import av
import csv
import os
import psutil
import queue
from fractions import Fraction
import multiprocessing as mp
from pynput import mouse, keyboard

# --- 配置参数 ---
OUTPUT_FOLDER_PATH = r"Y:\jist_dataset\simple\50"
VIDEO_FILENAME = os.path.join(OUTPUT_FOLDER_PATH, "final_output.mp4")
EVENTS_FILENAME = os.path.join(OUTPUT_FOLDER_PATH, "input_events.csv")
SYNC_TIME_FILENAME = os.path.join(OUTPUT_FOLDER_PATH, "video_start_time.txt")
REGION = (0, 0, 1920, 1080)


# ==============================================================================
# 进程 1: 屏幕捕获 (生产者) - 无改动
# ==============================================================================
def capture_process(frame_queue: mp.Queue, region: tuple, start_event: mp.Event, stop_event: mp.Event):
    """在一个独立的进程中运行，等待开始信号，然后捕获屏幕直到停止信号发出。"""
    try:
        p = psutil.Process(os.getpid())
        p.nice(psutil.HIGH_PRIORITY_CLASS)
        print(f"[捕获进程] 优先级已提升。")
    except Exception as e:
        print(f"[捕获进程] 提升优先级失败: {e}")

    print("[捕获进程] 等待开始信号 (请按 鼠标侧键2)...")
    start_event.wait()

    print("[捕获进程] 收到开始信号，将在 1 秒后开始录制...")
    time.sleep(1)

    print("[捕获进程] 初始化 DXCam...")
    camera = dxcam.create(output_color="BGR")
    if camera is None:
        stop_event.set()
        return

    camera.start(region=region, video_mode=True, target_fps=120)
    print("[捕获进程] --- 捕获进行中 (按 鼠标侧键1 停止) ---")
    frame_count = 0

    while not stop_event.is_set():
        frame = camera.get_latest_frame()
        if frame is not None:
            capture_time_ns = time.perf_counter_ns()
            try:
                frame_queue.put((frame.copy(), capture_time_ns), block=False)
                frame_count += 1
            except mp.queues.Full:
                pass

    camera.stop()
    print(f"\n[捕获进程] --- 捕获结束，共捕获 {frame_count} 帧 ---")
    frame_queue.put(None)
    frame_queue.close()
    frame_queue.join_thread()
    print("[捕获进程] 进程即将退出。")


# ==============================================================================
# 进程 2: 视频编码 (消费者) - 无改动
# ==============================================================================
def encode_process(frame_queue: mp.Queue, output_path: str, sync_time_path: str, width: int, height: int):
    """在另一个独立的进程中运行，负责从队列中取出帧并编码成视频。"""
    print("[编码进程] --- 等待第一帧以开始编码 ---")
    start_time_ns = None

    try:
        with av.open(output_path, mode='w') as container:
            stream = container.add_stream('libx264', rate=None)
            stream.width = width
            stream.height = height
            stream.pix_fmt = 'yuv420p'
            stream.options = {'preset': 'ultrafast', 'crf': '18'}
            stream.time_base = Fraction(1, 1_000_000_000)

            frame_count = 0
            while True:
                item = frame_queue.get()
                if item is None:
                    print("\n[编码进程] 收到结束信号。")
                    break

                frame_data, capture_time_ns = item
                if start_time_ns is None:
                    start_time_ns = capture_time_ns
                    print("[编码进程] 收到第一帧，编码开始！")
                    try:
                        with open(sync_time_path, 'w') as f:
                            f.write(str(start_time_ns))
                        print(f"[编码进程] 已将同步时间点写入 {sync_time_path}")
                    except Exception as e:
                        print(f"[编码进程] 写入同步时间失败: {e}")

                frame = av.VideoFrame.from_ndarray(frame_data, format='bgr24')
                frame.pts = capture_time_ns - start_time_ns
                for packet in stream.encode(frame):
                    container.mux(packet)
                frame_count += 1
                print(f"\r[编码进程] 已编码帧数: {frame_count}", end="")

            for packet in stream.encode():
                container.mux(packet)
            print(f"\n[编码进程] --- 编码完成，已保存到 {output_path} ---")
    except Exception as e:
        print(f"\n[编码进程] 编码出错: {e}")


# ==============================================================================
# 进程 3: 输入事件监听 (总指挥) - **此部分已更新**
# ==============================================================================
def input_listener_process(output_csv_path: str, start_event: mp.Event, stop_event: mp.Event):
    """
    在第三个进程中运行，监听所有输入事件并写入CSV。
    CSV格式已恢复为 v7_0_3.py 的通用六列格式。
    """
    print("[输入进程] --- 输入监听已启动 ---")
    print("[输入进程] 请按 鼠标侧键2 (前进键) 开始录制...")

    is_recording_started = False
    k_listener = None
    m_listener = None

    try:
        with open(output_csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            # 写入与 v7_0_3.py 完全相同的表头
            writer.writerow(['timestamp_ns', 'event_type', 'param1', 'param2', 'param3', 'param4'])

            # --- 定义事件处理函数 ---
            def on_key_action(key, action_type):
                """处理键盘按下和释放，并按指定格式写入CSV"""
                timestamp = time.perf_counter_ns()
                key_str = str(key)
                # 写入标准6元组，多余参数为None
                writer.writerow([timestamp, action_type, key_str, None, None, None])

            def on_click(x, y, button, pressed):
                """记录鼠标点击事件，并处理开始/停止逻辑"""
                nonlocal is_recording_started
                timestamp = time.perf_counter_ns()

                # 写入标准6元组，按需填充参数
                action_type = 'mouse_press' if pressed else 'mouse_release'
                button_str = str(button)
                writer.writerow([timestamp, action_type, x, y, button_str, None])

                # 只在“按下”时触发控制逻辑
                if not pressed:
                    return

                # --- 控制逻辑 ---
                if button == mouse.Button.x2 and not is_recording_started:
                    print("[输入进程] 检测到开始键 (侧键2)！发送开始信号...")
                    start_event.set()
                    is_recording_started = True
                elif button == mouse.Button.x1 and is_recording_started:
                    print("[输入进程] 检测到停止键 (侧键1)！发送停止信号并退出...")
                    stop_event.set()
                    if k_listener: k_listener.stop()
                    if m_listener: m_listener.stop()

            # --- 启动监听器 ---
            # 使用 lambda 来区分按下和释放事件
            k_listener = keyboard.Listener(
                on_press=lambda key: on_key_action(key, 'key_press'),
                on_release=lambda key: on_key_action(key, 'key_release')
            )
            m_listener = mouse.Listener(on_click=on_click)

            k_listener.start()
            m_listener.start()

            k_listener.join()
            m_listener.join()

    except Exception as e:
        print(f"[输入进程] 发生错误: {e}")
        if not stop_event.is_set():
            stop_event.set()

    print("[输入进程] 监听已结束，进程即将退出。")


# ==============================================================================
# 主进程: 负责启动、协调和等待所有子进程 - 无改动
# ==============================================================================
if __name__ == "__main__":
    mp.freeze_support()

    os.makedirs(OUTPUT_FOLDER_PATH, exist_ok=True)

    frame_queue = mp.Queue(maxsize=300)
    start_event = mp.Event()
    stop_event = mp.Event()

    print("[主进程] 获取视频尺寸...")
    try:
        temp_cam = dxcam.create(region=REGION)
        if temp_cam is None: raise Exception("DXCam 创建失败")
        frame_sample = temp_cam.grab()
        if frame_sample is None: raise Exception("无法捕获样本帧。")
        h, w, _ = frame_sample.shape
        temp_cam.release()
        del temp_cam, frame_sample
        print(f"[主进程] 视频尺寸: {w}x{h}")
    except Exception as e:
        print(f"[主进程] 错误: {e}")
        exit()

    capture_proc = mp.Process(target=capture_process, args=(frame_queue, REGION, start_event, stop_event))
    encode_proc = mp.Process(target=encode_process, args=(frame_queue, VIDEO_FILENAME, SYNC_TIME_FILENAME, w, h))
    listener_proc = mp.Process(target=input_listener_process, args=(EVENTS_FILENAME, start_event, stop_event))

    print("\n[主进程] 启动所有进程...")
    listener_proc.start()
    capture_proc.start()
    encode_proc.start()

    print("[主进程] 所有进程已启动。等待录制完成...")
    capture_proc.join()
    encode_proc.join()
    listener_proc.join()

    print("\n[主进程] 所有任务完成！视频、事件日志和同步文件已保存。")
