import tkinter as tk
from tkinter import ttk
import sounddevice as sd
import numpy as np
import logging
import queue

# Logging setup
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Global variables
selected_device_id = None
available_devices = []
stream = None
volume_queue = queue.Queue()

# VU Meter class
class VUMeter(tk.Canvas):
    def __init__(self, master, width, height, **kwargs):
        super().__init__(master, width=width, height=height, **kwargs)
        self.width = width
        self.height = height
        self.bar = self.create_rectangle(0, 0, 0, height, fill="green")

    def set_level(self, level):
        self.coords(self.bar, 0, 0, self.width * max(0, min(1, level)), self.height)

# Audio callback function
def audio_callback(indata, frames, time, status):
    if status:
        logging.warning(f"Stream status: {status}")
    volume_norm = np.linalg.norm(indata) * 10
    volume_queue.put(volume_norm / 10)

# Start audio stream
def start_audio_stream(device_id):
    global stream
    try:
        stop_audio_stream()
        logging.info(f"Starting audio stream on device ID {device_id}")
        stream = sd.InputStream(
            device=device_id,
            channels=1,
            samplerate=44100,
            callback=audio_callback
        )
        stream.start()
        status_label.config(text="Mic Active", fg="green")
        logging.info(f"Audio stream started on device ID {device_id}")
    except sd.PortAudioError as e:
        logging.error(f"PortAudioError: {e}")
        status_label.config(text="Invalid Device", fg="red")
        stop_audio_stream()
    except Exception as e:
        logging.error(f"Error starting stream: {e}")
        status_label.config(text="Error", fg="red")
        stop_audio_stream()

# Stop audio stream
def stop_audio_stream():
    global stream
    if stream:
        try:
            logging.info("Stopping audio stream...")
            stream.stop()
            stream.close()
            logging.info("Audio stream stopped")
        except Exception as e:
            logging.error(f"Error stopping stream: {e}")
        finally:
            stream = None
            status_label.config(text="Mic Stopped", fg="gray")

# Update device list with sorting
def update_device_list():
    global available_devices, selected_device_id
    try:
        logging.info("Updating device list...")
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
        hostapi_names = {i: api['name'] for i, api in enumerate(hostapis)}

        # Filter devices with input channels
        input_devices = [d for d in devices if d['max_input_channels'] > 0]

        # Sort devices by relevance
        keywords = ["USB", "Mic", "Microphone", "Headset"]
        input_devices = sorted(
            input_devices,
            key=lambda d: any(kw.lower() in d['name'].lower() for kw in keywords),
            reverse=True
        )
        available_devices = input_devices

        if input_devices:
            device_names = [f"{d['name']} (ID: {d['index']}, Host: {hostapi_names[d['hostapi']]})" for d in input_devices]
            device_dropdown['values'] = device_names
            device_dropdown.config(state="readonly")

            if not selected_device_id or selected_device_id not in [d['index'] for d in input_devices]:
                selected_device_id = input_devices[0]['index']
                device_dropdown.current(0)
                start_audio_stream(selected_device_id)
        else:
            selected_device_id = None
            stop_audio_stream()
            device_dropdown['values'] = ["No Input Devices Found"]
            device_dropdown.current(0)
            device_dropdown.config(state="disabled")
            status_label.config(text="No Mic Found", fg="red")

        logging.info(f"Available devices: {[d['name'] for d in input_devices]}")
    except Exception as e:
        logging.error(f"Error updating device list: {e}")
        status_label.config(text="Error", fg="red")

# Handle device selection
def on_device_select(event):
    global selected_device_id
    try:
        selected_index = device_dropdown.current()
        if selected_index != -1 and available_devices:
            new_device_id = available_devices[selected_index]['index']
            if new_device_id != selected_device_id:
                selected_device_id = new_device_id
                logging.info(f"Switching to device ID {new_device_id}")
                start_audio_stream(selected_device_id)
    except Exception as e:
        logging.error(f"Error in device selection: {e}")
        status_label.config(text="Bad Input", fg="red")

# Update VU meter periodically
def update_vu_meter():
    try:
        while not volume_queue.empty():
            level = volume_queue.get()
            vu_meter.set_level(level)
    except Exception as e:
        logging.error(f"Error updating VU meter: {e}")
    root.after(100, update_vu_meter)

# Main application
def main():
    global root, vu_meter, status_label, device_dropdown
    try:
        # Initialize window
        root = tk.Tk()
        root.overrideredirect(True)
        root.geometry("250x70")
        root.configure(bg="lightgray")
        root.resizable(False, False)

        # Dragging functionality
        def start_drag(event):
            root.x_offset = event.x
            root.y_offset = event.y

        def do_drag(event):
            x = root.winfo_pointerx() - root.x_offset
            y = root.winfo_pointery() - root.y_offset
            root.geometry(f"+{x}+{y}")

        # Header frame
        header_frame = tk.Frame(root, bg="gray", height=20)
        header_frame.pack(fill=tk.X)
        header_frame.bind("<ButtonPress-1>", start_drag)
        header_frame.bind("<B1-Motion>", do_drag)

        # Status label in header
        status_label = tk.Label(header_frame, text="Initializing...", fg="black", bg="gray", font=("Arial", 8))
        status_label.pack(side=tk.LEFT, padx=5)

        # Close button
        close_button = tk.Button(
            header_frame,
            text="X",
            font=("Arial", 8, "bold"),
            bg="red",
            fg="white",
            bd=0,
            command=root.destroy,
            cursor="hand2"
        )
        close_button.pack(side=tk.RIGHT, padx=5)

        # Device dropdown
        device_dropdown = ttk.Combobox(root, state="readonly", width=30)
        device_dropdown.pack(pady=2)
        device_dropdown.bind("<<ComboboxSelected>>", on_device_select)

        # VU meter with border
        vu_frame = tk.Frame(root, bg="gray", bd=1, relief=tk.SUNKEN)
        vu_frame.pack(pady=2)
        vu_meter = VUMeter(vu_frame, width=230, height=15, bg="black")
        vu_meter.pack()

        # Initial setup
        update_device_list()

        # Periodic device check
        def periodic_device_check():
            update_device_list()
            root.after(5000, periodic_device_check)

        periodic_device_check()
        root.after(100, update_vu_meter)
        root.mainloop()
        stop_audio_stream()
    except Exception as e:
        logging.error(f"Unhandled exception in main: {e}")

if __name__ == "__main__":
    main()