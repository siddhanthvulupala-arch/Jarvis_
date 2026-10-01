import asyncio
import os
import subprocess
import edge_tts

lines = [
    ('voice_01_wake', 'Good morning.'),
    ('voice_02_listen', "I'm listening."),
    ('voice_03_memory', 'I remember.'),
    ('voice_04_assist', 'Consider it done.'),
    ('voice_05_code', 'I found it.'),
    ('voice_06_vision', 'I see you.'),
    ('voice_07_build', "Let's build it."),
    ('voice_08_help', 'How can I help?')
]

os.makedirs('voice_assets', exist_ok=True)

async def main():
    voice = 'en-GB-RyanNeural'
    print(f"Generating JARVIS voice lines using {voice}...")
    for name, text in lines:
        out_mp3 = os.path.join('voice_assets', f'{name}.mp3')
        comm = edge_tts.Communicate(text, voice, rate='-4%', pitch='-2Hz')
        await comm.save(out_mp3)
        # Convert to WAV for easier mixing with ffmpeg
        out_wav = os.path.join('voice_assets', f'{name}.wav')
        subprocess.run(['ffmpeg', '-y', '-i', out_mp3, '-ar', '44100', '-ac', '2', out_wav],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"Generated: {out_wav} -> \"{text}\"")

if __name__ == '__main__':
    asyncio.run(main())
