
import dxcam
import time
import av
import csv
import os
import psutil  # Used for setting process priorities
import queue  # Standard queue for inter-thread communication within a process
import input_module_all_inf as input_module
from fractions import Fraction
import multiprocessing as mp

# --- 配置参数 ---
CAPTURE_DURATION = 20  # 录制总时长（秒）
VIDEO_FILENAME = r"D:\pyprogect\video_model\get_screen_captrue_and_mouse_keyboard_events\v7\1080p_3600_1000hzmouseinput\final_output.mp4"
EVENTS_FILENAME = r"D:\pyprogect\video_model\get_screen_captrue_and_mouse_keyboard_events\v7\1080p_3600_1000hzmouseinput\input_events.csv"
SYNC_TIME_FILENAME = r"D:\pyprogect\video_model\get_screen_captrue_and_mouse_keyboard_events\v7\1080p_3600_1000hzmouseinput\video_start_time.txt"  # 用于存储同步时间点
REGION = (0, 0, 1920, 1080)  # 录制区域


# ==============================================================================
# 进程 1: 屏幕捕获 (生产者)
# ==============================================================================
def capture_process(frame_queue: mp.Queue, region: tuple, duration: int):
    """在一个独立的进程中运行，负责捕获屏幕并把帧放入进程队列。"""
    try:
        p = psutil.Process(os.getpid())
        p.nice(psutil.HIGH_PRIORITY_CLASS)
        print(f"[Capture Process] 优先级已提升。")
    except Exception as e:
        print(f"[Capture Process] 提升优先级失败: {e}")

    print("[Capture Process] 初始化 DXCam...")
    camera = dxcam.create(output_color="BGR")
    if camera is None: return

    camera.start(region=region, video_mode=True, target_fps=120)
    print("[Capture Process] --- 捕获进行中 ---")
    start_capture_time = time.time()
    frame_count = 0

    while time.time() - start_capture_time < duration:
        frame = camera.get_latest_frame()
        if frame is not None:
            capture_time_ns = time.perf_counter_ns()
            frame_queue.put((frame.copy(), capture_time_ns))
            frame_count += 1

    camera.stop()
    print(f"[Capture Process] --- 捕获在 {duration} 秒后结束，共捕获 {frame_count} 帧 ---")

    print("[Capture Process] 发送结束信号到队列。")
    frame_queue.put(None)

    # --- 确保所有数据被刷新到管道，防止数据丢失 ---
    print("[Capture Process] 正在关闭队列并等待数据刷新...")
    frame_queue.close()
    frame_queue.join_thread()
    # ---------------------------------------------

    print("[Capture Process] 数据刷新完成，进程即将退出。")


# ==============================================================================
# 进程 2: 视频编码 (消费者)
# ==============================================================================
def encode_process(frame_queue: mp.Queue, output_path: str, sync_time_path: str, width: int, height: int):
    """在另一个独立的进程中运行，负责从队列中取出帧并编码成视频。"""
    print("[Encode Process] --- 等待第一帧以开始编码 ---")
    start_time_ns = None

    try:
        with av.open(output_path, mode='w') as container:
            stream = container.add_stream('libx264', rate=None)
            stream.width = width
            stream.height = height
            stream.pix_fmt = 'yuv420p'
            stream.time_base = Fraction(1, 1_000_000_000)

            frame_count = 0
            while True:
                item = frame_queue.get()
                if item is None:
                    print("\n[Encode Process] 收到结束信号。")
                    break

                frame_data, capture_time_ns = item
                if start_time_ns is None:
                    start_time_ns = capture_time_ns
                    print("[Encode Process] 收到第一帧，编码开始！")

                    # --- 将视频的绝对开始时间写入文件，用于后续同步 ---
                    try:
                        with open(sync_time_path, 'w') as f:
                            f.write(str(start_time_ns))
                        print(f"[Encode Process] 已将同步时间点写入 {sync_time_path}")
                    except Exception as e:
                        print(f"[Encode Process] 写入同步时间失败: {e}")
                    # ------------------------------------------------

                frame = av.VideoFrame.from_ndarray(frame_data, format='bgr24')
                frame.pts = capture_time_ns - start_time_ns

                for packet in stream.encode(frame):
                    container.mux(packet)

                frame_count += 1
                print(f"\r[Encode Process] 已编码帧数: {frame_count}", end="")

            for packet in stream.encode():
                container.mux(packet)

            print(f"\n[Encode Process] --- 编码完成，已保存到 {output_path} ---")

    except Exception as e:
        print(f"\n[Encode Process] 编码出错: {e}")


# ==============================================================================
# 进程 3: 输入事件监听 (独立的生产者)
# ==============================================================================
def input_listener_process(output_csv_path: str):
    """在第三个进程中运行，监听输入事件并写入CSV文件。"""
    try:
        p = psutil.Process(os.getpid())
        p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        print(f"[Input Process] 优先级已降低。")
    except Exception as e:
        print(f"[Input Process] 降低优先级失败: {e}")

    print("[Input Process] --- 输入监听已启动 ---")
    event_queue = queue.Queue()

    def event_handler_callback(data_tuple):
        event_queue.put(data_tuple)

    input_module.start_listener(event_handler_callback)

    with open(output_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp_ns', 'event_type', 'param1', 'param2', 'param3', 'param4'])

        while True:
            try:
                event_data = event_queue.get(timeout=1.0)
                writer.writerow(event_data)
            except queue.Empty:
                continue


# ==============================================================================
# 主进程: 负责启动、协调和停止所有子进程
# ==============================================================================
if __name__ == "__main__":
    mp.freeze_support()

    # 1. 为视频帧创建进程间队列
    frame_queue = mp.Queue(maxsize=240)

    # 2. 预先获取屏幕尺寸
    print("[Main Process] 获取视频尺寸...")
    temp_cam = dxcam.create()
    if temp_cam is None: exit()
    frame_sample = temp_cam.grab(REGION)
    if frame_sample is None:
        print("[Main Process] 无法捕获样本帧，请检查屏幕是否开启。")
        temp_cam.stop()
        exit()
    h, w, _ = frame_sample.shape
    # --- 确保临时dxcam实例被正确关闭 ---
    temp_cam.stop()
    del temp_cam, frame_sample
    print(f"[Main Process] 视频尺寸: {w}x{h}")

    # 3. 创建三个子进程
    capture_proc = mp.Process(target=capture_process, args=(frame_queue, REGION, CAPTURE_DURATION))
    encode_proc = mp.Process(target=encode_process, args=(frame_queue, VIDEO_FILENAME, SYNC_TIME_FILENAME, w, h))
    listener_proc = mp.Process(target=input_listener_process, args=(EVENTS_FILENAME,))

    # 4. 启动所有进程
    print("[Main Process] 启动所有进程...")
    capture_proc.start()
    encode_proc.start()
    listener_proc.start()

    # 5. 等待捕获和编码任务自己完成
    print(f"[Main Process] 等待捕获和编码任务完成...")
    capture_proc.join()
    encode_proc.join()
    print("[Main Process] 捕获和编码进程已全部结束。")

    # 6. 录制已完成，现在可以终止监听进程
    print("[Main Process] 正在终止输入监听进程...")
    listener_proc.terminate()
    listener_proc.join()

    print("\n[Main Process] 所有任务完成！视频、事件日志和同步文件已保存。")
