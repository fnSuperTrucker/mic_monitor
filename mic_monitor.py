import tkinter as tk
import sounddevice as sd
import numpy as np
import time
import platform
from tkinter import ttk

# --- Audio Settings ---
samplerate = 44100
blocksize = 4096  # Increased blocksize
channels = 1
device = None  # Use default input device
audio_threshold = 0.005  # Threshold to detect audio input

# --- VU Meter Settings ---
vu_width = 200
vu_height = 20
peak_color = "red"
activity_color = "green"
decay_rate = 0.98
peak_hold_time = 0.5  # seconds

# --- Status Indicator Settings ---
status_width = 80
status_height = 20
no_input_color = "gray"
has_input_color = "yellow"

last_volume_norm = 0.0
update_threshold = 0.01  # Adjust this value

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
        self.after(200, self.update_vu) # Less frequent peak decay update

class StatusIndicator(tk.Canvas):
    def __init__(self, master, width, height, initial_color, text, **kwargs):
        tk.Canvas.__init__(self, master, width=width, height=height, bg=initial_color, **kwargs)
        self.width = width
        self.height = height
        self.color = initial_color
        self.text_id = self.create_text(width / 2, height / 2, text=text, anchor=tk.CENTER)

    def set_color(self, color):
        self.config(bg=color)
        self.color = color

    def set_text(self, text):
        self.itemconfig(self.text_id, text=text)

def callback(indata, frames, time, status):
    global vu_meter, input_status_indicator, last_volume_norm, root
    try:
        if status:
            print(f"Audio input status: {status}")
        if any(indata):
            volume_norm = np.abs(indata).mean() * 50
            if abs(volume_norm - last_volume_norm) > update_threshold:
                vu_meter.set_level(volume_norm)
                if root:
                    root.after(0, vu_meter.update_vu) # Schedule immediate GUI update
                last_volume_norm = volume_norm
            if volume_norm > audio_threshold:
                input_status_indicator.set_color(has_input_color)
                input_status_indicator.set_text("Input: Yes")
            else:
                input_status_indicator.set_color(no_input_color)
                input_status_indicator.set_text("Input: No")
        else:
            vu_meter.set_level(0)
            if root:
                root.after(0, vu_meter.update_vu) # Update on silence too
            input_status_indicator.set_color(no_input_color)
            input_status_indicator.set_text("Input: No")
            last_volume_norm = 0.0
    except Exception as e:
        print(f"Error in callback: {e}")

root = None # Initialize root globally

try:
    with sd.InputStream(device=device, channels=channels, samplerate=samplerate, blocksize=4096, callback=callback):
        root = tk.Tk()
        root.title("Microphone Monitor")
        root.wm_attributes("-topmost", True)  # Make it always on top
        root.resizable(True, True)          # Make it resizable

        vu_meter = VUMeter(root, vu_width, vu_height, bg="black")
        vu_meter.pack(padx=10, pady=5, fill=tk.X, expand=True)

        input_status_indicator = StatusIndicator(root, status_width, status_height, "gray", "Input: No")
        input_status_indicator.pack(padx=10, pady=5, side=tk.LEFT)

        vu_meter.update_vu() # Initial call to start peak decay updates

        root.mainloop()

except sd.NoBackendError:
    print("Error: No audio backend found. Make sure you have appropriate audio drivers installed.")
except Exception as e:
    print(f"An error occurred outside the stream: {e}")
finally:
    root = None # Clean up root