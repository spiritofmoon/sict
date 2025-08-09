Please enter the cpp_file_v3 folder and execute the command "pip install ." to install the input_module_all_inf library

Two versions of the input checking program and two timing methods are provided:
In the all_events version, all events, including mouse movement events, are monitored. When moving the mouse, the
absolute position and relative displacement of the mouse are recorded in real-time based on the mouse reporting rate. If
the mouse reporting rate is high, (
(For example, at 1000Hz) it will occupy CPU resources more significantly
And this version uses fixed time recording, and the time can be modified by adjusting the CAPTURE_DURATION parameter

In the no_mouse_move_events version, detailed mouse positions are not required in simple training events, and this
version can be used. Mouse displacement information has been removed to reduce CPU usage, and coordinates are returned
as parameters when an input event is detected.