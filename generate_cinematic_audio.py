#!/usr/bin/env python3
"""
JARVIS Cinematic Audio Composer
Synthesizes a multi-track futuristic electronic soundtrack with sound design
and mixes in the generated JARVIS voice lines with dynamic sidechain ducking.
"""

import os
import wave
import numpy as np
from scipy.io import wavfile

SAMPLE_RATE = 44100
DURATION = 34.0
TOTAL_SAMPLES = int(SAMPLE_RATE * DURATION)

def generate_audio():
    print("[AUDIO] Synthesizing cinematic electronic score...")
    t = np.linspace(0, DURATION, TOTAL_SAMPLES, endpoint=False)
    
    # 1. Warm Analog Sub-Bass & Drone (Track 1)
    # Fundamental in D (D1 = 36.7 Hz, D2 = 73.4 Hz, F2 = 87.3 Hz, G2 = 98.0 Hz, A2 = 110.0 Hz)
    sub_bass = np.zeros(TOTAL_SAMPLES, dtype=np.float32)
    chord_times = [
        (0.0, 6.0, 36.7),    # D
        (6.0, 12.0, 29.1),   # Bb
        (12.0, 18.0, 43.6),  # F
        (18.0, 24.0, 32.7),  # C
        (24.0, 29.5, 36.7),  # D (Building)
        (29.5, 31.6, 55.0),  # A (Peak climax)
        (31.6, 34.0, 0.0)    # Silence for final line & pulse
    ]
    for start, end, freq in chord_times:
        if freq == 0: continue
        i0, i1 = int(start * SAMPLE_RATE), int(end * SAMPLE_RATE)
        seg_t = t[i0:i1]
        fade_len = int(0.3 * SAMPLE_RATE)
        env = np.ones(i1 - i0, dtype=np.float32)
        env[:fade_len] = np.linspace(0, 1, fade_len)
        env[-fade_len:] = np.linspace(1, 0, fade_len)
        wave = (np.sin(2 * np.pi * freq * seg_t) * 0.7 + 
                np.sin(2 * np.pi * freq * 2 * seg_t) * 0.25) * env
        sub_bass[i0:i1] += wave * 0.45

    # 2. Atmospheric Synth Pads (Track 2)
    # Lush stereophonic pads with gentle detune
    pad_left = np.zeros(TOTAL_SAMPLES, dtype=np.float32)
    pad_right = np.zeros(TOTAL_SAMPLES, dtype=np.float32)
    pad_chords = [
        (0.0, 6.0, [146.8, 174.6, 220.0]),   # Dm (D3, F3, A3)
        (6.0, 12.0, [116.5, 146.8, 174.6]),  # Bb (Bb2, D3, F3)
        (12.0, 18.0, [130.8, 174.6, 220.0]), # F (C3, F3, A3)
        (18.0, 24.0, [130.8, 164.8, 196.0]), # C (C3, E3, G3)
        (24.0, 29.5, [146.8, 174.6, 220.0, 293.7]), # Dm add9
        (29.5, 31.6, [164.8, 220.0, 261.6, 329.6]), # Am peak
        (31.6, 34.0, [])
    ]
    for start, end, notes in pad_chords:
        if not notes: continue
        i0, i1 = int(start * SAMPLE_RATE), int(end * SAMPLE_RATE)
        seg_t = t[i0:i1]
        fade_len = int(0.5 * SAMPLE_RATE)
        env = np.ones(i1 - i0, dtype=np.float32)
        env[:fade_len] = np.linspace(0, 1, fade_len)
        env[-fade_len:] = np.linspace(1, 0, fade_len)
        for n in notes:
            # Left slightly flat, right slightly sharp for stereo wideness
            pad_left[i0:i1] += np.sin(2 * np.pi * (n * 0.998) * seg_t) * env * 0.12
            pad_right[i0:i1] += np.sin(2 * np.pi * (n * 1.002) * seg_t) * env * 0.12

    # 3. Futuristic 16th-note Cyber Arpeggio (Track 3)
    # Starts subtle at t = 3.5s, gathers intensity, peaks at 29s - 31.5s
    arp_left = np.zeros(TOTAL_SAMPLES, dtype=np.float32)
    arp_right = np.zeros(TOTAL_SAMPLES, dtype=np.float32)
    arp_notes = [146.8, 220.0, 293.7, 349.2, 440.0, 349.2, 293.7, 220.0] # Dm pattern
    note_dur = 0.125 # 16th note at 120 BPM
    total_arp_steps = int(31.5 / note_dur)
    
    for step in range(int(3.2 / note_dur), total_arp_steps):
        st = step * note_dur
        et = st + note_dur
        if et > 31.6: break
        i0, i1 = int(st * SAMPLE_RATE), int(et * SAMPLE_RATE)
        pitch = arp_notes[step % len(arp_notes)]
        seg_t = t[i0:i1]
        decay = np.exp(-14 * (seg_t - st))
        # Intensity builds from 0.05 at 3.5s to 0.35 at 29s
        gain = 0.05 + 0.30 * ((st - 3.2) / 28.0)
        pan = 0.5 + 0.3 * np.sin(step * 0.6) # Auto-pan
        sig = (np.sin(2 * np.pi * pitch * seg_t) + 0.3 * np.sin(2 * np.pi * pitch * 2 * seg_t)) * decay * gain
        arp_left[i0:i1] += sig * (1.0 - pan)
        arp_right[i0:i1] += sig * pan

    # 4. Cinematic Percussion & Hits (Track 4)
    percussion = np.zeros(TOTAL_SAMPLES, dtype=np.float32)
    # Kick hits on downbeats starting at 6.0s (every 1.0s = 120 BPM quarter notes)
    for kt in np.arange(6.0, 31.5, 1.0):
        i0 = int(kt * SAMPLE_RATE)
        i1 = min(TOTAL_SAMPLES, i0 + int(0.25 * SAMPLE_RATE))
        dur_s = (i1 - i0) / SAMPLE_RATE
        seg_t = np.linspace(0, dur_s, i1 - i0, endpoint=False)
        pitch_drop = 120.0 * np.exp(-30 * seg_t) + 42.0
        kick = np.sin(2 * np.pi * pitch_drop * seg_t) * np.exp(-12 * seg_t)
        # Velocity increases over time
        v = 0.2 + 0.4 * ((kt - 6.0) / 25.5)
        percussion[i0:i1] += kick * v

    # 5. Cinematic Sound Effects & Impacts (Track 5)
    sfx_left = np.zeros(TOTAL_SAMPLES, dtype=np.float32)
    sfx_right = np.zeros(TOTAL_SAMPLES, dtype=np.float32)

    def add_whoosh(t_start, dur=1.2, gain=0.3):
        i0 = int(t_start * SAMPLE_RATE)
        i1 = min(TOTAL_SAMPLES, i0 + int(dur * SAMPLE_RATE))
        seg_t = np.linspace(0, dur, i1 - i0, endpoint=False)
        noise = np.random.uniform(-1, 1, i1 - i0).astype(np.float32)
        env = np.sin(np.pi * (seg_t / dur))
        sfx_left[i0:i1] += noise * env * gain * 0.4
        sfx_right[i0:i1] += noise * env * gain * 0.4

    def add_chime(t_start, pitch=1200.0, gain=0.25):
        i0 = int(t_start * SAMPLE_RATE)
        i1 = min(TOTAL_SAMPLES, i0 + int(0.4 * SAMPLE_RATE))
        seg_t = np.linspace(0, 0.4, i1 - i0, endpoint=False)
        decay = np.exp(-12 * seg_t)
        tone = np.sin(2 * np.pi * pitch * seg_t) * decay * gain
        sfx_left[i0:i1] += tone
        sfx_right[i0:i1] += tone

    def add_sub_impact(t_start, gain=0.7):
        i0 = int(t_start * SAMPLE_RATE)
        i1 = min(TOTAL_SAMPLES, i0 + int(1.5 * SAMPLE_RATE))
        seg_t = np.linspace(0, 1.5, i1 - i0, endpoint=False)
        decay = np.exp(-4 * seg_t)
        pitch = 70 * np.exp(-6 * seg_t) + 35
        boom = np.sin(2 * np.pi * pitch * seg_t) * decay * gain
        sfx_left[i0:i1] += boom
        sfx_right[i0:i1] += boom

    # Scene FX cues
    add_whoosh(0.2, dur=1.5, gain=0.3)
    add_chime(3.4, pitch=1400, gain=0.18) # Mic listen
    add_chime(6.4, pitch=1600, gain=0.18) # Data search
    add_chime(9.4, pitch=1100, gain=0.18) # Memory recall
    add_whoosh(14.8, dur=1.0, gain=0.25)  # Code scan
    add_chime(16.4, pitch=1800, gain=0.22) # Code fix
    add_chime(18.2, pitch=1350, gain=0.22) # Vision lock
    add_whoosh(23.8, dur=2.0, gain=0.35)  # Build riser
    add_sub_impact(32.4, gain=0.85)       # Final shockwave pulse impact!

    # 6. Load & Place JARVIS Voice Lines with Automatic Sidechain Ducking
    voice_track_l = np.zeros(TOTAL_SAMPLES, dtype=np.float32)
    voice_track_r = np.zeros(TOTAL_SAMPLES, dtype=np.float32)
    ducking_mask = np.ones(TOTAL_SAMPLES, dtype=np.float32)

    voice_cues = [
        (1.0, 'voice_assets/voice_01_wake.wav'),
        (3.8, 'voice_assets/voice_02_listen.wav'),
        (9.8, 'voice_assets/voice_03_memory.wav'),
        (12.8, 'voice_assets/voice_04_assist.wav'),
        (16.0, 'voice_assets/voice_05_code.wav'),
        (19.0, 'voice_assets/voice_06_vision.wav'),
        (24.8, 'voice_assets/voice_07_build.wav'),
        (31.8, 'voice_assets/voice_08_help.wav')
    ]

    for start_t, vfile in voice_cues:
        if not os.path.exists(vfile):
            print(f"[WARN] Missing voice file {vfile}")
            continue
        sr, vdata = wavfile.read(vfile)
        # Normalize to float32 [-1, 1]
        if vdata.dtype == np.int16:
            v_norm = vdata.astype(np.float32) / 32768.0
        else:
            v_norm = vdata.astype(np.float32)
        if len(v_norm.shape) == 2:
            vl = v_norm[:, 0]
            vr = v_norm[:, 1]
        else:
            vl = v_norm
            vr = v_norm

        i0 = int(start_t * SAMPLE_RATE)
        v_len = min(len(vl), TOTAL_SAMPLES - i0)
        i1 = i0 + v_len

        voice_track_l[i0:i1] += vl[:v_len] * 0.95
        voice_track_r[i0:i1] += vr[:v_len] * 0.95

        # Duck music during voice: smooth ramp down to 0.35, then ramp back up
        lead_in = int(0.15 * SAMPLE_RATE)
        lead_out = int(0.35 * SAMPLE_RATE)
        d0 = max(0, i0 - lead_in)
        d1 = min(TOTAL_SAMPLES, i1 + lead_out)
        
        # Smooth window for ducking
        duck_win = np.full(d1 - d0, 0.35, dtype=np.float32)
        duck_win[:lead_in] = np.linspace(1.0, 0.35, lead_in)
        duck_win[-lead_out:] = np.linspace(0.35, 1.0, lead_out)
        ducking_mask[d0:d1] = np.minimum(ducking_mask[d0:d1], duck_win)

    # Hard cut music at t = 31.6s for final line
    cut_i = int(31.6 * SAMPLE_RATE)
    ducking_mask[cut_i:] = 0.0

    # 7. Master Mix & Final Normalization
    music_l = (sub_bass + pad_left + arp_left + percussion + sfx_left) * ducking_mask
    music_r = (sub_bass + pad_right + arp_right + percussion + sfx_right) * ducking_mask

    master_l = music_l + voice_track_l
    master_r = music_r + voice_track_r

    # Add the final pulse impact back in at 32.4s (un-ducked)
    pulse_i0 = int(32.4 * SAMPLE_RATE)
    pulse_len = min(int(1.5 * SAMPLE_RATE), TOTAL_SAMPLES - pulse_i0)
    seg_t = np.linspace(0, 1.5, pulse_len, endpoint=False)
    final_boom = (np.sin(2 * np.pi * 48 * seg_t) * np.exp(-4 * seg_t)) * 0.8
    master_l[pulse_i0:pulse_i0+pulse_len] += final_boom
    master_r[pulse_i0:pulse_i0+pulse_len] += final_boom

    # Fade out very end
    end_fade = int(0.6 * SAMPLE_RATE)
    master_l[-end_fade:] *= np.linspace(1.0, 0.0, end_fade)
    master_r[-end_fade:] *= np.linspace(1.0, 0.0, end_fade)

    # Peak normalization to -1.0 dB
    peak = max(np.max(np.abs(master_l)), np.max(np.abs(master_r)))
    if peak > 0:
        target_peak = 0.89 # -1.0 dB
        master_l = (master_l / peak) * target_peak
        master_r = (master_r / peak) * target_peak

    stereo_output = np.column_stack((master_l, master_r))
    int16_output = (stereo_output * 32767).astype(np.int16)

    out_file = "cinematic_soundtrack.wav"
    wavfile.write(out_file, SAMPLE_RATE, int16_output)
    print(f"[AUDIO] Master soundtrack successfully created: {out_file} (Duration: {DURATION}s, {int16_output.nbytes // 1024} KB)")

if __name__ == '__main__':
    generate_audio()
