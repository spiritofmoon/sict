import av
import csv
import sys
from typing import List, Tuple

# --- 配置输入和输出文件名 ---
VIDEO_INPUT_PATH = r"1080p_jisuanqi_123add456\final_output.mp4"
EVENTS_INPUT_PATH = r"1080p_jisuanqi_123add456\input_events.csv"
SYNC_TIME_PATH = r"1080p_jisuanqi_123add456\video_start_time.txt"  # 新增：同步时间文件
OUTPUT_CSV_PATH = r"1080p_jisuanqi_123add456\frame_by_frame_analysis_final.csv"


def read_video_timestamps(video_path: str) -> List[int]:
    """
    读取视频文件，返回每一帧的时间戳列表（单位：纳秒）。
    """
    print(f"正在从 '{video_path}' 读取视频帧时间戳...")
    timestamps_ns = []
    try:
        with av.open(video_path, 'r') as container:
            stream = container.streams.video[0]
            # 确保时间基准是纳秒，与我们录制时设置的一致
            if stream.time_base.denominator != 1_000_000_000:
                print(f"警告: 视频时间基准不是纳秒 (1/{stream.time_base.denominator})，结果可能不精确。")

            for frame in container.decode(stream):
                # frame.pts 已经是纳秒单位的整数
                timestamps_ns.append(frame.pts)

        print(f"成功读取 {len(timestamps_ns)} 帧时间戳。")
        return timestamps_ns
    except FileNotFoundError:
        print(f"错误: 视频文件 '{video_path}' 未找到。")
        sys.exit(1)
    except Exception as e:
        print(f"读取视频时出错: {e}")
        sys.exit(1)


def read_input_events(csv_path: str) -> List[list]:
    """
    读取输入事件CSV文件，返回事件列表。
    时间戳已转换为整数纳秒。
    """
    print(f"正在从 '{csv_path}' 读取输入事件...")
    events = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader)  # 跳过表头
            for row in reader:
                # 将时间戳字符串转为整数纳秒
                row[0] = int(row[0])
                events.append(row)

        print(f"成功读取 {len(events)} 个输入事件。")
        return events
    except FileNotFoundError:
        print(f"错误: 事件文件 '{csv_path}' 未找到。")
        sys.exit(1)
    except Exception as e:
        print(f"读取CSV时出错: {e}")
        sys.exit(1)


# ==============================================================================
# === 核心修改部分：关联函数现在接收视频的绝对开始时间 ===
# ==============================================================================
def correlate_events_to_frames(frame_timestamps_relative: List[int], events_absolute: List[list], video_start_ns: int) -> List[dict]:
    """
    将事件列表关联到每个视频帧的时间间隔内。
    """
    if not frame_timestamps_relative: return []
    print("正在使用同步点关联事件与视频帧...")

    processed_data = []
    event_idx = 0

    for i in range(len(frame_timestamps_relative)):
        frame_start_relative_ns = frame_timestamps_relative[i]
        frame_end_relative_ns = frame_timestamps_relative[i + 1] if i + 1 < len(frame_timestamps_relative) else float('inf')

        frame_events = []
        # 查找所有落在这个时间区间的事件
        while event_idx < len(events_absolute):
            # 将事件的绝对时间戳转换为相对于视频开始的相对时间戳
            event_time_relative_ns = events_absolute[event_idx][0] - video_start_ns

            if frame_start_relative_ns <= event_time_relative_ns < frame_end_relative_ns:
                # 复制一份事件数据，并把相对时间戳也加进去
                event_data_copy = events_absolute[event_idx][:]
                event_data_copy[0] = event_time_relative_ns
                frame_events.append(event_data_copy)
                event_idx += 1
            elif event_time_relative_ns >= frame_end_relative_ns:
                break
            else:
                event_idx += 1

        duration_ms = (frame_end_relative_ns - frame_start_relative_ns) / 1e6 if frame_end_relative_ns != float('inf') else 0
        processed_data.append({
            "frame_index": i,
            "timestamp_sec": frame_start_relative_ns / 1e9,
            "duration_ms": duration_ms,
            "events": frame_events
        })

    print("关联完成。")
    return processed_data


def write_output_csv(output_path: str, processed_data: List[dict]):
    """
    将处理好的数据写入新的CSV文件。
    """
    print(f"正在将分析结果写入 '{output_path}'...")
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['frame_index', 'timestamp_sec', 'frame_duration_ms', 'events_in_frame'])

        for row_data in processed_data:
            # 将事件列表格式化为人类可读的字符串
            events_str = ""
            if row_data["events"]:
                # 过滤掉事件中的时间戳，只保留事件内容
                formatted_events = [f"({', '.join(map(str, e[1:]))})" for e in row_data["events"]]
                # 每个事件占一行，在单元格内换行以方便阅读
                events_str = "\n".join(formatted_events)

            writer.writerow([
                row_data["frame_index"],
                f"{row_data['timestamp_sec']:.6f}",
                f"{row_data['duration_ms']:.3f}",
                events_str
            ])
    print("写入完成！")


if __name__ == "__main__":
    # 1. 读取数据
    # 读取的是视频内部的相对时间戳 (0, 8333..., 1666...)
    frame_times_relative = read_video_timestamps(VIDEO_INPUT_PATH)
    # 读取的是事件的绝对时间戳 (87345..., 87346...)
    events_absolute = read_input_events(EVENTS_INPUT_PATH)

    # 2. 读取关键的同步点：视频的绝对开始时间
    try:
        with open(SYNC_TIME_PATH, 'r') as f:
            video_start_time_absolute_ns = int(f.read())
        print(f"成功读取视频绝对开始时间: {video_start_time_absolute_ns}")
    except FileNotFoundError:
        print(f"错误: 同步文件 '{SYNC_TIME_PATH}' 未找到！请先运行修改后的录制脚本。")
        sys.exit(1)

    # 3. 核心逻辑：传入同步点进行关联
    final_data = correlate_events_to_frames(frame_times_relative, events_absolute, video_start_time_absolute_ns)

    # 4. 写入结果
    write_output_csv(OUTPUT_CSV_PATH, final_data)

    print(f"\n所有处理已完成！请查看最终的分析文件: {OUTPUT_CSV_PATH}")
