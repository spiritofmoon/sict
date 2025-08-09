// input_module.cpp
#include <pybind11/pybind11.h>
#include <pybind11/functional.h>
#include <Windows.h>
#include <thread>
#include <functional>
#include <vector>

namespace py = pybind11;

// --- 全局变量 ---
std::function<void(py::tuple)> g_callback;
LARGE_INTEGER g_perf_frequency;

// --- C++核心逻辑 ---
uint64_t get_timestamp_ns() {
    LARGE_INTEGER count;
    QueryPerformanceCounter(&count);
    uint64_t seconds = count.QuadPart / g_perf_frequency.QuadPart;
    uint64_t remainder = count.QuadPart % g_perf_frequency.QuadPart;
    uint64_t nano_part = (remainder * 1000000000) / g_perf_frequency.QuadPart;
    return (seconds * 1000000000) + nano_part;
}

LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
        case WM_INPUT: {
            UINT dwSize = 0;
            GetRawInputData((HRAWINPUT)lParam, RID_INPUT, NULL, &dwSize, sizeof(RAWINPUTHEADER));
            if (dwSize == 0) return 0;

            std::vector<BYTE> buffer(dwSize);
            if (GetRawInputData((HRAWINPUT)lParam, RID_INPUT, buffer.data(), &dwSize, sizeof(RAWINPUTHEADER)) != dwSize) {
                return 0;
            }

            auto* raw = (RAWINPUT*)buffer.data();
            uint64_t timestamp = get_timestamp_ns();

            py::gil_scoped_acquire acquire;

            if (raw->header.dwType == RIM_TYPEMOUSE) {
                // === 新增: 获取鼠标绝对坐标 ===
                POINT cursor_pos;
                GetCursorPos(&cursor_pos);
                // ============================

                const auto& mouse = raw->data.mouse;

                // 1. 处理鼠标移动 (数据包中加入绝对坐标)
                if (mouse.lLastX != 0 || mouse.lLastY != 0) {
                    // === 修改: 新增 cursor_pos.x 和 cursor_pos.y ===
                    g_callback(py::make_tuple(timestamp, "mouse_move", mouse.lLastX, mouse.lLastY, cursor_pos.x, cursor_pos.y));
                }

                // 2. 处理鼠标按键 (数据包中加入绝对坐标)
                USHORT flags = mouse.usButtonFlags;
                // === 修改: 为所有按键事件新增 cursor_pos.x 和 cursor_pos.y ===
                if (flags & RI_MOUSE_LEFT_BUTTON_DOWN)   g_callback(py::make_tuple(timestamp, "mouse_down", "left", cursor_pos.x, cursor_pos.y));
                if (flags & RI_MOUSE_LEFT_BUTTON_UP)     g_callback(py::make_tuple(timestamp, "mouse_up", "left", cursor_pos.x, cursor_pos.y));
                if (flags & RI_MOUSE_RIGHT_BUTTON_DOWN)  g_callback(py::make_tuple(timestamp, "mouse_down", "right", cursor_pos.x, cursor_pos.y));
                if (flags & RI_MOUSE_RIGHT_BUTTON_UP)    g_callback(py::make_tuple(timestamp, "mouse_up", "right", cursor_pos.x, cursor_pos.y));
                if (flags & RI_MOUSE_MIDDLE_BUTTON_DOWN) g_callback(py::make_tuple(timestamp, "mouse_down", "middle", cursor_pos.x, cursor_pos.y));
                if (flags & RI_MOUSE_MIDDLE_BUTTON_UP)   g_callback(py::make_tuple(timestamp, "mouse_up", "middle", cursor_pos.x, cursor_pos.y));

                // 3. 处理滚轮事件 (数据包中加入绝对坐标)
                if (flags & RI_MOUSE_WHEEL) {
                    short wheel_delta = (short)mouse.usButtonData;
                    // === 修改: 新增 cursor_pos.x 和 cursor_pos.y ===
                    g_callback(py::make_tuple(timestamp, "mouse_wheel", wheel_delta, cursor_pos.x, cursor_pos.y));
                }

            } else if (raw->header.dwType == RIM_TYPEKEYBOARD) {
                const auto& kbd = raw->data.keyboard;
                if (kbd.Flags == RI_KEY_MAKE) {
                    g_callback(py::make_tuple(timestamp, "key_down", kbd.VKey));
                } else if (kbd.Flags == RI_KEY_BREAK) {
                    g_callback(py::make_tuple(timestamp, "key_up", kbd.VKey));
                }
            }
            return 0;
        }
        case WM_DESTROY:
            PostQuitMessage(0);
            break;
        default:
            return DefWindowProc(hwnd, msg, wParam, lParam);
    }
    return 0;
}

void run_message_loop() {
    const wchar_t* CLASS_NAME = L"PyInputListenerWindowClass";
    WNDCLASSEXW wc = {0};
    wc.cbSize = sizeof(WNDCLASSEXW);
    wc.lpfnWndProc = WndProc;
    wc.hInstance = GetModuleHandle(NULL);
    wc.lpszClassName = CLASS_NAME;

    if (!RegisterClassExW(&wc)) { return; }

    HWND hwnd = CreateWindowExW(0, CLASS_NAME, L"Python Raw Input Listener", 0, 0, 0, 0, 0, HWND_MESSAGE, NULL, NULL, NULL);
    if (hwnd == NULL) { return; }

    RAWINPUTDEVICE rids[2];
    rids[0].usUsagePage = 0x01;
    rids[0].usUsage = 0x02;
    rids[0].dwFlags = RIDEV_INPUTSINK;
    rids[0].hwndTarget = hwnd;
    rids[1].usUsagePage = 0x01;
    rids[1].usUsage = 0x06;
    rids[1].dwFlags = RIDEV_INPUTSINK;
    rids[1].hwndTarget = hwnd;

    if (!RegisterRawInputDevices(rids, 2, sizeof(RAWINPUTDEVICE))) { return; }

    MSG msg;
    while (GetMessage(&msg, NULL, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessage(&msg);
    }
}

void start_listener(std::function<void(py::tuple)> callback) {
    if (g_callback) return;
    g_callback = callback;
    std::thread listener_thread(run_message_loop);
    listener_thread.detach();
}

PYBIND11_MODULE(input_module_all_inf, m) {
    m.doc() = "A high-performance keyboard and mouse listener module.";
    if (!QueryPerformanceFrequency(&g_perf_frequency)) {
        throw std::runtime_error("High-resolution performance counter not available.");
    }
    m.def("start_listener", &start_listener, "Starts the input listener in a background thread.",
          py::arg("callback"));
}