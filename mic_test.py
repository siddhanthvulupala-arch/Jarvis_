import sounddevice as sd
import numpy as np

fs = 48000   # ← change THIS based on Step 1

print("Speak now...")

audio = sd.rec(int(3 * fs), samplerate=fs, channels=1, dtype='float32', device=9)
sd.wait()

energy = np.mean(np.abs(audio))
print("Energy:", energy)