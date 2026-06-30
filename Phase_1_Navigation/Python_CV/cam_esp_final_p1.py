import cv2
import numpy as np
import serial
import serial.tools.list_ports
import time
from collections import deque
import threading

def find_arduino_port():
    """Automatically find Arduino COM port"""
    ports = serial.tools.list_ports.comports()
    for port in ports:
        if 'Arduino' in port.description or 'CH340' in port.description or 'USB' in port.description or 'CP210' in port.description:
            return port.device
    return None

def setup_serial():
    """Setup serial connection to ESP32"""
    print("\nSearching for ESP32...")
    port = find_arduino_port()
    
    if port:
        print(f"✔ Found device on {port}")
        try:
            ser = serial.Serial(port, 115200, timeout=1)
            time.sleep(2)
            print("✔ Serial connection established")
            return ser
        except Exception as e:
            print(f"✗ Error connecting: {e}")
            return None
    else:
        print("✗ ESP32 not found. Please check connection.")
        return None

def send_command(ser, command):
    """Send command to ESP32"""
    if ser and ser.is_open:
        try:
            ser.write(f"{command}\n".encode())
            ser.flush()
        except Exception as e:
            print(f"Error sending command: {e}")

class ObjectTracker:
    """Track object left/right movement - ONLY for camera"""
    def __init__(self, history_size=5, sensitivity=8):
        self.positions = deque(maxlen=history_size)
        self.last_direction = None
        self.last_command_time = 0
        self.command_cooldown = 0.15  
        self.sensitivity = sensitivity
        self.screen_center = 320  
        
    def update(self, x, screen_width):
        """Update position and determine direction"""
        self.screen_center = screen_width // 2
        self.positions.append(x)
        
        if len(self.positions) < 2:
            return None
        
        recent_movement = self.positions[-1] - self.positions[-2]
        
        if len(self.positions) >= 3:
            movements = []
            for i in range(1, len(self.positions)):
                movements.append(self.positions[i] - self.positions[i-1])
            avg_movement = sum(movements) / len(movements)
        else:
            avg_movement = recent_movement
        
        current_time = time.time()
        
        # Determine direction based on movement AND position relative to center
        new_direction = None
        
        # Use average movement for direction
        if avg_movement > self.sensitivity:
            new_direction = "RIGHT"
        elif avg_movement < -self.sensitivity:
            new_direction = "LEFT"
        
        # Send command if direction detected and cooldown passed
        if new_direction and (current_time - self.last_command_time) > self.command_cooldown:
            self.last_direction = new_direction
            self.last_command_time = current_time
            return new_direction
        
        return None
    
    def set_sensitivity(self, sensitivity):
        """Update sensitivity threshold"""
        self.sensitivity = sensitivity
    
    def reset(self):
        """Clear tracking history"""
        self.positions.clear()
        self.last_direction = None

print("=" * 70)
print("SEPARATED TOF + VISION HAPTIC SYSTEM")
print("=" * 70)
print("\nSYSTEM DESIGN:")
print("  • LRA1 (LEFT) + LRA2 (RIGHT) = Camera tracking ONLY")
print("  • LRA3 (APPROACHING) + LRA4 (GOING AWAY) = TOF sensor ONLY")
print("  • ALL activate only when MM-Wave detects motion")
print("=" * 70)

# Setup ESP32 connection
arduino = setup_serial()
if not arduino:
    print("\n⚠ Warning: Continuing without ESP32 connection")
else:
    print("✔ Haptic feedback enabled!\n")

# Initialize webcam
print("Opening webcam...")
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1080)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
cap.set(cv2.CAP_PROP_FPS, 30)

if not cap.isOpened():
    print("✗ Error: Could not open webcam")
    exit()

print("✔ Webcam opened successfully\n")

# Initialize background subtractor
fgbg = cv2.createBackgroundSubtractorMOG2(
    history=300,
    varThreshold=40,
    detectShadows=False
)

# HOG person detector
hog = cv2.HOGDescriptor()
hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

# Initialize tracker for camera-based left/right ONLY
tracker = ObjectTracker(history_size=5, sensitivity=6)  # More history, lower threshold

# Motion detection parameters
min_area = 2000
erosion_kernel = np.ones((3, 3), np.uint8)
dilation_kernel = np.ones((7, 7), np.uint8)

# Performance variables
frame_count = 0
fps_time = time.time()
fps = 0
use_hog = True
system_active = False
debug_mode = True  # Shows detailed tracking info

# Track active camera-based LRAs only (left/right)
active_camera_lras = set()

print("=" * 70)
print("CONTROLS:")
print("  q - Quit")
print("  c - Clear tracking")
print("  h - Toggle HOG person detection")
print("  d - Toggle debug mode")
print("  Space - Manual system activation")
print("  + - Increase sensitivity (lower threshold)")
print("  - - Decrease sensitivity (higher threshold)")
print("=" * 70)
print("\n⏳ Waiting for MM-WAVE MOTION SENSOR...\n")

# Serial reading thread for TOF distance monitoring
tof_distance = None
motion_detected = False
tof_lock = threading.Lock()

def read_serial_data():
    """Read motion sensor status and TOF data from ESP32"""
    global tof_distance, motion_detected, system_active
    
    buffer = ""
    while True:
        if arduino and arduino.is_open:
            try:
                if arduino.in_waiting:
                    byte = arduino.read().decode('utf-8', errors='ignore')
                    buffer += byte
                    
                    if byte == '\n':
                        line = buffer.strip()
                        buffer = ""
                        
                        # Check for motion detection from MM-wave sensor
                        if "MOTION DETECTED" in line:
                            motion_detected = True
                            system_active = True
                            print("\n MM-WAVE MOTION DETECTED - SYSTEM ACTIVATED")
                            print("    Camera tracking: ENABLED (LRA1/LRA2)")
                            print("    TOF tracking: ENABLED (LRA3/LRA4)\n")
                        
                        # Check for motion stopped
                        if "Motion stopped" in line:
                            motion_detected = False
                            system_active = False
                            print("\n  Motion stopped - ALL TRACKING DISABLED\n")
                        
                        # Parse distance data from TOF
                        if "Distance:" in line:
                            try:
                                dist_str = line.split("Distance:")[1].split("mm")[0].strip()
                                distance = int(dist_str)
                                
                                with tof_lock:
                                    tof_distance = distance
                            except:
                                pass
            except:
                pass
        time.sleep(0.01)

serial_thread = threading.Thread(target=read_serial_data, daemon=True)
serial_thread.start()

# Adjustable sensitivity
sensitivity = 6  # Lower = more sensitive

while True:
    ret, frame = cap.read()
    if not ret:
        print("Failed to grab frame")
        break
    
    frame = cv2.flip(frame, 1)
    h, w = frame.shape[:2]
    
    # Calculate FPS
    frame_count += 1
    if frame_count % 30 == 0:
        fps = 30 / (time.time() - fps_time)
        fps_time = time.time()
    
    if not system_active:
        # SYSTEM INACTIVE - waiting for MM-wave motion sensor
        cv2.rectangle(frame, (50, h//2 - 100), (w - 50, h//2 + 100), (0, 0, 0), -1)
        cv2.rectangle(frame, (50, h//2 - 100), (w - 50, h//2 + 100), (0, 0, 255), 3)
        
        cv2.putText(frame, "SYSTEM INACTIVE", (w//2 - 200, h//2 - 40), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)
        cv2.putText(frame, "Waiting for MM-Wave Motion Sensor", (w//2 - 280, h//2 + 20), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100, 100, 255), 2)
        cv2.putText(frame, "(or press SPACE for manual activation)", (w//2 - 260, h//2 + 60), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 150), 1)
    else:
        # SYSTEM ACTIVE - both camera and TOF tracking enabled
        
        # === CAMERA-BASED TRACKING (LEFT/RIGHT) ===
        fgmask = fgbg.apply(frame)
        fgmask = cv2.erode(fgmask, erosion_kernel, iterations=1)
        fgmask = cv2.dilate(fgmask, dilation_kernel, iterations=2)
        
        contours, _ = cv2.findContours(fgmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        detected_objects = []
        main_object = None
        max_area = 0
        
        for contour in contours:
            area = cv2.contourArea(contour)
            
            if area > min_area:
                x, y, w_box, h_box = cv2.boundingRect(contour)
                aspect_ratio = w_box / float(h_box) if h_box > 0 else 0
                
                if 0.2 < aspect_ratio < 5:
                    center_x = x + w_box // 2
                    center_y = y + h_box // 2
                    
                    detected_objects.append({
                        'bbox': (x, y, w_box, h_box),
                        'center': (center_x, center_y),
                        'area': area
                    })
                    
                    if area > max_area:
                        max_area = area
                        main_object = detected_objects[-1]
        
        # HOG detection
        if use_hog and frame_count % 3 == 0:
            try:
                persons, weights = hog.detectMultiScale(frame, winStride=(8, 8), 
                                                        padding=(4, 4), scale=1.05)
                
                for i, (x, y, w_box, h_box) in enumerate(persons):
                    if weights[i] > 0.5:
                        area = w_box * h_box
                        center_x = x + w_box // 2
                        center_y = y + h_box // 2
                        
                        detected_objects.append({
                            'bbox': (x, y, w_box, h_box),
                            'center': (center_x, center_y),
                            'area': area,
                            'type': 'person'
                        })
                        
                        if area > max_area:
                            max_area = area
                            main_object = detected_objects[-1]
            except:
                pass
        
        # Draw all detected objects
        for obj in detected_objects:
            x, y, w_box, h_box = obj['bbox']
            color = (255, 100, 0) if obj.get('type') == 'person' else (0, 255, 0)
            cv2.rectangle(frame, (x, y), (x + w_box, y + h_box), color, 2)
            cv2.circle(frame, obj['center'], 5, (0, 0, 255), -1)
            label = "Person" if obj.get('type') == 'person' else "Object"
            cv2.putText(frame, label, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        
        # === CAMERA LEFT/RIGHT TRACKING ===
        new_camera_lras = set()
        
        if main_object:
            center_x, center_y = main_object['center']
            direction = tracker.update(center_x, w)
            
            x, y, w_box, h_box = main_object['bbox']
            cv2.rectangle(frame, (x, y), (x + w_box, y + h_box), (0, 255, 255), 3)
            
            # Draw center reference line
            cv2.line(frame, (w//2, 0), (w//2, h), (255, 255, 0), 2)
            
            # Draw tracking trail with numbered positions
            if len(tracker.positions) > 1:
                points = [(int(pos), center_y) for pos in tracker.positions]
                for i in range(1, len(points)):
                    thickness = i + 1  # Thicker for more recent
                    cv2.line(frame, points[i-1], points[i], (255, 0, 255), thickness)
                
                # Show last 3 positions with numbers
                for i, pos in enumerate(list(tracker.positions)[-3:]):
                    cv2.circle(frame, (int(pos), center_y), 8, (0, 255, 255), -1)
                    cv2.putText(frame, str(i+1), (int(pos)-5, center_y-15), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
            
            # Display current movement with larger text
            if len(tracker.positions) >= 2:
                movement = tracker.positions[-1] - tracker.positions[-2]
                move_color = (0, 255, 0) if abs(movement) > sensitivity else (100, 100, 100)
                cv2.putText(frame, f"Movement: {movement:.1f}px", (10, 120), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, move_color, 2)
                
                # Show threshold indicator
                cv2.putText(frame, f"Threshold: {sensitivity}px", (10, 150), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
            
            # Process left/right direction with enhanced visual feedback
            if direction == "LEFT":
                new_camera_lras.add("lra1")
                # Large LEFT indicator
                cv2.rectangle(frame, (20, 50), (280, 140), (0, 0, 255), -1)
                cv2.putText(frame, "<<<< LEFT", (40, 100), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
                cv2.putText(frame, "[LRA1 ON]", (70, 130), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                
            elif direction == "RIGHT":
                new_camera_lras.add("lra2")
                # Large RIGHT indicator
                cv2.rectangle(frame, (w - 280, 50), (w - 20, 140), (0, 255, 0), -1)
                cv2.putText(frame, "RIGHT >>>>", (w - 270, 100), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
                cv2.putText(frame, "[LRA2 ON]", (w - 220, 130), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        else:
            tracker.reset()
            # Show "No object detected"
            cv2.putText(frame, "No object tracked", (10, 120), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        
        # Send camera-based commands (LEFT/RIGHT only)
        for lra in new_camera_lras - active_camera_lras:
            print(f" Camera: ✔ ACTIVATING {lra.upper()}")
            send_command(arduino, lra)
        
        for lra in active_camera_lras - new_camera_lras:
            if debug_mode:
                print(f" Camera: ✗ Deactivating {lra.upper()}")
            send_command(arduino, f"off_{lra}")
        
        active_camera_lras = new_camera_lras
        
        # DEBUG INFO
        if debug_mode and main_object:
            debug_y = 320
            cv2.rectangle(frame, (w - 250, debug_y - 30), (w - 10, debug_y + 120), (40, 40, 40), -1)
            cv2.putText(frame, "DEBUG INFO", (w - 240, debug_y), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            
            if len(tracker.positions) >= 2:
                pos_history = list(tracker.positions)
                cv2.putText(frame, f"Curr X: {pos_history[-1]:.0f}", (w - 240, debug_y + 20), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
                cv2.putText(frame, f"Prev X: {pos_history[-2]:.0f}", (w - 240, debug_y + 40), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
                
                diff = pos_history[-1] - pos_history[-2]
                diff_color = (0, 255, 0) if diff > 0 else (0, 0, 255) if diff < 0 else (150, 150, 150)
                cv2.putText(frame, f"Diff: {diff:.1f}px", (w - 240, debug_y + 60), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.4, diff_color, 1)
                
                cv2.putText(frame, f"Thresh: {sensitivity}px", (w - 240, debug_y + 80), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 0), 1)
                
                active_str = "LEFT" if "lra1" in active_camera_lras else "RIGHT" if "lra2" in active_camera_lras else "NONE"
                cv2.putText(frame, f"Active: {active_str}", (w - 240, debug_y + 100), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        
        # === TOF TRACKING (APPROACHING/GOING AWAY) ===
        # TOF is handled automatically by Arduino - just display status
        with tof_lock:
            if tof_distance is not None:
                # Draw TOF status (Arduino handles the actual LRA3/4 control)
                cv2.putText(frame, f"TOF: {tof_distance}mm", (10, 180), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
                
                # Visual indicator for TOF tracking
                cv2.rectangle(frame, (10, 200), (300, 260), (0, 0, 0), -1)
                cv2.rectangle(frame, (10, 200), (300, 260), (100, 200, 255), 2)
                cv2.putText(frame, "TOF Auto-Tracking:", (20, 225), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                cv2.putText(frame, "LRA3: Approaching", (20, 245), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)
                cv2.putText(frame, "LRA4: Going Away", (20, 260), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 165), 1)
    
    # === STATUS PANEL ===
    panel_height = 200
    cv2.rectangle(frame, (0, h - panel_height), (w, h), (0, 0, 0), -1)
    
    arduino_status = "✔ Connected" if arduino and arduino.is_open else "✗ Disconnected"
    system_status = "🟢 ACTIVE" if system_active else "🔴 INACTIVE"
    
    y_pos = h - 190
    cv2.putText(frame, f"System: {system_status} | ESP32: {arduino_status}", 
               (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    
    y_pos += 30
    cv2.putText(frame, f"FPS: {fps:.1f} | Objects: {len(detected_objects) if system_active else 0}", 
               (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    
    y_pos += 25
    cv2.putText(frame, f"Sensitivity: {sensitivity}px threshold", 
               (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 255, 255), 1)
    
    y_pos += 25
    cv2.putText(frame, "Camera Tracking:", (10, y_pos), 
               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 255, 150), 1)
    camera_status = ", ".join(sorted(active_camera_lras)) if active_camera_lras else "None"
    cv2.putText(frame, f"  Active: {camera_status}", (10, y_pos + 20), 
               cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 100), 1)
    
    y_pos += 50
    cv2.putText(frame, "TOF: Auto-controlled by Arduino (LRA3/4)", (10, y_pos), 
               cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 200, 100), 1)
    
    y_pos += 25
    cv2.putText(frame, "q=quit | c=clear | h=HOG | d=debug | Space=manual | +/- sens", 
               (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1)
    
    # Display frame
    cv2.imshow('Separated TOF + Vision Haptic System', frame)
    if system_active:
        cv2.imshow('Motion Mask', fgmask)
    
    # Keyboard controls
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        break
    elif key == ord('c'):
        tracker.reset()
        fgbg = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=40, detectShadows=False)
        print("\n[Cleared tracking & background]\n")
    elif key == ord('h'):
        use_hog = not use_hog
        print(f"\n✔ HOG person detection: {'ON' if use_hog else 'OFF'}\n")
    elif key == ord('d'):
        debug_mode = not debug_mode
        print(f"\n✔ Debug mode: {'ON' if debug_mode else 'OFF'}\n")
    elif key == ord(' '):
        if not system_active:
            # Manual activation
            system_active = True
            motion_detected = True
            send_command(arduino, "force_start")
            print("\n✅ System manually ACTIVATED\n")
        else:
            print("\n⚠️  Cannot manually deactivate - only MM-wave sensor can stop system\n")
    elif key == ord('+') or key == ord('='):
        sensitivity = max(2, sensitivity - 1)
        tracker.set_sensitivity(sensitivity)
        print(f"\n✔ Sensitivity INCREASED to {sensitivity}px (more sensitive)\n")
    elif key == ord('-') or key == ord('_'):
        sensitivity = min(20, sensitivity + 1)
        tracker.set_sensitivity(sensitivity)
        print(f"\n✔ Sensitivity DECREASED to {sensitivity}px (less sensitive)\n")

# Cleanup
if arduino and arduino.is_open:
    send_command(arduino, "off")
    arduino.close()
    print("✔ ESP32 connection closed")

cap.release()
cv2.destroyAllWindows()
print("✔ Program ended successfully")