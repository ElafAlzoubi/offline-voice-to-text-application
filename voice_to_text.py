"""
Voice-to-Text Desktop App
==========================
A fully offline, open-source voice-to-text transcription tool using Whisper.cpp.

Features:
- Global hotkey activation (Ctrl + Shift + V)
- Offline speech recognition via Whisper.cpp
- Automatic text insertion at cursor position
- No API calls, completely free

Author: AI Assistant
License: MIT
"""

import os
import sys
import tempfile
import subprocess
import threading
import time
import platform
from pathlib import Path
import urllib.request
import zipfile
import shutil

import sounddevice as sd
import numpy as np
from scipy.io import wavfile
import keyboard
import pyautogui

# ==================== CONFIGURATION ====================

# Hotkey configuration - HOLD TO RECORD
HOTKEY = "ctrl+space"  # Hold down Ctrl+Space while speaking, release when done

# Audio recording settings
SAMPLE_RATE = 16000  # Whisper expects 16kHz
MAX_DURATION = 30    # Maximum recording duration in seconds (safety limit)
CHANNELS = 1         # Mono audio
AUDIO_DEVICE = None  # None = use default, or specify device number (run test_microphone.py to see list)

# Whisper.cpp settings - OPTIMIZED FOR SPEED
WHISPER_MODEL = "ggml-tiny.en.bin"  # Options: tiny.en, base.en, small.en, medium.en, large
WHISPER_THREADS = 4  # Balanced threads - fast but won't freeze PC
WHISPER_BEAM_SIZE = 1  # Keep at 1 for fastest speed (greedy decoding)

# Paths
BASE_DIR = Path(__file__).parent if hasattr(__file__, '__self__') else Path(os.getcwd())
WHISPER_DIR = BASE_DIR / "whisper.cpp"
MODELS_DIR = BASE_DIR / "models"
WHISPER_EXECUTABLE = "main.exe" if platform.system() == "Windows" else "main"

# ==================== GLOBAL STATE ====================

is_recording = False
recording_thread = None
audio_data = []
stop_recording = False

# ==================== HELPER FUNCTIONS ====================

def log(message):
    """Print a timestamped log message."""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

def ensure_directories():
    """Create necessary directories if they don't exist."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    WHISPER_DIR.mkdir(parents=True, exist_ok=True)

def download_file(url, destination):
    """Download a file with progress indication."""
    log(f"Downloading {url}...")
    try:
        urllib.request.urlretrieve(url, destination)
        log(f"Downloaded to {destination}")
        return True
    except Exception as e:
        log(f"❌ Download failed: {e}")
        return False

def download_whisper_model():
    """Download the Whisper model if not present."""
    model_path = MODELS_DIR / WHISPER_MODEL
    
    if model_path.exists():
        log(f"✓ Model found: {WHISPER_MODEL}")
        return True
    
    log(f"Model not found. Downloading {WHISPER_MODEL}...")
    
    # Model download URL
    model_url = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{WHISPER_MODEL}"
    
    if download_file(model_url, model_path):
        log(f"✓ Model ready: {WHISPER_MODEL}")
        return True
    else:
        log(f"❌ Failed to download model. Please download manually from:")
        log(f"   {model_url}")
        log(f"   Save to: {model_path}")
        return False

def check_whisper_executable():
    """Check if Whisper.cpp executable exists."""
    exe_path = WHISPER_DIR / WHISPER_EXECUTABLE
    
    if exe_path.exists():
        log(f"✓ Whisper.cpp executable found")
        return True
    
    log(f"❌ Whisper.cpp executable not found at: {exe_path}")
    log(f"   Please download and compile whisper.cpp from:")
    log(f"   https://github.com/ggerganov/whisper.cpp")
    log(f"   Place the compiled '{WHISPER_EXECUTABLE}' in: {WHISPER_DIR}")
    
    system = platform.system()
    if system == "Windows":
        log(f"\n   For Windows, download pre-built binaries or compile using:")
        log(f"   1. Install CMake and Visual Studio")
        log(f"   2. git clone https://github.com/ggerganov/whisper.cpp")
        log(f"   3. cd whisper.cpp")
        log(f"   4. cmake -B build")
        log(f"   5. cmake --build build --config Release")
        log(f"   6. Copy build/bin/Release/main.exe to {WHISPER_DIR}/")
    else:
        log(f"\n   For {system}, compile using:")
        log(f"   1. git clone https://github.com/ggerganov/whisper.cpp")
        log(f"   2. cd whisper.cpp")
        log(f"   3. make")
        log(f"   4. Copy ./main to {WHISPER_DIR}/")
    
    return False

def setup_whisper():
    """Initialize Whisper.cpp components."""
    log("Setting up Whisper.cpp...")
    ensure_directories()
    
    # Check for executable
    if not check_whisper_executable():
        return False
    
    # Download model if needed
    if not download_whisper_model():
        return False
    
    log("✓ Whisper.cpp setup complete!")
    return True

# ==================== AUDIO RECORDING ====================

def record_audio_while_held():
    """
    Record audio while the hotkey is held down.
    Stops recording when key is released.
    
    Returns:
        numpy array of audio data
    """
    global stop_recording
    
    log("🎙️  Recording... (release key to stop)")
    
    try:
        recorded_chunks = []
        
        # Start recording in chunks
        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype='float32',
            device=AUDIO_DEVICE
        )
        
        stream.start()
        start_time = time.time()
        
        # Record while key is held (check every 0.1 seconds)
        while not stop_recording:
            # Check if maximum duration exceeded
            if time.time() - start_time > MAX_DURATION:
                log("⚠️  Maximum duration reached")
                break
            
            # Read audio chunk
            chunk, overflowed = stream.read(int(SAMPLE_RATE * 0.1))
            if len(chunk) > 0:
                recorded_chunks.append(chunk)
            
            time.sleep(0.01)  # Small delay to prevent CPU spinning
        
        stream.stop()
        stream.close()
        
        # Combine all chunks
        if recorded_chunks:
            audio = np.concatenate(recorded_chunks, axis=0)
            
            duration = len(audio) / SAMPLE_RATE
            log(f"✓ Recorded {duration:.1f}s")
            
            # Check audio levels
            max_amplitude = np.max(np.abs(audio))
            if max_amplitude < 0.001:
                log(f"⚠️  Very low audio - check mic volume")
            
            return audio
        else:
            log("⚠️  No audio recorded")
            return None
    
    except Exception as e:
        log(f"❌ Recording error: {e}")
        return None

def save_audio(audio, filename):
    """
    Save audio data to a WAV file.
    
    Args:
        audio: numpy array of audio data
        filename: path to save the WAV file
    """
    try:
        # Flatten to mono if needed
        if len(audio.shape) > 1:
            audio = audio.flatten()
        
        # Normalize and convert to int16
        # First normalize to prevent clipping
        max_val = np.max(np.abs(audio))
        if max_val > 0:
            audio = audio / max_val
        
        # Convert to int16 format required by Whisper
        audio_int16 = (audio * 32767).astype(np.int16)
        
        # Save as mono 16kHz WAV file
        wavfile.write(filename, SAMPLE_RATE, audio_int16)
        
    except Exception as e:
        log(f"❌ Error saving audio: {e}")
        raise

# ==================== TRANSCRIPTION ====================

def transcribe(audio_file):
    """
    Transcribe audio file using Whisper.cpp.
    
    Args:
        audio_file: path to the WAV file
        
    Returns:
        transcribed text string
    """
    log("🔄 Transcribing...")
    
    try:
        exe_path = WHISPER_DIR / WHISPER_EXECUTABLE
        model_path = MODELS_DIR / WHISPER_MODEL
        
        # Convert paths to absolute paths
        exe_path = exe_path.resolve()
        model_path = model_path.resolve()
        audio_file_abs = Path(audio_file).resolve()
        
        # Create output text file path (in temp directory)
        output_txt = str(audio_file_abs) + ".txt"
        
        # Build command - OPTIMIZED AND RELIABLE
        cmd = [
            str(exe_path),
            "-m", str(model_path),
            "-f", str(audio_file_abs),
            "-t", str(WHISPER_THREADS),       # Use 8 threads
            "-l", "en",                        # Language: English (skip auto-detect)
            "--output-txt",                    # Save output to text file
            "--no-timestamps"                  # Skip timestamp generation (faster)
        ]
        
        # Run Whisper.cpp - balanced for speed without freezing system
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60  # Increased timeout to prevent failures
        )
        
        # Check for output text file
        if os.path.exists(output_txt):
            try:
                with open(output_txt, 'r', encoding='utf-8') as f:
                    text = f.read().strip()
                
                # Clean up output file
                os.unlink(output_txt)
                
                # Clean up the text (remove extra whitespace and newlines)
                text = ' '.join(text.split())
                
                if text:
                    log(f"✓ \"{text}\"")
                    return text
                else:
                    log("⚠️  No speech detected")
                    return None
            except Exception as e:
                log(f"❌ Error reading transcription: {e}")
                return None
        else:
            log("⚠️  No speech detected or failed to create output file")
            # Show stderr for debugging
            if result.stderr:
                stderr_lines = result.stderr.strip().split('\n')
                for line in stderr_lines[:3]:  # Show first 3 lines of error
                    log(f"   Error: {line}")
            return None
            
    except subprocess.TimeoutExpired:
        log("❌ Transcription timeout - Whisper.cpp took too long")
        log("   Try speaking for a shorter duration or check system resources")
        return None
    except Exception as e:
        log(f"❌ Transcription error: {e}")
        return None

# ==================== TEXT INJECTION ====================

def type_text(text):
    """
    Type the transcribed text at the current cursor position.
    
    Args:
        text: string to type
    """
    if not text:
        return
    
    try:
        # Minimal delay for speed
        time.sleep(0.05)
        
        # Type the text FAST - no interval between characters
        pyautogui.write(text, interval=0)
        
        log("✓ Done!")
        
    except Exception as e:
        log(f"❌ Error typing text: {e}")

# ==================== MAIN WORKFLOW ====================

def process_voice_input():
    """Main workflow: record -> transcribe -> type."""
    global stop_recording
    
    # Create temporary file for audio
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_audio:
        temp_audio_path = temp_audio.name
    
    try:
        # Step 1: Record audio (while key is held)
        audio = record_audio_while_held()
        
        if audio is None:
            return
        
        # Step 2: Save to file
        save_audio(audio, temp_audio_path)
        
        # Step 3: Transcribe
        log("🔄 Transcribing...")
        text = transcribe(temp_audio_path)
        
        # Step 4: Type the text
        if text:
            type_text(text)
        
    except Exception as e:
        log(f"❌ Error in voice processing: {e}")
    
    finally:
        # Clean up temporary file
        try:
            os.unlink(temp_audio_path)
        except:
            pass

def on_hotkey_press():
    """Callback when hotkey is pressed (start recording)."""
    global recording_thread, stop_recording, is_recording
    
    # Prevent multiple recordings at once
    if is_recording:
        return
    
    is_recording = True
    stop_recording = False
    
    # Process in a separate thread to avoid blocking
    recording_thread = threading.Thread(target=process_voice_input, daemon=True)
    recording_thread.start()

def on_hotkey_release():
    """Callback when hotkey is released (stop recording)."""
    global stop_recording, is_recording
    
    stop_recording = True
    is_recording = False

# ==================== MAIN APPLICATION ====================

def check_dependencies():
    """Verify all dependencies are installed."""
    log("Checking dependencies...")
    
    required_modules = [
        ('sounddevice', 'sounddevice'),
        ('numpy', 'numpy'),
        ('scipy', 'scipy'),
        ('keyboard', 'keyboard'),
        ('pyautogui', 'pyautogui'),
    ]
    
    missing = []
    for module_name, package_name in required_modules:
        try:
            __import__(module_name)
        except ImportError:
            missing.append(package_name)
    
    if missing:
        log(f"❌ Missing dependencies: {', '.join(missing)}")
        log(f"   Install with: pip install {' '.join(missing)}")
        return False
    
    log("✓ All dependencies installed")
    return True

def main():
    """Main application entry point."""
    log("=" * 60)
    log("Voice-to-Text Desktop App")
    log("=" * 60)
    log(f"Platform: {platform.system()} {platform.release()}")
    log(f"Python: {sys.version.split()[0]}")
    log("")
    
    # Check dependencies
    if not check_dependencies():
        log("\n❌ Please install missing dependencies and restart.")
        input("Press Enter to exit...")
        return
    
    # Setup Whisper.cpp
    if not setup_whisper():
        log("\n❌ Whisper.cpp setup failed. Please follow the instructions above.")
        input("Press Enter to exit...")
        return
    
    log("")
    log("=" * 60)
    log(f"✓ Ready! HOLD {HOTKEY.upper()} while speaking")
    log("=" * 60)
    log(f"  • HOLD the key down while talking")
    log(f"  • RELEASE when done speaking")
    log(f"  • Sample rate: {SAMPLE_RATE} Hz")
    log(f"  • Model: {WHISPER_MODEL}")
    log(f"  • Press Ctrl+C to exit")
    log("=" * 60)
    log("")
    
    # Register hotkey with press and release handlers
    try:
        keyboard.on_press_key('space', lambda _: on_hotkey_press() if keyboard.is_pressed('ctrl') else None)
        keyboard.on_release_key('space', lambda _: on_hotkey_release() if not keyboard.is_pressed('space') else None)
        
        # Keep the program running
        keyboard.wait()
        
    except KeyboardInterrupt:
        log("\n👋 Shutting down...")
    except Exception as e:
        log(f"\n❌ Error: {e}")
    finally:
        log("Goodbye!")

if __name__ == "__main__":
    main()

