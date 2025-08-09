# test.py
import input_module_all_inf as input_module
import time
import queue

# 使用队列来安全地在线程间传递数据
event_queue = queue.Queue()


def my_event_handler(data_tuple):
    # 这个函数会在C++的后台线程中被调用
    # 不要在这里做耗时操作，尽快将数据放入队列
    event_queue.put(data_tuple)


# 注册回调函数并启动监听
print("Starting input listener... Press any key or move the mouse.")
input_module.start_listener(my_event_handler)

# 在主线程中处理事件
print("Listening for 10 seconds...")
end_time = time.time() + 10
while time.time() < end_time:
    try:
        # 从队列中获取事件，设置超时以防永久阻塞
        event = event_queue.get(timeout=0.1)

        # 解析鼠标移动事件
        if event[1] == "mouse_move":
            timestamp, event_type, rel_x, rel_y, abs_x, abs_y = event
            print(f"[{timestamp}] {event_type}: Rel({rel_x}, {rel_y}), Abs({abs_x}, {abs_y})")
        # 解析鼠标点击和滚轮事件
        elif event[1] in ("mouse_down", "mouse_up", "mouse_wheel"):
            # 根据事件类型解包
            if event[1] == "mouse_wheel":
                timestamp, event_type, delta, abs_x, abs_y = event
                print(f"[{timestamp}] {event_type}: Delta({delta}), Abs({abs_x}, {abs_y})")
            else:
                timestamp, event_type, button, abs_x, abs_y = event
                print(f"[{timestamp}] {event_type}: Button({button}), Abs({abs_x}, {abs_y})")
        # 解析键盘事件
        else:
            timestamp, event_type, vkey = event
            print(f"[{timestamp}] {event_type}: VKey({vkey})")

    except queue.Empty:
        # 队列为空时，继续循环
        continue

print("Listener test finished.")