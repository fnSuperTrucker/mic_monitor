import tkinter as tk
import sounddevice as sd
import numpy as np
import time
import platform
from tkinter import ttk

# --- Audio Settings ---
samplerate = 44100
blocksize = 4096
channels = 1
audio_threshold = 0.005
CHECK_DEVICE_INTERVAL_MS = 2000
RETRY_INTERVAL_MS = 2000
STREAM_TIMEOUT_S = 5
DEVICE_REFRESH_DELAY = 0.5
MAX_RETRY_BACKOFF_MS = 5000
MAX_RETRIES = 5
VOLUME_SCALE = 100
DEBUG_VERBOSE = False  # Set to True for detailed audio logging

# --- VU Meter Settings ---
vu_width = 200
vu_height = 20
peak_color = "red"
activity_color = "green"
decay_rate = 0.98
peak_hold_time = 0.5

# --- Status Indicator Settings ---
status_width = 80
status_height = 20
no_input_color = "gray"
has_input_color = "yellow"

last_volume_norm = 0.0
update_threshold = 0.01
last_callback_time = time.time()
is_restarting = False
last_device_list = None
last_status_text = None
retry_count = 0
last_volume_log_time = 0

stream = None
current_input_device = None
root = None
vu_meter = None
input_status_indicator = None
target_device_name = "Microphone (USB Audio Device)"
target_device_indices = [1, 4, 6, 13]

class VUMeter(tk.Canvas):
    def __init__(self, master, width, height, **kwargs):
        tk.Canvas.__init__(self, master, width=width, height=height, **kwargs)
        self.width = width
        self.height = height
        self.level = 0
        self.peak = 0
        self.peak_hold_start = 0
        self.activity_bar = self.create_rectangle(0, 0, 0, height, fill=activity_color)
        self.peak_indicator = self.create_line(0, 0, 0, height, fill=peak_color, width=2)

    def set_level(self, level):
        self.level = max(0, min(1, level))
        if self.level > self.peak:
            self.peak = self.level
            self.peak_hold_start = time.time()

    def update_vu(self):
        activity_width = int(self.width * self.level)
        self.coords(self.activity_bar, 0, 0, activity_width, self.height)

        if time.time() - self.peak_hold_start < peak_hold_time:
            peak_x = int(self.width * self.peak)
            self.coords(self.peak_indicator, peak_x, 0, peak_x, self.height)
            self.itemconfig(self.peak_indicator, state=tk.NORMAL)
        else:
            self.itemconfig(self.peak_indicator, state=tk.HIDDEN)

        self.peak *= decay_rate
        self.after(50, self.update_vu)

class StatusIndicator(tk.Canvas):
    def __init__(self, master, width, height, initial_color, text, **kwargs):
        tk.Canvas.__init__(self, master, width=width, height=height, bg=initial_color, **kwargs)
        self.width = width
        self.height = height
        self.color = initial_color
        self.text_id = self.create_text(width / 2, height / 2, text=text, anchor=tk.CENTER)

    def set_color(self, color):
        if self.color != color:
            self.config(bg=color)
            self.color = color

    def set_text(self, text):
        global last_status_text
        if last_status_text != text:
            self.itemconfig(self.text_id, text=text)
            last_status_text = text

def callback(indata, frames, time_info, status):
    global vu_meter, input_status_indicator, last_volume_norm, last_callback_time, last_volume_log_time
    try:
        last_callback_time = time.time()
        if status:
            print(f"Audio input status: {status}")
            if "overflow" in str(status).lower():
                print("Input overflow detected. Scheduling stream restart.")
                if root:
                    root.after(0, schedule_stream_restart)
                raise sd.CallbackAbort
        if any(indata):
            volume_norm = np.abs(indata).mean() * VOLUME_SCALE
            # Log volume periodically if verbose debugging is enabled
            if DEBUG_VERBOSE and time.time() - last_volume_log_time > 1.0:
                print(f"Raw volume norm: {volume_norm:.3f}")
                last_volume_log_time = time.time()
            if abs(volume_norm - last_volume_norm) > update_threshold:
                last_volume_norm = volume_norm
                if root:
                    root.after(0, lambda: vu_meter.set_level(volume_norm))
            if volume_norm > audio_threshold:
                if root:
                    root.after(0, lambda: [input_status_indicator.set_color(has_input_color), input_status_indicator.set_text("Input: Yes")])
            else:
                if root:
                    root.after(0, lambda: [input_status_indicator.set_color(no_input_color), input_status_indicator.set_text("Input: No")])
        else:
            if root:
                root.after(0, lambda: vu_meter.set_level(0))
                root.after(0, lambda: [input_status_indicator.set_color(no_input_color), input_status_indicator.set_text("Input: No")])
            last_volume_norm = 0.0
    except sd.CallbackAbort:
        raise
    except Exception as e:
        print(f"Callback error: {e}")
        if root:
            root.after(0, schedule_stream_restart)

def stop_audio_stream():
    global stream
    try:
        if stream:
            stream.abort()
            stream.close()
            print("Audio stream stopped.")
        stream = None
    except Exception as e:
        print(f"Error stopping audio stream: {e}")
    finally:
        stream = None
        try:
            sd._terminate()
            sd._initialize()
            print("PortAudio refreshed.")
        except Exception as e:
            print(f"Error refreshing PortAudio: {e}")

def start_audio_stream():
    global stream, current_input_device, last_device_list
    try:
        time.sleep(DEVICE_REFRESH_DELAY)
        devices = sd.query_devices()
        input_devices = [d for d in devices if d['max_input_channels'] > 0]
        possible_devices = [d for d in input_devices if d['index'] in target_device_indices and target_device_name.lower() in d['name'].lower()]

        device_names = [d['name'] for d in input_devices]
        if device_names != last_device_list:
            print(f"Available input devices: {device_names}")
            last_device_list = device_names

        if possible_devices:
            for device in possible_devices:
                chosen_device_index = device['index']
                current_input_device = device['name']
                print(f"Attempting to start stream on {current_input_device} (index: {chosen_device_index}, hostapi: {device['hostapi']}, max_input_channels: {device['max_input_channels']})")
                try:
                    sd.check_input_settings(device=chosen_device_index, channels=channels, samplerate=samplerate)
                    stream = sd.InputStream(
                        device=chosen_device_index,
                        channels=channels,
                        samplerate=samplerate,
                        blocksize=blocksize,
                        callback=callback
                    )
                    stream.start()
                    print(f"Audio stream started on device: {current_input_device} (index: {chosen_device_index})")
                    if root:
                        root.after(0, lambda: input_status_indicator.set_text(f"Device: {current_input_device[:10]}..."))
                    return True
                except sd.PortAudioError as e:
                    print(f"Failed to start stream on {current_input_device} (index: {chosen_device_index}): {e}")
                    continue
            print(f"No valid devices found among {target_device_name} instances.")
            if root:
                root.after(0, lambda: input_status_indicator.set_text("No Device"))
            return False
        else:
            print(f"No input devices found matching '{target_device_name}' at indices {target_device_indices}.")
            if root:
                root.after(0, lambda: input_status_indicator.set_text("No Device"))
            return False
    except sd.PortAudioError as e:
        print(f"PortAudio error starting audio stream: {e}")
        if root:
            root.after(0, lambda: input_status_indicator.set_text("Stream Error"))
        return False
    except Exception as e:
        print(f"Unexpected error starting audio stream: {e}")
        if root:
            root.after(0, lambda: input_status_indicator.set_text("Stream Error"))
        return False

def schedule_stream_restart():
    global is_restarting, retry_count
    if is_restarting:
        print("Restart already in progress. Skipping.")
        return
    is_restarting = True
    try:
        stop_audio_stream()
        time.sleep(DEVICE_REFRESH_DELAY)
        devices = sd.query_devices()
        input_devices = [d for d in devices if d['max_input_channels'] > 0]
        possible_devices = [d for d in input_devices if d['index'] in target_device_indices and target_device_name.lower() in d['name'].lower()]
        if not possible_devices:
            if retry_count >= MAX_RETRIES:
                print(f"Max retries ({MAX_RETRIES}) reached. Stopping retry attempts.")
                if root:
                    root.after(0, lambda: input_status_indicator.set_text("No Device"))
                return
            retry_delay = min(RETRY_INTERVAL_MS + (retry_count * 500), MAX_RETRY_BACKOFF_MS)
            print(f"Target device '{target_device_name}' not found at indices {target_device_indices}. Retrying in {retry_delay}ms (attempt {retry_count + 1}/{MAX_RETRIES})...")
            retry_count += 1
            if root:
                root.after(retry_delay, schedule_stream_restart)
            return
        retry_count = 0
        if start_audio_stream() and stream and stream.active:
            print("Stream restarted successfully.")
        else:
            print("Failed to restart stream. Retrying...")
            if root:
                root.after(RETRY_INTERVAL_MS, schedule_stream_restart)
    except Exception as e:
        print(f"Error during stream restart: {e}")
        if root:
            root.after(RETRY_INTERVAL_MS, schedule_stream_restart)
    finally:
        is_restarting = False

def check_audio_device():
    global current_input_device, last_callback_time, last_device_list
    try:
        devices = sd.query_devices()
        input_devices = [d for d in devices if d['max_input_channels'] > 0]
        possible_devices = [d for d in input_devices if d['index'] in target_device_indices and target_device_name.lower() in d['name'].lower()]

        device_names = [d['name'] for d in input_devices]
        if device_names != last_device_list:
            print(f"Available input devices: {device_names}")
            last_device_list = device_names

        if stream and stream.active and (time.time() - last_callback_time > STREAM_TIMEOUT_S):
            print("Stream timed out. Restarting...")
            schedule_stream_restart()
            return

        if not possible_devices:
            if current_input_device:
                print(f"Device '{current_input_device}' no longer available.")
                stop_audio_stream()
                current_input_device = None
                if root:
                    root.after(0, lambda: input_status_indicator.set_text("No Device"))
            if root:
                root.after(CHECK_DEVICE_INTERVAL_MS, check_audio_device)
            return
        else:
            device_name = possible_devices[0]['name']
            if device_name != current_input_device or not (stream and stream.active):
                print(f"Input device changed to '{device_name}' or stream inactive. Restarting stream.")
                stop_audio_stream()
                current_input_device = device_name
                if start_audio_stream():
                    print("Stream restarted with new device.")
                else:
                    print("Failed to start stream with new device. Retrying...")
                    if root:
                        root.after(CHECK_DEVICE_INTERVAL_MS, check_audio_device)
                return
    except Exception as e:
        print(f"Error checking audio device: {e}")
        if root:
            root.after(0, lambda: input_status_indicator.set_text("Device Error"))
    if root:
        root.after(CHECK_DEVICE_INTERVAL_MS, check_audio_device)

def main():
    global root, vu_meter, input_status_indicator
    try:
        root = tk.Tk()
        root.title("Microphone Monitor")
        root.wm_attributes("-topmost", True)
        root.resizable(True, True)

        vu_meter = VUMeter(root, vu_width, vu_height, bg="black")
        vu_meter.pack(padx=10, pady=5, fill=tk.X, expand=True)

        input_status_indicator = StatusIndicator(root, status_width, status_height, "gray", "No Device")
        input_status_indicator.pack(padx=10, pady=5, side=tk.LEFT)

        vu_meter.update_vu()

        if not start_audio_stream():
            print("Initial stream start failed. Retrying...")
            root.after(RETRY_INTERVAL_MS, schedule_stream_restart)

        root.after(CHECK_DEVICE_INTERVAL_MS, check_audio_device)
        root.mainloop()

    except tk.TclError as e:
        print(f"Tkinter error: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        stop_audio_stream()
        root = None

if __name__ == "__main__":
    main()